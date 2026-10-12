"""ตั้งค่าที่ใช้กับเทสต์ทุกไฟล์ — pytest โหลดไฟล์นี้ก่อน import โมดูลเทสต์ใด ๆ.

**ปิด LangSmith tracing ระหว่างรันเทสต์** — container มี LANGCHAIN_TRACING_V2=true จาก .env
เทสต์ที่เดินกราฟ (AI ปลอม) จึงเคยส่ง trace เข้า project talentmatch-ai จริง: เช็ก 2026-10-12
~240 จาก 308 trace ใน 7 วันเป็นของ pytest และ error 50 รายการ (16%) ทั้งหมดคือ 429 ที่เทสต์จำลองเอง
ส่วน trace ที่เรียก Gemini จริง 62 รายการ error 0 — หน้าสรุปจึงดูแย่เกินจริงและ P50 latency เป็น 0.00s

ระบบจริงและสคริปต์วัดผล (scripts/eval_*.py รันด้วย python ตรง ไม่ผ่าน pytest) ยังส่ง trace ตามปกติ
tests/test_tracing_off.py ล็อกไว้ว่าปิดอยู่จริง
"""
import os

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

# SDK จำค่า env ไว้ (lru_cache) — ถ้ามีอะไรอ่านไปก่อนหน้านี้ ค่าเก่า "true" จะค้าง
try:
    from langsmith import utils as _ls_utils

    _ls_utils.get_env_var.cache_clear()
except Exception:  # noqa: BLE001 — ไม่มี langsmith ก็ไม่มีอะไรให้ปิด
    pass
