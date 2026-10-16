"""เราเตอร์ Human-in-the-Loop: HR อนุมัติ/ปฏิเสธ + ส่งอีเมลถึงผู้สมัคร."""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Json

from app.agents.bias_rules import find_biased_message_phrases
from app.agents.runner import active_candidates, reserve_candidates
from app.auth import get_current_user, require_admin
from app.database import get_conn
from app.job_queue import enqueue, enqueue_many
from app.email_sender import EmailConfigError, send_email
from app.schemas import (
    BulkDecisionAccepted,
    BulkDecisionIn,
    BulkDecisionSkip,
    EmailDraftDeleteOut,
    EmailDraftIn,
    EmailDraftOut,
    EmailSendIn,
    EmailSendOut,
    HRDecisionIn,
    HRDecisionOut,
)

log = logging.getLogger(__name__)

# เพดานคนต่อหนึ่งคำขอ — ผูกกับโควตา LLM ไม่ใช่ประสิทธิภาพ: อนุมัติ 1 คน = ~2 call
# (planner + drafter) โควตาฟรีมี 20 call/วัน 10 คนจึงใช้หมดวันพอดี
MAX_BULK_DECISION = int(os.getenv("MAX_BULK_DECISION", "10"))


def _bulk_partition(
    requested: list[str], existing: set[str], active: frozenset[str]
) -> tuple[list[str], list[dict]]:
    """แยกคำขอเป็น (รับเข้าคิว, ข้าม+เหตุผล) — ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมี DB.

    ต้องเป็น partial success เสมอ: ถ้าคนหนึ่งใน 10 มีปัญหาแล้วทำให้อีก 9 คนที่ควรสำเร็จ
    พลอยไม่ได้ทำไปด้วย จะแย่กว่าไม่มี bulk action เลย จึงไม่โยน exception ที่นี่
    """
    accepted: list[str] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    for cid in requested:
        cid = str(cid)
        if cid in seen:
            skipped.append({"id": cid, "reason": "ส่งชื่อซ้ำในคำขอเดียวกัน"})
            continue
        seen.add(cid)
        if cid not in existing:
            skipped.append({"id": cid, "reason": "ไม่พบผู้สมัคร"})
        elif cid in active:
            skipped.append({"id": cid, "reason": "กำลังประมวลผลอยู่"})
        else:
            accepted.append(cid)
    return accepted, skipped


router = APIRouter(
    prefix="/api/v1/candidates", tags=["hr"], dependencies=[Depends(get_current_user)]
)


@router.post("/bulk-decision", response_model=BulkDecisionAccepted, status_code=202)
def submit_bulk_decision(payload: BulkDecisionIn) -> BulkDecisionAccepted:
    """ตัดสินหลายคนด้วยผลเดียวกัน — บันทึกทันที แล้วเดินกราฟเบื้องหลัง.

    ⚠️ ต้องประกาศ *ก่อน* /{candidate_id}/decision ไม่งั้น FastAPI จะจับเส้นทางนี้เป็น
    candidate_id = "bulk-decision" (บทเรียนเดียวกับ /candidates/search)

    คืนผลการ "รับเข้าคิว" ไม่ใช่ผลการตัดสิน — ผลรายคนไปปรากฏผ่าน poll เดิมของหน้ารายชื่อ
    """
    requested = [str(c) for c in payload.candidate_ids]
    if len(requested) > MAX_BULK_DECISION:
        raise HTTPException(
            status_code=413,
            detail=f"ตัดสินได้ครั้งละไม่เกิน {MAX_BULK_DECISION} คน (ส่งมา {len(requested)})",
        )

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM candidates WHERE id = ANY(%s)", (requested,)
        ).fetchall()
        existing = {str(r["id"]) for r in rows}

        accepted, skipped = _bulk_partition(requested, existing, active_candidates())

        # บันทึกคำตัดสินทั้งชุดในทรานแซกชันเดียว (SQL เดียวกับ submit_decision)
        for cid in accepted:
            conn.execute(
                """
                INSERT INTO hr_decisions (candidate_id, decision, notes)
                VALUES (%s, %s, %s)
                ON CONFLICT (candidate_id)
                DO UPDATE SET decision = EXCLUDED.decision,
                              notes = EXCLUDED.notes,
                              updated_at = timezone('utc'::text, now())
                """,
                (cid, payload.decision, payload.notes),
            )
        conn.commit()

    # จองใน request thread ก่อนตอบ — กันดับเบิลคลิกยิงซ้ำ (แพตเทิร์นเดียวกับ reprocess)
    # แล้วเข้าคิวทีละคน: worker รันตามลำดับทีละชิ้น ไม่ใช่ขนานจนชนเพดาน RPM
    # และงานไม่หายถ้า container รีสตาร์ตกลางชุด (ต่างจาก background task เดิม)
    if accepted:
        reserve_candidates(accepted)
        enqueue_many([
            (cid, None, "resume_after_decision",
             {"decision": payload.decision, "notes": payload.notes})
            for cid in accepted
        ])

    return BulkDecisionAccepted(
        accepted=len(accepted),
        candidate_ids=accepted,
        skipped=[BulkDecisionSkip(**s) for s in skipped],
    )


@router.post("/{candidate_id}/decision", response_model=HRDecisionOut)
def submit_decision(candidate_id: str, payload: HRDecisionIn) -> HRDecisionOut:
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

    # resume กราฟจากจุด interrupt (ไม่ rerun จาก entry point) — เข้าคิวเพราะเรียก LLM
    # worker จะเรียก runner.decide_candidate ตัวเดิม ทั้งการจองทะเบียน _gate และ
    # การ resume/ย้อน state จึงเหมือนเดิมทุกอย่าง แค่ทนต่อการรีสตาร์ตขึ้น
    reserve_candidates([candidate_id])
    enqueue(
        candidate_id, None, "resume_after_decision",
        {"decision": payload.decision, "notes": payload.notes},
    )
    return HRDecisionOut(**row)


def _require_evaluation(conn, candidate_id: str) -> None:
    """ต้องมีแถว evaluations ก่อน — คอลัมน์อีเมลทั้งหมดอยู่บนตารางนั้น.

    ใช้ร่วมกันทั้งการส่งและการบันทึกร่าง ข้อความจึงตรงกันเสมอ
    """
    row = conn.execute(
        "SELECT candidate_id FROM evaluations WHERE candidate_id = %s", (candidate_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="ยังไม่มีผลประเมินของผู้สมัครนี้ ยังไม่มีร่างอีเมลให้แก้"
        )


def _draft_json(payload: EmailDraftIn) -> dict:
    """รูปที่เก็บลง email_draft_edited — ใส่ kind เฉพาะเมื่อส่งมา.

    ร่างที่บันทึกก่อนมีฟิลด์นี้ไม่มีคีย์ kind เลย ถ้าคราวนี้เก็บ "kind": null ไว้ด้วย
    ข้อมูลในคอลัมน์เดียวกันจะมีสองรูปที่หมายถึงสิ่งเดียวกัน (ไม่รู้ชนิด)
    """
    draft = {"subject": payload.subject, "body": payload.body}
    if payload.kind is not None:
        draft["kind"] = payload.kind
    return draft


@router.put("/{candidate_id}/email/draft", response_model=EmailDraftOut)
def save_email_draft(candidate_id: str, payload: EmailDraftIn) -> EmailDraftOut:
    """บันทึกร่างอีเมลที่ HR แก้เอง — ไม่ส่งอะไรทั้งสิ้น.

    เดิมข้อความที่ HR พิมพ์แก้อยู่ในหน้าจอเท่านั้น ออกจากหน้าแล้วกลับมาก็หายกลับไปเป็น
    ร่างของ AI · เก็บลง email_draft_edited ซึ่งเป็นคนละคอลัมน์กับ email_draft ของ
    email_drafter เพราะกราฟเดินรอบใหม่เขียนทับคอลัมน์นั้น และ runner ตั้งเป็น NULL ได้
    เมื่อ drafter ล้ม — ร่างของ HR ต้องรอดทั้งสองกรณี
    """
    with get_conn() as conn:
        _require_evaluation(conn, candidate_id)
        row = conn.execute(
            """UPDATE evaluations
                  SET email_draft_edited = %s,
                      email_draft_edited_at = timezone('utc'::text, now())
                WHERE candidate_id = %s
            RETURNING candidate_id, email_draft_edited_at""",
            (Json(_draft_json(payload)), candidate_id),
        ).fetchone()
        conn.commit()
    log.info("บันทึกร่างอีเมลที่ HR แก้ของผู้สมัคร %s", candidate_id)
    return EmailDraftOut(
        candidate_id=row["candidate_id"],
        subject=payload.subject,
        body=payload.body,
        kind=payload.kind,
        edited_at=row["email_draft_edited_at"],
    )


@router.delete("/{candidate_id}/email/draft", response_model=EmailDraftDeleteOut)
def clear_email_draft(candidate_id: str) -> EmailDraftDeleteOut:
    """ทิ้งร่างของ HR แล้วกลับไปใช้ร่างของ AI — ร่างของ AI ไม่เคยถูกแตะ จึงไม่ต้องกู้อะไร."""
    with get_conn() as conn:
        _require_evaluation(conn, candidate_id)
        conn.execute(
            """UPDATE evaluations
                  SET email_draft_edited = NULL, email_draft_edited_at = NULL
                WHERE candidate_id = %s""",
            (candidate_id,),
        )
        conn.commit()
    return EmailDraftDeleteOut(candidate_id=candidate_id)


@router.post("/{candidate_id}/email/send", response_model=EmailSendOut, dependencies=[Depends(require_admin)])
def send_candidate_email(
    candidate_id: str, payload: EmailSendIn, user: str = Depends(get_current_user)
) -> EmailSendOut:
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

    # ตรวจถ้อยคำที่อาจเป็นการเลือกปฏิบัติ **ในตัว endpoint ส่งเอง** ไม่แยก /check — หน้าเว็บลืม
    # เรียกก่อนส่งก็ข้ามไม่ได้ · ไม่ห้ามส่ง: HR เห็นแล้วยืนยันได้ (บางงานจำเป็นจริง) แต่ต้องรู้ตัวก่อน
    # และระบบจำไว้ว่าใครส่งทั้งที่ถูกเตือน · AI ร่างอีเมลโดยไม่เห็นข้อมูลส่วนตัว (test_prompt_privacy)
    # ความเสี่ยงจริงจึงเป็นข้อความที่ HR แก้เองหรือเทมเพลตของตัวเอง
    hits = find_biased_message_phrases(f"{payload.subject}\n{payload.body}")
    if hits and not payload.acknowledged_bias_warning:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "bias_warning",
                "message": "อีเมลนี้มีถ้อยคำที่อาจเป็นการเลือกปฏิบัติ — ตรวจก่อนส่ง",
                "phrases": [{"category": h.category, "phrase": h.phrase} for h in hits],
            },
        )
    if hits:
        log.warning(
            "%s ส่งอีเมลถึงผู้สมัคร %s ทั้งที่ระบบเตือนถ้อยคำ: %s",
            user, candidate_id, [h.phrase for h in hits],
        )

    try:
        send_email(to=payload.to, subject=payload.subject, body=payload.body)
    except EmailConfigError as exc:
        log.error("ตั้งค่าอีเมลไม่ครบ: %s", exc)
        raise HTTPException(status_code=503, detail="ระบบอีเมลยังไม่ถูกตั้งค่า") from exc
    except Exception as exc:  # noqa: BLE001 — SMTP/Gmail API ล้มได้หลายแบบ ไม่ leak stack ให้ client
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
