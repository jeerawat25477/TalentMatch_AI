"""เราเตอร์ค่าตั้งค่าระบบ — ตอนนี้มีแค่สวิตช์ปากทางรับอีเมล.

สวิตช์อยู่ใน DB ไม่ใช่ env เพราะ HR ต้องเปิด/ปิดเองได้จากหน้าเว็บโดยไม่ต้องรีสตาร์ต
(worker อ่านค่าทุกรอบ tick ผ่าน app/settings.py ที่แคชสั้น ๆ ให้)

⚠️ **ไม่รับและไม่คืนความลับของ IMAP ผ่าน API เด็ดขาด** — host/password อ่านจาก env
อย่างเดียว ที่นี่คืนแค่ `imap_configured: bool` ให้ HR รู้ว่ากดเปิดแล้วจะทำงานได้จริงไหม
(ดู CLAUDE.md หัวข้อ Secrets)

ข้อยกเว้นเดียวคือ `apply_address_template` ซึ่งได้มาจาก `IMAP_USER` — **ที่อยู่นั้นไม่ใช่
ความลับ** มันคือสิ่งที่จะถูกประกาศให้ผู้สมัครส่งเมลเข้ามา และต้องมาจากแหล่งเดียวกับที่
worker ดึงจริง ไม่งั้นหน้าเว็บจะโชว์กล่องหนึ่งแต่ระบบดึงอีกกล่อง แล้วใบสมัครหายเงียบ
"""
import logging

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.database import get_conn
from app.email_intake import (
    DEFAULT_SETTING,
    SETTING_KEY,
    apply_address_template,
    imap_configured,
)
from app.schemas import (
    EmailIntakeActivityItem,
    EmailIntakeSettingIn,
    EmailIntakeSettingOut,
)
from app.settings import get_setting, patch_setting

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT เหมือนทุก router อื่น — ทุก path ต้องล็อกอินก่อน
router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


def _counts_today() -> tuple[int, int]:
    """นับผลการรับอีเมล "ของวันนี้" จาก email_intake_log.

    นับจากตารางไม่ใช่ตัวแปรในหน่วยความจำ เพราะ backend รีโหลดบ่อยมากใน dev
    ตัวนับในโปรเซสจะรีเซ็ตจนตัวเลขที่ HR เห็นไม่มีความหมาย

    ตัด "วันนี้" ตาม UTC ให้ตรงกับ created_at ที่เก็บเป็น UTC ทั้งระบบ (คนละเรื่องกับ
    รอบโควตาของ Google ใน llm_quota.py ที่ต้องตัดตาม Pacific)
    """
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT outcome, count(*) AS n
                     FROM email_intake_log
                    WHERE created_at >= date_trunc('day', timezone('utc'::text, now()))
                    GROUP BY outcome"""
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 — ตัวเลขสถานะพังไม่ควรทำให้หน้าตั้งค่าเปิดไม่ได้
        log.warning("นับผลการรับอีเมลวันนี้ไม่สำเร็จ: %s", exc)
        return 0, 0

    by_outcome = {r["outcome"]: r["n"] for r in rows}
    matched = by_outcome.get("matched", 0)
    # ทุกอย่างที่ไม่ได้เข้าระบบนับเป็น "ไม่ได้รับเข้า" รวมกัน — HR สนใจว่ามีกี่ฉบับที่
    # ต้องไปดูเอง ไม่ได้สนใจแยกประเภทตรงตัวเลขสรุปนี้ (รายละเอียดอยู่ในตาราง log)
    unmatched = sum(n for outcome, n in by_outcome.items() if outcome != "matched")
    return matched, unmatched


def _status() -> EmailIntakeSettingOut:
    setting = get_setting(SETTING_KEY, DEFAULT_SETTING)
    matched, unmatched = _counts_today()
    return EmailIntakeSettingOut(
        enabled=bool(setting.get("enabled")),
        imap_configured=imap_configured(),
        last_poll_at=setting.get("last_poll_at"),
        last_error=setting.get("last_error"),
        matched_count_today=matched,
        unmatched_count_today=unmatched,
        apply_address_template=apply_address_template(),
    )


@router.get("/email-intake", response_model=EmailIntakeSettingOut)
def get_email_intake() -> EmailIntakeSettingOut:
    """สถานะปากทางรับอีเมล (เปิดอยู่ไหม ตั้งค่าครบไหม ดึงล่าสุดเมื่อไร ผิดพลาดอะไร)."""
    return _status()


@router.get("/email-intake/activity", response_model=list[EmailIntakeActivityItem])
def get_email_intake_activity(
    limit: int = Query(30, ge=1, le=100),
) -> list[EmailIntakeActivityItem]:
    """อีเมลที่ worker จัดการล่าสุด ใหม่สุดก่อน — ป้อนฟีดในหน้ารับสมัครและการแจ้งเตือน.

    สถานะ "อ่านแล้ว" ไม่ได้เก็บที่นี่ หน้าเว็บจำเวลาที่เปิดดูล่าสุดไว้เอง (ตอนนี้มีผู้ใช้
    HR คนเดียว ถ้าวันหนึ่งมีหลายคนค่อยย้ายมาเก็บต่อผู้ใช้)

    LEFT JOIN ทั้งสองตาราง เพราะ log ไม่มี FK — ผู้สมัครหรือตำแหน่งอาจถูกลบไปแล้ว
    แถวนั้นยังต้องโผล่ในฟีดได้ แค่ไม่มีชื่อให้กด
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT l.id, l.outcome, l.from_addr, l.subject, l.detail, l.created_at,
                      j.id AS job_id, j.title AS job_title,
                      c.id AS candidate_id, c.full_name AS candidate_name
                 FROM email_intake_log l
                 LEFT JOIN jobs j       ON j.id = l.job_id
                 LEFT JOIN candidates c ON c.id = l.candidate_id
                ORDER BY l.created_at DESC
                LIMIT %s""",
            (limit,),
        ).fetchall()
    return [EmailIntakeActivityItem(**r) for r in rows]


@router.patch("/email-intake", response_model=EmailIntakeSettingOut)
def set_email_intake(payload: EmailIntakeSettingIn) -> EmailIntakeSettingOut:
    """เปิด/ปิดปากทางรับอีเมล — มีผลภายในไม่กี่วินาที ไม่ต้องรีสตาร์ต.

    เปลี่ยนเฉพาะฟิลด์ enabled ด้วย patch ไม่ใช่เขียนทับทั้งก้อน ไม่งั้น last_uid_seen
    จะหายแล้วรอบถัดไปจะดูดเมลทั้งกล่องซ้ำ
    """
    patch_setting(SETTING_KEY, {"enabled": payload.enabled}, DEFAULT_SETTING)
    log.info("HR %s ปากทางรับอีเมล", "เปิด" if payload.enabled else "ปิด")
    return _status()
