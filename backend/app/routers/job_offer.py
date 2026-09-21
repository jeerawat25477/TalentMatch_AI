"""เราเตอร์ข้อเสนอจ้างงาน (ขั้น "ยื่นข้อเสนอ") — HR กรอกเองล้วน ๆ.

ในชีวิตจริง HR โทรยื่นข้อเสนอและต่อรองกันนอกระบบ แล้วส่ง Offer Letter ตามแบบฟอร์มของ
บริษัท ไฟล์นี้ไม่ได้ทำแทนส่วนไหนเลย แค่ **ช่วยจำ** ว่ายื่นอะไรไป ต้องตอบภายในเมื่อไหร่
และผู้สมัครตอบว่าอะไร — พอตอบรับ หน้าต่างรับเข้าเป็นพนักงานจะเติมค่าจากข้อเสนอให้

**ไม่ import อะไรจาก agents/ ไม่เรียก LLM** เหมือน interview_outcome.py / hiring_board.py

❗ **ห้ามเขียน hr_decisions จากที่นี่** เหตุผลเดียวกับ interview_outcome.py: คำตัดสินนั้น
ตอบว่า "ผ่านคัดกรองไหม" และ route_candidates อ่านไปเลือกเส้นทางของกราฟ ถ้าผู้สมัครปฏิเสธ
ข้อเสนอแล้วไปเขียนทับเป็น rejected กราฟจะถูกปลุกให้ร่างอีเมลปฏิเสธและเผาโควตาเอง
❗ **ตอบรับ ≠ จ้าง** ที่นี่ไม่สร้างแถวใน employees เด็ดขาด การจ้างเป็นระเบียนถาวรที่ต้อง
กรอกข้อมูลจ้างและกดยืนยันในหน้าต่างรับเข้า (POST /candidates/{id}/hire)
❗ salary เป็นข้อมูลอ่อนไหว — log ได้แค่ candidate_id กับสถานะ ห้าม log payload
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.database import get_conn
from app.schemas import JobOffer, JobOfferResponseIn, JobOfferUpsert

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT เหมือนทุก router อื่น
router = APIRouter(
    prefix="/api/v1", tags=["job-offer"], dependencies=[Depends(get_current_user)]
)

_OFFER_COLUMNS = """position, salary, start_date, respond_by, note, response,
                   decline_reason, offered_at, responded_at, updated_at"""

# ขั้นที่ยังมาไม่ถึงการยื่นข้อเสนอ จึงเลื่อนขึ้นมาได้เมื่อบันทึกข้อเสนอ
_ADVANCE_TO_OFFER_FROM = ("invited", "scheduled", "interviewed")


def _next_stage_after_offer(current: Optional[str]) -> Optional[str]:
    """ขั้นใหม่หลังบันทึกข้อเสนอ หรือ None ถ้าไม่ต้องแตะ hiring_stage — ฟังก์ชันบริสุทธิ์.

    กฎเดียวกับ interview_outcome._next_stage_after_outcome คือ **เลื่อนขึ้นได้อย่างเดียว**:
    - ไม่มีแถว / invited / scheduled / interviewed -> 'offer' (บันทึกข้อเสนอ = ยื่นแล้ว
      HR ไม่ต้องกลับไปลากการ์ดซ้ำ)
    - offer -> None แก้ข้อเสนอเฉย ๆ ต้องไม่ทำให้ moved_at ขยับ
    - declined -> None การ์ดที่ HR พักไว้ต้องไม่ถูกปลุกด้วยการแก้ข้อเสนอ ต้องดึงกลับเองก่อน
    """
    return "offer" if current is None or current in _ADVANCE_TO_OFFER_FROM else None


def _stage_after_response(response: str, current: Optional[str]) -> Optional[str]:
    """ขั้นใหม่หลังบันทึกคำตอบของผู้สมัคร หรือ None ถ้าไม่ต้องแตะ — ฟังก์ชันบริสุทธิ์.

    - ปฏิเสธ -> 'declined' (ปิดกระบวนการ) ถ้ายังไม่อยู่ที่นั่น
    - ตอบรับ -> ขั้นไม่เปลี่ยน (ยังไม่ได้จ้าง การจ้างเกิดในหน้าต่างรับเข้า) ยกเว้นกำลังอยู่
      'declined' ซึ่งแปลว่า HR กดปฏิเสธผิดแล้วมาแก้ -> ดึงกลับไป 'offer'
    """
    if response == "declined":
        return None if current == "declined" else "declined"
    return "offer" if current == "declined" else None


def _move_stage(conn, candidate_id: str, stage: str) -> None:
    """ย้ายขั้นในทรานแซกชันเดียวกับการบันทึกข้อเสนอ/คำตอบ — ล้มอันใดอันหนึ่งต้องไม่เหลือสภาพครึ่ง ๆ."""
    conn.execute(
        """
        INSERT INTO hiring_stage (candidate_id, stage)
        VALUES (%s, %s)
        ON CONFLICT (candidate_id) DO UPDATE
           SET stage = EXCLUDED.stage,
               moved_at = timezone('utc'::text, now())
        """,
        (candidate_id, stage),
    )


def _load_candidate(conn, candidate_id: str):
    """ขั้นปัจจุบัน + จ้างแล้วหรือยัง · 404 ถ้าไม่พบ · 409 ถ้ารับเข้าเป็นพนักงานไปแล้ว."""
    row = conn.execute(
        """
        SELECT c.id, hs.stage, emp.id AS employee_id
          FROM candidates c
          LEFT JOIN hiring_stage hs ON hs.candidate_id = c.id
          LEFT JOIN employees emp   ON emp.candidate_id = c.id
         WHERE c.id = %s
        """,
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")
    if row["employee_id"] is not None:
        raise HTTPException(
            status_code=409,
            detail="ผู้สมัครรายนี้ถูกรับเข้าเป็นพนักงานแล้ว — แก้ไขได้ที่ระเบียนพนักงาน",
        )
    return row


@router.put("/candidates/{candidate_id}/offer", response_model=JobOffer)
def upsert_offer(candidate_id: str, payload: JobOfferUpsert) -> JobOffer:
    """บันทึก (หรือแก้) ข้อเสนอ แล้วย้ายขั้นเป็น "ยื่นข้อเสนอ" ในทรานแซกชันเดียวกัน.

    แก้ข้อเสนอหลังผู้สมัครตอบไปแล้ว (เช่นต่อรองใหม่) = ข้อเสนอฉบับใหม่ คำตอบเดิมจึงถูก
    ล้างกลับเป็น pending · offered_at คงเวลาที่ยื่นครั้งแรกไว้ updated_at บอกว่าแก้ล่าสุดเมื่อไหร่
    """
    with get_conn() as conn:
        row = _load_candidate(conn, candidate_id)
        saved = conn.execute(
            f"""
            INSERT INTO job_offers
                   (candidate_id, position, salary, start_date, respond_by, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (candidate_id) DO UPDATE
               SET position = EXCLUDED.position,
                   salary = EXCLUDED.salary,
                   start_date = EXCLUDED.start_date,
                   respond_by = EXCLUDED.respond_by,
                   note = EXCLUDED.note,
                   response = 'pending',
                   decline_reason = NULL,
                   responded_at = NULL,
                   updated_at = timezone('utc'::text, now())
            RETURNING {_OFFER_COLUMNS}
            """,
            (
                candidate_id,
                payload.position.strip(),
                payload.salary,
                payload.start_date,
                payload.respond_by,
                payload.note,
            ),
        ).fetchone()
        next_stage = _next_stage_after_offer(row["stage"])
        if next_stage is not None:
            _move_stage(conn, candidate_id, next_stage)
        conn.commit()

    log.info(
        "บันทึกข้อเสนอของผู้สมัคร %s (ขั้น: %s)",
        candidate_id,
        next_stage or f"คงเดิมที่ {row['stage']}",
    )
    return JobOffer(**saved)


@router.post("/candidates/{candidate_id}/offer/response", response_model=JobOffer)
def record_offer_response(candidate_id: str, payload: JobOfferResponseIn) -> JobOffer:
    """บันทึกคำตอบของผู้สมัคร — ปฏิเสธแล้วปิดกระบวนการให้ · ตอบรับไม่จ้างให้เอง.

    ต้องมีข้อเสนอที่บันทึกไว้ก่อน (404) — การ์ดที่ถูกลากไปขั้นยื่นข้อเสนอโดยไม่มีรายละเอียด
    ใช้ปุ่มรับเข้า/ย้ายไป "ไม่ไปต่อ" ที่มีอยู่แล้วแทน ไม่ต้องผ่านที่นี่
    """
    with get_conn() as conn:
        row = _load_candidate(conn, candidate_id)
        saved = conn.execute(
            f"""
            UPDATE job_offers
               SET response = %s,
                   decline_reason = %s,
                   responded_at = timezone('utc'::text, now()),
                   updated_at = timezone('utc'::text, now())
             WHERE candidate_id = %s
            RETURNING {_OFFER_COLUMNS}
            """,
            (
                payload.response,
                # เหตุผลมีความหมายเฉพาะตอนปฏิเสธ — ตอบรับแล้วล้างทิ้ง ไม่เหลือค่าค้างจากรอบก่อน
                (payload.decline_reason or "").strip() or None
                if payload.response == "declined"
                else None,
                candidate_id,
            ),
        ).fetchone()
        if saved is None:
            raise HTTPException(
                status_code=404, detail="ยังไม่ได้บันทึกข้อเสนอของผู้สมัครรายนี้"
            )
        next_stage = _stage_after_response(payload.response, row["stage"])
        if next_stage is not None:
            _move_stage(conn, candidate_id, next_stage)
        conn.commit()

    log.info(
        "บันทึกคำตอบข้อเสนอของผู้สมัคร %s = %s (ขั้น: %s)",
        candidate_id,
        payload.response,
        next_stage or f"คงเดิมที่ {row['stage']}",
    )
    return JobOffer(**saved)
