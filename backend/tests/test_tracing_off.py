"""เทสต์ต้องไม่ส่ง trace เข้า LangSmith จริง — ดูเหตุผลที่ tests/conftest.py."""
from langsmith import utils


def test_langsmith_tracing_is_off_during_pytest():
    assert not utils.tracing_is_enabled(), (
        "pytest กำลังส่ง trace เข้า LangSmith จริง — tests/conftest.py ถูกลบหรือไม่ได้ปิด tracing"
    )
