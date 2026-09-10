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
from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

# โควตา chat call ต่อวันต่อโมเดล — free tier ของ Gemini = 20
GEMINI_DAILY_CHAT_QUOTA = int(os.getenv("GEMINI_DAILY_CHAT_QUOTA", "20"))

# เขตเวลาที่ใช้ตัดรอบโควตา — Google รีเซ็ต RPD ตอนเที่ยงคืน Pacific
#
# ⚠️ **นี่เป็นสมมติฐาน ไม่ใช่สิ่งที่เราวัดเอง** เป็นพฤติกรรมที่ Google ระบุไว้ แต่โปรเจกต์นี้
# ยังไม่เคยเฝ้าดูจังหวะที่ 429 หายไปจริง ๆ ถ้าสังเกตแล้วพบว่ามันรีเซ็ตตาม UTC ให้ตั้ง
# GEMINI_QUOTA_TZ=UTC แล้วพฤติกรรมจะกลับไปเหมือนก่อน โดยไม่ต้องแก้โค้ด
_QUOTA_TZ_NAME = os.getenv("GEMINI_QUOTA_TZ", "America/Los_Angeles")

# ใช้เมื่ออ่านฐานข้อมูลเขตเวลาไม่ได้ — เลือก 8 (PST) ไม่ใช่ 7 (PDT) โดยตั้งใจ:
# วัดแล้ว (สแกนปี 2026-2027 ทีละ 5 นาที) สูตรลบ 8 ไม่เคยให้วันที่ "เร็วกว่า" Pacific จริง
# เลยสักครั้ง มีแต่ช้ากว่าหรือตรง = พลาดไปทาง "หวงโควตา" (พักงานเกินจำเป็น รอบหน้าก็รัน)
# ไม่มีทางพลาดไปทาง "คิดว่ายังเหลือ" ซึ่งจะพาไปเจอ 429 กลางทาง · ถ้าแก้เป็น 7 คุณสมบัตินี้หาย
_FALLBACK_OFFSET = timedelta(hours=8)


@lru_cache(maxsize=1)
def _quota_tz() -> Optional[tzinfo]:
    """เขตเวลาของรอบโควตา (None = อ่านฐานข้อมูลเขตเวลาไม่ได้ ให้ใช้ทางถอย).

    แคชไว้เพื่อให้ log เตือนแค่ครั้งเดียว ไม่ใช่เพื่อความเร็ว — ZoneInfo แคชอ็อบเจกต์
    ให้ในตัวอยู่แล้ว (วัดได้ 100,000 ครั้ง = 0.011 วินาที)

    ต้องดัก Exception กว้าง ๆ: ชื่อโซนที่ไม่มีจริงโยน ZoneInfoNotFoundError ก็จริง
    แต่ชื่อที่ผิดรูป (ว่างเปล่า หรือมี ../) โยน **ValueError** ซึ่งไม่ใช่คลาสเดียวกัน
    ดักแคบไปแล้วค่า env ที่พิมพ์ผิดจะทำให้ทั้งแอปล่มแทนที่จะถอยไปใช้ทางสำรอง
    """
    try:
        return ZoneInfo(_QUOTA_TZ_NAME)
    except Exception as exc:  # noqa: BLE001 — ดูเหตุผลใน docstring
        log.warning(
            "อ่านเขตเวลา %r ไม่ได้ (%s) — ใช้ทางถอย ลบ %s ชม.คงที่แทน "
            "ตัวนับจะยังทำงาน แต่ช่วงคาบเกี่ยวอาจพักงานเกินจำเป็นราวชั่วโมงหนึ่ง",
            _QUOTA_TZ_NAME, exc, int(_FALLBACK_OFFSET.total_seconds() // 3600),
        )
        return None


def quota_date(now: datetime, tz: Optional[tzinfo]) -> date:
    """แปลงเวลา UTC เป็น "วันที่ตามรอบโควตาของ Google" — ฟังก์ชันบริสุทธิ์.

    รับ now กับ tz เข้ามาเป็นพารามิเตอร์เพื่อให้ทดสอบทุกเคส (ข้ามวัน, วันเปลี่ยน DST,
    ทางถอย) ได้โดยไม่ต้อง mock เวลาหรือ env — แพตเทิร์นเดียวกับ rate_limit.hit_and_check

    การแปลงจาก UTC ไปเป็นเวลาท้องถิ่นมีคำตอบเดียวเสมอ แม้แต่วันถอยเวลาที่มี 25 ชั่วโมง
    (ความกำกวมของ DST เกิดตอนแปลง *ย้อนทาง* คือมีเวลาท้องถิ่นแล้วหาว่าเป็น UTC ไหน)
    """
    if tz is not None:
        return now.astimezone(tz).date()
    return (now - _FALLBACK_OFFSET).date()


def today() -> date:
    """วันที่ที่ใช้ตัดรอบโควตา — **ตามรอบจริงของ Google ไม่ใช่ UTC**.

    เดิมใช้ UTC ด้วยเหตุผลที่ผิด (คิดว่าอิมเมจไม่มีฐานข้อมูลเขตเวลา ต้องลง tzdata เพิ่ม
    ทั้งที่ python:3.12-slim มี /usr/share/zoneinfo ติดมาอยู่แล้ว) ความคลาดที่ตามมาคือ
    ตอบวันที่ผิดถึง 30.6% ของเวลาทั้งปี และช่องว่างนั้นคร่อมเวลาทำงานช่วงเช้าของ HR พอดี:
    call ที่ใช้ตอนเช้าถูกคิดเข้าโควตาจริงของ "เมื่อวาน" ฝั่ง Google แต่โผล่ในยอด "วันนี้"
    ของเรา ทำให้ช่วงบ่าย (ที่โควตาจริงรีเซ็ตไปแล้ว) ถูกพักงานทิ้งไว้ทั้งที่ยิงได้

    นี่เป็นแหล่งความจริงเดียวของจุดตัดวัน — record_call กับ used_today เรียกตัวนี้ทั้งคู่
    """
    return quota_date(datetime.now(timezone.utc), _quota_tz())


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
