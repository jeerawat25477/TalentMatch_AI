"""เราเตอร์ค่าตั้งค่าระบบ — ตอนนี้มีแค่สวิตช์ปากทางรับอีเมล.

สวิตช์อยู่ใน DB ไม่ใช่ env เพราะ HR ต้องเปิด/ปิดเองได้จากหน้าเว็บโดยไม่ต้องรีสตาร์ต
(worker อ่านค่าทุกรอบ tick ผ่าน app/settings.py ที่แคชสั้น ๆ ให้)

⚠️ **ไม่รับและไม่คืนความลับของ IMAP ผ่าน API เด็ดขาด** — host/user/password อ่านจาก env
อย่างเดียว ที่นี่คืนแค่ `imap_configured: bool` ให้ HR รู้ว่ากดเปิดแล้วจะทำงานได้จริงไหม
(ดู CLAUDE.md หัวข้อ Secrets)
"""
import logging

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.database import get_conn
from app.email_intake import DEFAULT_SETTING, SETTING_KEY, imap_configured
from app.schemas import EmailIntakeSettingIn, EmailIntakeSettingOut
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
    )


@router.get("/email-intake", response_model=EmailIntakeSettingOut)
def get_email_intake() -> EmailIntakeSettingOut:
    """สถานะปากทางรับอีเมล (เปิดอยู่ไหม ตั้งค่าครบไหม ดึงล่าสุดเมื่อไร ผิดพลาดอะไร)."""
    return _status()


@router.patch("/email-intake", response_model=EmailIntakeSettingOut)
def set_email_intake(payload: EmailIntakeSettingIn) -> EmailIntakeSettingOut:
    """เปิด/ปิดปากทางรับอีเมล — มีผลภายในไม่กี่วินาที ไม่ต้องรีสตาร์ต.

    เปลี่ยนเฉพาะฟิลด์ enabled ด้วย patch ไม่ใช่เขียนทับทั้งก้อน ไม่งั้น last_uid_seen
    จะหายแล้วรอบถัดไปจะดูดเมลทั้งกล่องซ้ำ
    """
    patch_setting(SETTING_KEY, {"enabled": payload.enabled}, DEFAULT_SETTING)
    log.info("HR %s ปากทางรับอีเมล", "เปิด" if payload.enabled else "ปิด")
    return _status()
