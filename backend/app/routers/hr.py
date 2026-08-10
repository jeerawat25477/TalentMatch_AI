"""เราเตอร์ Human-in-the-Loop: HR อนุมัติ/ปฏิเสธ + ส่งอีเมลถึงผู้สมัคร."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.agents.runner import resume_after_decision
from app.auth import get_current_user
from app.database import get_conn
from app.email_sender import EmailConfigError, send_email
from app.schemas import (
    EmailSendIn,
    EmailSendOut,
    HRDecisionIn,
    HRDecisionOut,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/candidates", tags=["hr"], dependencies=[Depends(get_current_user)]
)


@router.post("/{candidate_id}/decision", response_model=HRDecisionOut)
def submit_decision(
    candidate_id: str, payload: HRDecisionIn, background_tasks: BackgroundTasks
) -> HRDecisionOut:
    """บันทึกผลตัดสินของ HR แล้ว resume กราฟจากจุด interrupt (ไม่ใช่รันใหม่).

    ขั้นตอน:
      1. upsert ลงตาราง hr_decisions (candidate_id เป็น UNIQUE — 1 คน 1 ผล)
      2. โหลด state ของกราฟด้วย thread_id เดิม, ป้อน hr_decision/hr_notes
      3. สั่งรันต่อจาก interrupt เพื่อเข้าสู่ planner/drafter
    """
    with get_conn() as conn:
        cand = conn.execute(
            "SELECT id FROM candidates WHERE id = %s", (candidate_id,)
        ).fetchone()
        if cand is None:
            raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")

        row = conn.execute(
            """
            INSERT INTO hr_decisions (candidate_id, decision, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (candidate_id)
            DO UPDATE SET decision = EXCLUDED.decision,
                          notes = EXCLUDED.notes,
                          updated_at = timezone('utc'::text, now())
            RETURNING candidate_id, decision, notes, updated_at
            """,
            (candidate_id, payload.decision, payload.notes),
        ).fetchone()
        conn.commit()

    # resume กราฟจากจุด interrupt (ไม่ rerun จาก entry point) — ทำเบื้องหลังเพราะเรียก LLM
    background_tasks.add_task(
        resume_after_decision, candidate_id, payload.decision, payload.notes
    )
    return HRDecisionOut(**row)


@router.post("/{candidate_id}/email/send", response_model=EmailSendOut)
def send_candidate_email(candidate_id: str, payload: EmailSendIn) -> EmailSendOut:
    """ส่งอีเมลถึงผู้สมัคร (HR กดเอง หลังตรวจผู้รับ/หัวข้อ/เนื้อความบนจอ).

    ส่งแบบ **synchronous** ต่างจากกราฟ — HR ต้องรู้ทันทีว่าสำเร็จหรือล้ม ไม่ใช่ยิงแล้วเงียบ

    ความปลอดภัย: ผู้รับ (`to`) มาจากค่าที่ HR ยืนยันบนจอ ไม่ใช่ดึงอีเมลที่ LLM แกะจาก DB
    มาส่งเองอัตโนมัติ — มนุษย์คือด่านกัน spam relay (ดู memory-bank/04_security.md)
    """
    with get_conn() as conn:
        row = conn.execute(
            """SELECT e.candidate_id FROM evaluations e WHERE e.candidate_id = %s""",
            (candidate_id,),
        ).fetchone()
    if row is None:
        # ต้องมี evaluation ก่อน (คอลัมน์ email_sent_* อยู่บนตารางนี้) — ยังไม่ประเมิน = ส่งไม่ได้
        raise HTTPException(status_code=404, detail="ยังไม่มีผลประเมินของผู้สมัครนี้ ส่งอีเมลไม่ได้")

    try:
        send_email(to=payload.to, subject=payload.subject, body=payload.body)
    except EmailConfigError as exc:
        log.error("ตั้งค่า SMTP ไม่ครบ: %s", exc)
        raise HTTPException(status_code=503, detail="ระบบอีเมลยังไม่ถูกตั้งค่า") from exc
    except Exception as exc:  # noqa: BLE001 — SMTP ล้มได้หลายแบบ ไม่ leak stack ให้ client
        log.exception("ส่งอีเมลถึง %s ล้มเหลว: %s", payload.to, exc)
        raise HTTPException(status_code=502, detail="ส่งอีเมลไม่สำเร็จ ลองใหม่อีกครั้ง") from exc

    with get_conn() as conn:
        sent = conn.execute(
            """UPDATE evaluations
               SET email_sent_at = timezone('utc'::text, now()), email_sent_to = %s,
                   email_send_count = COALESCE(email_send_count, 0) + 1
               WHERE candidate_id = %s
               RETURNING candidate_id, email_sent_to, email_sent_at, email_send_count""",
            (payload.to, candidate_id),
        ).fetchone()
        conn.commit()
    return EmailSendOut(**sent)
