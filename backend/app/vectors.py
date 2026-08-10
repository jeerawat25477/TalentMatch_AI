"""คลังเวกเตอร์ของ resume — index และค้นหาผู้สมัครเก่าด้วยความหมาย.

ตาม vectordb_chroma.md §1.2 แต่ใช้ **pgvector** แทน Chroma เพราะมี Postgres อยู่แล้ว
ใน compose (join กับ candidates/jobs ได้ตรง ๆ) และตรงกับ path Supabase ใน CLAUDE.md

⚠️ ขอบเขตการใช้งาน: ที่นี่คือ "จัดอันดับให้ HR ดู" เท่านั้น **ห้ามเอาไปใช้ตัดสินว่าทักษะ
ตรงหรือไม่ตรง** — วัดจริงแล้ว cosine ของ gemini-embedding-001 ให้ PostgreSQL↔MySQL = 0.885
และ Java↔JavaScript = 0.865 ซึ่งสูงกว่าคู่ที่ควรตรงจริงอย่าง React Native↔Mobile Hybrid (0.838)
จึงไม่มี threshold ที่แยกถูก การเทียบทักษะอยู่ที่ app/agents/skills.py แบบ deterministic

โมเดล: บรีฟระบุ models/text-embedding-004 แต่คีย์ปัจจุบันเรียกไม่ได้แล้ว (ไม่อยู่ใน ListModels)
ตัวที่ใช้ได้คือ gemini-embedding-001 ซึ่งคืน 3072 มิติโดยดีฟอลต์ แต่รองรับการตัดเหลือ 768
(Matryoshka) จึงยังคงคอลัมน์ VECTOR(768) ตามที่ CLAUDE.md กำหนดไว้ได้
"""
import logging
import os
from typing import Optional

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.agents.llm import MAX_ATTEMPTS, MAX_BACKOFF, _is_retryable
from app.database import get_conn

log = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
# ต้องตรงกับ VECTOR(n) ใน schema.sql เสมอ — แก้ตัวใดตัวหนึ่งแล้วอีกตัวต้องตามด้วย
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

# ตัดข้อความ resume ก่อน embed — กัน payload ใหญ่เกินและลดเวลา
MAX_CHARS = int(os.getenv("EMBEDDING_MAX_CHARS", "8000"))

_embeddings: Optional[GoogleGenerativeAIEmbeddings] = None


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """คืนตัว embed (สร้างครั้งเดียว) — แบบเดียวกับ llm.get_llm()."""
    global _embeddings
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            output_dimensionality=EMBEDDING_DIM,
        )
    return _embeddings


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=MAX_BACKOFF),
    retry=retry_if_exception(_is_retryable),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def embed(text: str) -> list[float]:
    """แปลงข้อความเป็นเวกเตอร์ พร้อม backoff เมื่อชน rate limit (เหมือน structured_invoke).

    โควตา embedding แยกจาก generateContent แต่ยังเจอ 429 ได้ถ้ายิงถี่
    """
    return get_embeddings().embed_query(text[:MAX_CHARS])


def index_candidate(candidate_id: str, text: str) -> None:
    """เพิ่ม/อัปเดตเวกเตอร์ของผู้สมัครหนึ่งคน (upsert ผ่าน UNIQUE(candidate_id))."""
    if not (text or "").strip():
        return
    content = text[:MAX_CHARS]
    vector = embed(content)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO resume_embeddings (candidate_id, embedding, content)
               VALUES (%s, %s, %s)
               ON CONFLICT (candidate_id)
               DO UPDATE SET embedding = EXCLUDED.embedding,
                             content   = EXCLUDED.content""",
            (candidate_id, str(vector), content),
        )
        conn.commit()


def search(
    query: str, limit: int = 10, exclude_candidate_id: str | None = None
) -> list[dict]:
    """ค้นผู้สมัครที่ประวัติใกล้เคียงข้อความค้นหาที่สุด (cosine distance — น้อย = ใกล้).

    exclude_candidate_id: กันไม่ให้ผู้สมัครคนนั้นเจอตัวเอง — ใช้ตอน retrieval agent
    หาคนคล้าย ๆ (ตอน re-run แบบ HITL ผู้สมัครถูก index แล้วจะ match ตัวเองด้วย distance 0)
    """
    if not (query or "").strip():
        return []
    vector = str(embed(query))
    exclude = str(exclude_candidate_id) if exclude_candidate_id else None
    with get_conn() as conn:
        # คนเดียวกันมีหลายแถวได้ (candidates ผูกกับ job — สมัคร 5 ตำแหน่ง = 5 แถว)
        # การค้นหา "ผู้สมัครเก่า" ต้องคืนคนละหนึ่งครั้ง จึง DISTINCT ON เนื้อ resume
        # และเลือกแถวที่ resume_parser แกะชื่อจริงแล้ว (parsed_resume ไม่ NULL) มาเป็นตัวแทน
        rows = conn.execute(
            """WITH ranked AS (
                   SELECT DISTINCT ON (re.content)
                          c.id, c.full_name, c.email, c.job_id,
                          j.title AS job_title,
                          e.fit_score,
                          re.embedding <=> %s::vector AS distance
                   FROM resume_embeddings re
                   JOIN candidates c ON c.id = re.candidate_id
                   LEFT JOIN jobs j        ON j.id = c.job_id
                   LEFT JOIN evaluations e ON e.candidate_id = c.id
                   WHERE (%s::uuid IS NULL OR c.id <> %s::uuid)
                   ORDER BY re.content,
                            (c.parsed_resume IS NULL),   -- false มาก่อน = ชื่อจริง
                            c.created_at DESC
               )
               SELECT * FROM ranked ORDER BY distance LIMIT %s""",
            (vector, exclude, exclude, limit),
        ).fetchall()
    return [dict(r) for r in rows]
