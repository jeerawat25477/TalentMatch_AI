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


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _role_defaults_to_admin():
    """เทสต์เดิมแทน get_current_user ด้วยชื่อสมมติที่ไม่มีแถวใน users — ถ้าปล่อยให้ get_current_role
    อ่าน DB จริง endpoint ที่มี require_admin จะตอบ 401 ทั้งหมด จึงตั้ง role เป็น admin ไว้ก่อนทุกเทสต์
    (เทสต์ที่ .clear() ตอนจบ ก็แค่ลบทิ้ง เทสต์ถัดไปตั้งใหม่) · tests/test_roles.py แทนเป็น demo เอง"""
    from app.auth import get_current_role
    from app.main import app

    app.dependency_overrides[get_current_role] = lambda: "admin"
    yield
    app.dependency_overrides.pop(get_current_role, None)
