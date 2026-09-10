"""ด่านรับไฟล์เรซูเม่ — **แหล่งความจริงเดียว** ของทั้งการอัปโหลดและปากทางอีเมล.

เดิมลำดับด่านนี้ฝังอยู่ใน routers/candidates.py::upload_resumes ซึ่งเป็น async handler
พอมีทางเข้าที่สอง (email_intake.py) การเขียนลำดับเดิมซ้ำอีกชุดจะกลายเป็นกฎความปลอดภัย
สองสำเนาที่หลุดกันได้เงียบ ๆ — บทเรียนเดียวกับ compute_fit_score และ bands.py
และตรงกับที่ CLAUDE.md บันทึกไว้ว่า reprocess เรียกฟังก์ชันเดียวกับ upload
"so the two entry points cannot disagree"

ลำดับด่าน (ห้ามสลับ):
  1. magic byte  — ตัดสินจากไบต์จริง ไม่ใช่นามสกุลหรือ Content-Type ที่ผู้ส่งกำหนดเอง
  2. ขนาดไฟล์   — กัน DoS / decompression bomb
  3. sha256 ซ้ำ  — เช็ค **ก่อน** แกะข้อความ ไฟล์ที่เคยเห็นแล้วไม่ต้องเสียเวลาแกะซ้ำ
  4. แกะข้อความ  — ล้มได้ ไม่ควรทำให้ทั้งชุดพัง
  5. อ่านไม่ออก  — กันเรซูเม่สแกน/ถ่ายรูปที่จะเสียโควตา LLM ไปอ่านความว่างเปล่า
  6. INSERT      — ON CONFLICT DO NOTHING กันสองทางเข้าแทรกไฟล์เดียวกันพร้อมกัน

**คืนคำตัดสิน ไม่ raise** โดยตั้งใจ: เราเตอร์ต้องแปลงเป็น HTTPException (400/413) ส่วน
worker ต้องแปลงเป็น log + แถวใน email_intake_log — ถ้าฟังก์ชันนี้ raise HTTPException เอง
เลเยอร์ที่ไม่ใช่ HTTP จะต้องมาดัก exception ของ HTTP ซึ่งผิดที่ผิดทาง
"""
import hashlib
import logging
import os
from enum import Enum
from pathlib import PurePath
from typing import Optional
from uuid import UUID

from app.utils.pdf_extractor import extract_text_from_pdf

log = logging.getLogger(__name__)

# จำกัดการอัปโหลดกัน DoS — ไฟล์ใหญ่/เยอะเกินจะกิน RAM (อ่านทั้งไฟล์เข้าหน่วยความจำ)
# และตัวแกะ PDF อาจเจอไฟล์ที่ออกแบบมาให้หนัก (decompression bomb) ปรับผ่าน env
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_FILES = int(os.getenv("MAX_FILES", "20"))
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
PDF_MAGIC = b"%PDF-"  # PDF จริงต้องขึ้นต้นด้วยไบต์ชุดนี้ ไม่เชื่อแค่ชื่อไฟล์ .pdf

# เรซูเม่ที่สั้นกว่านี้ถือว่า "อ่านไม่ออก" — เทียบกับของจริง: sample อังกฤษสั้นสุด ~350 ตัวอักษร
# เรซูเม่ไทยจริงที่ทดสอบไว้ 1,951 และ 2,870 ตัวอักษร เกณฑ์นี้จึงกว้างพอที่ของดีจะผ่านหมด
MIN_RESUME_TEXT_CHARS = int(os.getenv("MIN_RESUME_TEXT_CHARS", "80"))


class Verdict(str, Enum):
    """ผลการตัดสินของด่าน — ผู้เรียกแปลงเป็นภาษาของตัวเอง (HTTP status / log)."""

    ACCEPTED = "accepted"
    NOT_PDF = "not_pdf"
    TOO_LARGE = "too_large"
    DUPLICATE = "duplicate"
    UNREADABLE = "unreadable"


def is_unreadable_resume(text: str) -> bool:
    """PDF ใบนี้ไม่มีข้อความให้ใช้งานใช่ไหม (เรซูเม่สแกน/ถ่ายรูป = มีแต่ภาพ ไม่มีชั้นข้อความ).

    ถ้าไม่กันตรงนี้ ระบบจะสร้างผู้สมัครที่ข้อมูลว่างแล้วยิงเข้ากราฟต่อ = เสียโควตาหลาย
    chat call ต่อไฟล์ (จาก 20/วัน) เพื่อให้ AI วิเคราะห์ความว่างเปล่า แล้วได้คะแนนมั่ว ๆ
    ปนในรายชื่อ โดย HR ไม่รู้ตัวเพราะ API ตอบเหมือนสำเร็จปกติ

    นับเฉพาะอักขระที่ไม่ใช่ช่องว่าง — บาง PDF คืนช่องว่าง/ขึ้นบรรทัดมาเป็นพรืดโดยไม่มีเนื้อจริง
    ขอบเขต: บอกได้แค่ "มีข้อความพอไหม" ไม่ได้บอกว่า "เป็นเรซูเม่จริงไหม" — ไฟล์สแกนที่มี
    กล่องข้อความปนมาเกินเกณฑ์จะยังหลุดผ่าน ซึ่งต้องใช้ OCR ถึงจะครอบได้ (คนละขนาดงาน)
    """
    return len("".join((text or "").split())) < MIN_RESUME_TEXT_CHARS


def is_duplicate_upload(
    digest: str, seen_in_batch: set[str], existing_in_job: set[str]
) -> bool:
    """ไฟล์นี้เคยเห็นแล้วหรือยัง — ทั้งในชุดที่รับมาพร้อมกัน และในตำแหน่งงานนี้.

    ตัดสินด้วย hash ของไบต์ ไม่ใช่ชื่อไฟล์ (เปลี่ยนได้) และไม่ใช่อีเมล (ตอนรับไฟล์ยังไม่มี —
    LLM ยังไม่ได้แกะ และค่าที่แกะมาจาก PDF ที่ใครก็ส่งมาได้ก็เชื่อไม่ได้อยู่ดี)
    ไฟล์ซ้ำหนึ่งใบ = ผู้สมัครเกินมาหนึ่งแถว + กราฟรันฟรีอีกรอบ (หลาย chat call จากโควตา 20/วัน)
    """
    return digest in seen_in_batch or digest in existing_in_job


def existing_hashes_for_job(conn, job_id: str) -> set[str]:
    """sha256 ของเรซูเม่ทุกใบที่ตำแหน่งงานนี้มีอยู่แล้ว (ใช้เป็นชุดเทียบซ้ำ)."""
    return {
        r["resume_sha256"]
        for r in conn.execute(
            """SELECT resume_sha256 FROM candidates
               WHERE job_id = %s AND resume_sha256 IS NOT NULL""",
            (job_id,),
        ).fetchall()
    }


def admit_resume(
    conn,
    job_id: str,
    filename: str,
    content: bytes,
    seen_in_batch: set[str],
    existing_in_job: set[str],
) -> tuple[Verdict, Optional[UUID]]:
    """ตัดสินไฟล์หนึ่งใบและสร้างแถวผู้สมัครถ้าผ่าน — คืน (คำตัดสิน, candidate_id).

    ไม่ commit ให้: ผู้เรียกคุมขอบเขตทรานแซกชันเอง (อัปโหลดหลายไฟล์ = ก้อนเดียว)
    ไม่ enqueue ให้: การเข้าคิวเป็นเรื่องของผู้เรียก ซึ่งอาจต้องจอง _active ก่อนด้วย
    """
    if not content.startswith(PDF_MAGIC):
        return Verdict.NOT_PDF, None
    if len(content) > MAX_BYTES:
        return Verdict.TOO_LARGE, None

    # เช็คซ้ำ "ก่อน" แกะข้อความ — ไฟล์ที่เคยเห็นแล้วไม่ต้องเสียเวลาแกะซ้ำ
    digest = hashlib.sha256(content).hexdigest()
    if is_duplicate_upload(digest, seen_in_batch, existing_in_job):
        return Verdict.DUPLICATE, None
    seen_in_batch.add(digest)

    # แกะข้อความแบบ graceful — PDF เสีย/แกะไม่ได้ ไม่ควรล้มทั้งชุด
    try:
        raw = extract_text_from_pdf(content)
    except Exception as exc:  # noqa: BLE001
        log.warning("แกะข้อความจาก %s ไม่สำเร็จ: %s", filename, exc)
        raw = ""

    if is_unreadable_resume(raw):
        log.info("ข้ามไฟล์ %s — สกัดข้อความไม่ได้/สั้นเกินเกณฑ์", filename)
        seen_in_batch.discard(digest)  # ไม่ได้บันทึกลง DB จึงไม่ควรกันไฟล์นี้ในรอบถัดไป
        return Verdict.UNREADABLE, None

    # full_name ชั่วคราวจากชื่อไฟล์ — resume_parser จะอัปเดตเป็นชื่อจริงภายหลัง
    placeholder_name = PurePath(filename or "resume.pdf").stem[:255] or "ไม่ทราบชื่อ"
    # ON CONFLICT กันเคสสองทางเข้ารับไฟล์เดียวกันพร้อมกัน (เช็คข้างบนไม่เห็นกันข้าม request)
    # ใช้แทนการ catch UniqueViolation เพราะ statement ที่ error จะทำให้ทรานแซกชันทั้งก้อน
    # abort ต้องไปตั้ง SAVEPOINT เพิ่ม — DO NOTHING จบในตัวและอะตอมมิกกว่า
    row = conn.execute(
        """
        INSERT INTO candidates (job_id, full_name, raw_resume_text, resume_sha256)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (job_id, resume_sha256) DO NOTHING
        RETURNING id
        """,
        (job_id, placeholder_name, raw, digest),
    ).fetchone()
    if row is None:  # มีคนอื่นแทรกไฟล์เดียวกันเข้าไปก่อนแล้ว
        return Verdict.DUPLICATE, None
    return Verdict.ACCEPTED, row["id"]
