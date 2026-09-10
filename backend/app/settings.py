"""ค่าตั้งค่าระดับระบบที่เก็บใน DB (ตาราง app_settings) พร้อมแคชสั้น ๆ.

ต่างจาก env: env ต้องรีสตาร์ตถึงจะมีผล ส่วนค่าที่นี่ HR กดเปลี่ยนจากหน้าเว็บได้สด ๆ
ใช้กับสิ่งที่ "ผู้ใช้ควบคุม" เท่านั้น — **ความลับ (คีย์/รหัสผ่าน) ยังต้องอยู่ใน env**
ไม่เอามาเก็บที่นี่เพราะจะวิ่งผ่าน API ได้ (ดู CLAUDE.md หัวข้อ Secrets)

ทำไมต้องแคช: worker อ่านค่านี้ทุกรอบ tick ถ้ายิง SELECT ทุกครั้งจะกวน DB โดยเปล่าประโยชน์
ทำไมแคชต้องสั้น: ผู้ใช้ต้องการให้สวิตช์เปิด/ปิดมีผลเกือบทันทีโดยไม่ต้องรีสตาร์ต
TTL 10 วินาทีจึงเป็นจุดสมดุล และ set_setting ล้างแคชให้ทันทีอยู่แล้ว

แคชเป็น state ในโปรเซส เหมือน runner._active และ rate limiter ของล็อกอิน — ใช้ได้กับ
backend เรพลิกาเดียว ถ้าจะสเกลต้องย้ายทั้งชุดพร้อมกัน (ไม่ใช่ข้อจำกัดใหม่ของไฟล์นี้)
"""
import logging
import threading
import time
from typing import Any, Optional

from psycopg.types.json import Json

from app.database import get_conn

log = logging.getLogger(__name__)

SETTINGS_CACHE_TTL = 10.0  # วินาที

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def invalidate(key: Optional[str] = None) -> None:
    """ล้างแคช (ทั้งหมด หรือเฉพาะ key) — เทสเรียกเพื่อไม่ให้ค่ารั่วข้ามเคส."""
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def get_setting(key: str, default: Optional[dict] = None) -> dict:
    """อ่านค่าตั้งค่า (ผ่านแคช) — คืน default ถ้าไม่มีแถวหรืออ่าน DB ไม่ได้.

    อ่านไม่ได้แล้วคืน default โดยไม่โยน exception โดยตั้งใจ: ผู้เรียกหลักคือ worker
    ที่วนลูปอยู่ ถ้า DB สะดุดชั่วครู่แล้ว worker ตายจะแย่กว่าการกลับไปใช้ค่าดีฟอลต์
    (ซึ่งของ email_intake คือ "ปิด" = ฝั่งที่ปลอดภัย)
    """
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < SETTINGS_CACHE_TTL:
            return hit[1]

    value = default or {}
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", (key,)
            ).fetchone()
        if row is not None:
            value = row["value"]
    except Exception as exc:  # noqa: BLE001 — ดูเหตุผลใน docstring
        log.warning("อ่านค่าตั้งค่า %s ไม่สำเร็จ ใช้ค่าดีฟอลต์แทน: %s", key, exc)
        return value

    with _lock:
        _cache[key] = (now, value)
    return value


def set_setting(key: str, value: dict) -> dict:
    """เขียนค่าตั้งค่า (UPSERT) แล้ว **ล้างแคชทันที**.

    การล้างแคชตรงนี้ไม่ใช่การปรับให้เร็วขึ้นเฉย ๆ แต่จำเป็นเพื่อความถูกต้องที่ผู้ใช้เห็น:
    ถ้าไม่ล้าง HR กดสวิตช์แล้วหน้าเว็บ GET ตามมาทันทีจะยังเห็นค่าเก่าไปอีกถึง 10 วินาที
    แล้วเข้าใจว่าปุ่มเสีย
    """
    with get_conn() as conn:
        row = conn.execute(
            """INSERT INTO app_settings (key, value)
               VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE
                  SET value = EXCLUDED.value,
                      updated_at = timezone('utc'::text, now())
               RETURNING value""",
            (key, Json(value)),
        ).fetchone()
        conn.commit()
    invalidate(key)
    return row["value"]


def patch_setting(key: str, changes: dict, default: Optional[dict] = None) -> dict:
    """อัปเดตเฉพาะบางฟิลด์ของค่าตั้งค่า (อ่าน-รวม-เขียน).

    ⚠️ ไม่ใช่การอัปเดตแบบอะตอมมิก — ถ้ามีสองคนเขียนพร้อมกัน คนหลังชนะทั้งก้อน
    ยอมรับได้เพราะผู้เขียนมีแค่ intake worker ตัวเดียวกับ HR ที่กดปุ่มนาน ๆ ที
    ถ้าวันหนึ่งมีผู้เขียนหลายทางพร้อมกันจริง ให้เปลี่ยนไปใช้ jsonb `||` ใน SQL แทน
    """
    current = dict(get_setting(key, default) or {})
    current.update(changes)
    return set_setting(key, current)
