"""ตัวนับ chat call รายวัน — ให้คิวรู้ว่าโควตา Gemini วันนี้เหลือพอจะรันงานถัดไปไหม.

ทำไมต้องมี: free tier ให้ 20 call/วัน **ต่อโมเดล** (RPD) ส่วน retry/backoff ใน
agents/llm.py แก้ได้แค่ลิมิตต่อนาที (RPM) — ยิงซ้ำตอนโควตารายวันหมดก็ได้ 429 เหมือนเดิม
ทางเดียวที่จะไม่ให้ batch ใหญ่ตายเงียบคือ "รู้ก่อนยิง" ว่าวันนี้เหลือเท่าไร

⚠️ เป็นตัวนับ **ไม่ใช่ด่านบังคับใน call path** — record_call ต้องไม่ทำให้ LLM call ล้ม
ไม่ว่า DB จะเป็นอะไร (เขียนไม่ได้ก็แค่ log warning แล้วปล่อยผ่าน) ด่านจริงอยู่ที่ worker
ซึ่งเช็คก่อนหยิบงานขึ้นมารัน

ขอบเขตที่ตัวเลขนี้บอกไม่ได้: มันนับเฉพาะ call ที่ออกจากแอปตัวนี้ ถ้ามีสคริปต์หรือ
เครื่องอื่นใช้คีย์เดียวกัน ค่าที่ได้จะต่ำกว่าความจริง — จึงยังต้องดัก 429 จริงที่ worker
เป็นตาข่ายชั้นสอง (ดู job_queue.classify_failure)
"""
import logging
import os
from datetime import date, datetime, timezone

log = logging.getLogger(__name__)

# โควตา chat call ต่อวันต่อโมเดล — free tier ของ Gemini = 20
GEMINI_DAILY_CHAT_QUOTA = int(os.getenv("GEMINI_DAILY_CHAT_QUOTA", "20"))


def today() -> date:
    """วันที่ที่ใช้ตัดรอบโควตา — UTC.

    Google รีเซ็ต RPD ตอนเที่ยงคืน Pacific ซึ่งไม่ตรงกับ UTC (คลาดได้ ~8 ชม.)
    เลือก UTC เพราะทั้งระบบใช้ UTC อยู่แล้วและไม่ต้องพึ่ง tzdata ในอิมเมจ
    ผลของความคลาด: ช่วงคาบเกี่ยวอาจคิดว่าโควตาหมดทั้งที่รีเซ็ตแล้ว (งานถูกพักไว้
    แล้วรอบถัดไปก็รันได้เอง) หรือคิดว่ายังเหลือทั้งที่หมด (เจอ 429 จริง แล้ว worker
    ตีเป็น deferred_quota) — ทั้งสองทางไม่มีทางทำให้งานหาย
    """
    return datetime.now(timezone.utc).date()


def has_room(used: int, cost: int, quota: int = GEMINI_DAILY_CHAT_QUOTA) -> bool:
    """โควตาที่เหลือพอสำหรับงานที่กิน `cost` call ไหม (ฟังก์ชันบริสุทธิ์ เทสได้ตรง ๆ).

    quota <= 0 = ปิดการคุมโควตา (ปล่อยผ่านทุกงาน) — ไว้ให้ปิดฟีเจอร์นี้ได้ด้วย env
    โดยไม่ต้องแก้โค้ด เช่นตอนอัปเกรดเป็นแพลนเสียเงินที่ RPD ไม่ใช่ปัญหาอีกต่อไป
    """
    if quota <= 0:
        return True
    return used + cost <= quota


def record_call(model: str) -> None:
    """+1 ให้ตัวนับของวันนี้ — best-effort เท่านั้น ห้ามโยน exception ออกไป.

    UPSERT แบบ `+ 1` ทำให้อะตอมมิกในตัวที่ฝั่ง DB จึงปลอดภัยกับหลายเธรด
    โดยไม่ต้องล็อกในโปรเซส (กราฟรันขนานได้ตาม GRAPH_MAX_CONCURRENCY)
    """
    try:
        from app.database import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO llm_quota_usage (usage_date, model, chat_calls_used)
                VALUES (%s, %s, 1)
                ON CONFLICT (usage_date, model)
                DO UPDATE SET chat_calls_used = llm_quota_usage.chat_calls_used + 1
                """,
                (today(), model),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 — นับพลาดดีกว่าทำให้ LLM call ล้ม
        log.warning("บันทึกตัวนับโควตาของ %s ไม่สำเร็จ: %s", model, exc)


def used_today(model: str) -> int:
    """จำนวน chat call ของโมเดลนี้ที่ใช้ไปแล้ววันนี้ (0 ถ้ายังไม่มีแถว/อ่านไม่ได้).

    อ่านไม่ได้แล้วคืน 0 = เลือกทาง "ปล่อยให้ลองรัน" มากกว่า "พักงานไว้" เพราะ
    ถ้าโควตาหมดจริง 429 จะพาไป deferred_quota อยู่ดี แต่ถ้าพักไว้เพราะ DB งอแง
    งานจะไม่เดินทั้งที่โควตาเหลือ
    """
    try:
        from app.database import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT chat_calls_used FROM llm_quota_usage WHERE usage_date = %s AND model = %s",
                (today(), model),
            ).fetchone()
        return int(row["chat_calls_used"]) if row else 0
    except Exception as exc:  # noqa: BLE001
        log.warning("อ่านตัวนับโควตาของ %s ไม่สำเร็จ: %s", model, exc)
        return 0
