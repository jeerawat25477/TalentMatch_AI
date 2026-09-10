"""คิวงานประมวลผลที่อยู่ใน Postgres — ทั้งกฎการตัดสินใจและ SQL ที่แตะตาราง.

ตั้งชื่อ job_queue ไม่ใช่ queue เพื่อไม่ให้ชวนสับสนกับโมดูล queue ของ stdlib

แบ่งเป็นสองชั้นชัด ๆ ตามแพตเทิร์นเดิมของรีโป (_bulk_partition / _is_stalled / _deletion_blocker):
  - ฟังก์ชันบริสุทธิ์ (estimate_cost / classify_failure / next_state) — ทดสอบได้โดยไม่ต้องมี DB
  - ฟังก์ชันที่แตะ DB (enqueue / claim_next / mark / reclaim_running) เป็น SQL ล้วน
    ไม่มี logic ตัดสินใจอยู่ข้างใน

ไม่ใช้ Redis/Celery/RabbitMQ โดยตั้งใจ: Postgres มีอยู่แล้วและ FOR UPDATE SKIP LOCKED
ให้การหยิบงานแบบอะตอมมิกได้ครบ การเพิ่ม broker ใหม่คือ dependency ที่ต้องดูแลอีกตัว
โดยไม่ได้อะไรเพิ่มในสเกลเรพลิกาเดียว (ดู CLAUDE.md)
"""
import logging
import os
from typing import Any, Literal, Optional

from psycopg.types.json import Json

from app.agents.llm import _RETRYABLE_MARKERS
from app.database import get_conn

log = logging.getLogger(__name__)

Kind = Literal["process", "resume_after_decision", "reprocess"]
Status = Literal["queued", "running", "done", "failed", "deferred_quota"]
Outcome = Literal["ok", "quota", "temporary", "permanent"]

# สถานะที่แปลว่า "ยังมีคนดูแลงานนี้อยู่" — ใช้ทั้งกันป้าย stalled และโชว์ให้ HR เห็น
PENDING_STATUSES = ("queued", "running", "deferred_quota")

# ต้นทุน chat call ต่องานหนึ่งชิ้น — **วัดจริงจากการรันทั้งชุด 2026-09-10**
# (ผู้สมัคร 3 คนกับ JD หนึ่งใบใช้ไป 14 call พอดี: 1 + 4 + 4 + 5)
#   process/reprocess = resume_parser 2 (โปรไฟล์ + หาหลักฐานทักษะ ตั้งแต่เฟส 1)
#                       + bias_auditor 1 + email_drafter 1  = 4
#                       + interview_planner อีก 1 ถ้าคะแนนสูงจน auto-advance = 5
#     (jd_analyzer ถูกข้ามเพราะส่ง analyzed_jd เข้าไปแล้ว, matcher ไม่ใช้ LLM)
#   resume_after_decision = interview_planner + email_drafter = 2
#     (ตัวเลขเดียวกับที่ hr.py::MAX_BULK_DECISION อ้างอิงอยู่)
# ⚠️ เอกสารเก่า (memory-bank/CLAUDE.md) เขียนว่า 3 — ตัวเลขนั้นมาจากก่อนเฟส 1 เพิ่ม
# LLM call ที่สองใน resume_parser จึงต่ำกว่าความจริงไปหนึ่ง
# เลือกคิดเผื่อฝั่งแพง: ประมาณสูงไป = พักงานเร็วไปนิด (รอบหน้าก็รัน) ส่วนประมาณต่ำไป
# = เริ่มงานแล้วตายกลางทางเพราะ 429 ซึ่งเสีย call ที่ยิงไปแล้วฟรี ๆ
COST_BY_KIND: dict[str, int] = {
    "process": 5,
    "reprocess": 5,
    "resume_after_decision": 2,
}
_DEFAULT_COST = 5

# จำนวนครั้งที่ยอมให้ลองใหม่เมื่อเจอ error **ชั่วคราว** (โควตาหมดไม่นับเป็น attempt)
MAX_QUEUE_ATTEMPTS = int(os.getenv("QUEUE_MAX_ATTEMPTS", "3"))
# เว้นระยะก่อนหยิบงานที่ถูกพักเพราะโควตากลับมาเช็คใหม่ (วินาที)
DEFERRED_RETRY_SEC = int(os.getenv("QUEUE_DEFERRED_RETRY_SEC", "600"))

# คีย์เวิร์ดของ "โควตาหมด" — ต้องแยกออกจาก error ชั่วคราวอื่นให้ได้
# ถ้าปนกัน โควตาหมดจะกิน attempts จนกลายเป็น failed ทั้งที่พรุ่งนี้รันได้สบาย
_QUOTA_MARKERS = ("resource_exhausted", "quota", "429")


def estimate_cost(kind: str) -> int:
    """งานชนิดนี้กิน chat call กี่ครั้ง (ชนิดที่ไม่รู้จัก = คิดแพงสุดไว้ก่อน)."""
    return COST_BY_KIND.get(kind, _DEFAULT_COST)


def classify_failure(exc: BaseException) -> Outcome:
    """แยกสาเหตุที่งานล้ม เป็น 3 ทางที่ปฏิบัติต่างกันสิ้นเชิง.

      quota     → พักไว้ (deferred_quota) พรุ่งนี้ค่อยรัน ไม่เสีย attempt
      temporary → ลองใหม่ (503/timeout/เน็ตสะดุด)
      permanent → เลิก (404/คีย์ผิด/ข้อมูลไม่ครบ) ยิงซ้ำอีกกี่ครั้งก็เหมือนเดิม

    ใช้ _RETRYABLE_MARKERS จาก agents/llm.py เป็นฐานของ "temporary" แทนการเขียน
    รายการซ้ำ — ไม่งั้นสองที่จะค่อย ๆ หลุดไม่ตรงกัน
    """
    text = str(exc).lower()
    if any(m in text for m in _QUOTA_MARKERS):
        return "quota"
    if any(m in text for m in _RETRYABLE_MARKERS):
        return "temporary"
    return "permanent"


def next_state(outcome: Outcome, attempts: int) -> tuple[Status, int]:
    """สถานะและจำนวน attempts ถัดไปของงาน หลังรันเสร็จหนึ่งรอบ.

    `attempts` ที่รับเข้ามาคือค่าก่อนรอบนี้ · quota ไม่เพิ่ม attempts โดยตั้งใจ:
    การที่วันนี้โควตาหมดไม่ใช่ความผิดของงานชิ้นนั้น ถ้านับรวมกัน งานจะหมดสิทธิ์
    ลองใหม่ตั้งแต่ยังไม่เคยได้รันจริงสักครั้ง
    """
    if outcome == "ok":
        return "done", attempts
    if outcome == "quota":
        return "deferred_quota", attempts
    if outcome == "temporary" and attempts + 1 < MAX_QUEUE_ATTEMPTS:
        return "queued", attempts + 1
    return "failed", attempts + 1


# ---------- ส่วนที่แตะ DB ----------


def enqueue(
    candidate_id: str, job_id: str | None, kind: Kind, payload: dict | None = None
) -> None:
    """ใส่งานหนึ่งชิ้นลงคิว (เรียกจากเธรดของ request — เร็ว ไม่บล็อก)."""
    enqueue_many([(candidate_id, job_id, kind, payload)])


def enqueue_many(rows: list[tuple]) -> None:
    """ใส่หลายงานในทรานแซกชันเดียว — ทั้ง batch เข้าคิวพร้อมกันหรือไม่เข้าเลย."""
    if not rows:
        return
    with get_conn() as conn:
        for candidate_id, job_id, kind, payload in rows:
            conn.execute(
                """INSERT INTO processing_queue (candidate_id, job_id, kind, payload)
                   VALUES (%s, %s, %s, %s)""",
                (
                    str(candidate_id),
                    str(job_id) if job_id else None,
                    kind,
                    Json(payload or {}),
                ),
            )
        conn.commit()
    log.info("เข้าคิว %s งาน (kind=%s)", len(rows), rows[0][2])


def claim_next() -> Optional[dict[str, Any]]:
    """หยิบงานเก่าสุดที่ยังรอ แล้วตีตรา 'running' ในคำสั่งเดียว (อะตอมมิก).

    FOR UPDATE SKIP LOCKED ทำให้ต่อให้มี worker หลายตัวก็ไม่มีทางหยิบงานชิ้นเดียวกัน
    (ตอนนี้มีตัวเดียว แต่ค่าใช้จ่ายของการเขียนให้ถูกตั้งแต่แรกเป็นศูนย์)

    รวม deferred_quota ที่พักครบเวลาแล้วเข้ามาด้วย — มันเป็นสถานะ "พัก" ไม่ใช่ปลายทาง
    จึงไม่ต้องมี cron ปลุกตอนเที่ยงคืน และไม่ต้องรู้ว่าโควตาจริงรีเซ็ตกี่โมง
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE processing_queue
               SET status = 'running', updated_at = timezone('utc'::text, now())
             WHERE id = (
                    SELECT id FROM processing_queue
                     WHERE status = 'queued'
                        OR (status = 'deferred_quota'
                            AND updated_at < timezone('utc'::text, now())
                                             - make_interval(secs => %s))
                     ORDER BY created_at
                     LIMIT 1
                     FOR UPDATE SKIP LOCKED
                   )
            RETURNING id, candidate_id, job_id, kind, payload, attempts
            """,
            (DEFERRED_RETRY_SEC,),
        ).fetchone()
        conn.commit()
    return dict(row) if row else None


def mark(queue_id: str, status: Status, attempts: int, error: str | None = None) -> None:
    """บันทึกผลของงานหนึ่งชิ้น (last_error เก็บเฉพาะตอนล้ม ตอนสำเร็จล้างทิ้ง)."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE processing_queue
                  SET status = %s, attempts = %s, last_error = %s,
                      updated_at = timezone('utc'::text, now())
                WHERE id = %s""",
            (status, attempts, (error or "")[:2000] or None, queue_id),
        )
        conn.commit()


def reclaim_running() -> int:
    """ดึงงานที่ค้างสถานะ 'running' กลับเป็น 'queued' — เรียกตอนแอปบูตเท่านั้น.

    **นี่คือจุดที่แก้ปัญหา "งานหายตอนรีสตาร์ต" ทั้งปัญหา** ณ ตอนแอปเพิ่งบูต ไม่มี
    งานไหนกำลังรันจริง แถวที่ยังเป็น running จึงเป็นเศษจากโปรเซสที่ตายไปกลางคัน
    เดิมงานพวกนั้นหายถาวรและผู้สมัครค้างเป็น "กำลังวิเคราะห์…" ตลอดกาล
    """
    with get_conn() as conn:
        rows = conn.execute(
            """UPDATE processing_queue
                  SET status = 'queued', updated_at = timezone('utc'::text, now())
                WHERE status = 'running'
            RETURNING id"""
        ).fetchall()
        conn.commit()
    if rows:
        log.warning("กู้งานที่ค้างจากรอบก่อน %s ชิ้นกลับเข้าคิว", len(rows))
    return len(rows)


def pending_status(candidate_id: str) -> Optional[str]:
    """สถานะคิวที่ยังทำงานอยู่ของผู้สมัครคนนี้ (None = ไม่มีอะไรค้าง).

    ใช้ตอนกดปุ่มรายคน (reprocess/ตัดสิน) — ทะเบียน _active ในโปรเซสหายไปเมื่อรีสตาร์ต
    แต่แถวในคิวไม่หาย ถ้าเช็คแค่ทะเบียนอย่างเดียว หลังรีสตาร์ตจะสั่งงานซ้ำเข้าคิวได้
    """
    with get_conn() as conn:
        row = conn.execute(
            """SELECT status FROM processing_queue
                WHERE candidate_id = %s AND status = ANY(%s)
                ORDER BY created_at LIMIT 1""",
            (str(candidate_id), list(PENDING_STATUSES)),
        ).fetchone()
    return row["status"] if row else None
