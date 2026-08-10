"""สถานะ LangSmith tracing — ใช้ log ตอนบูตว่าเปิดจริงไหม.

LangChain/LangGraph มี tracing ในตัว: ถ้า LANGCHAIN_TRACING_V2 truthy และมี LANGCHAIN_API_KEY
ทุก call ของ LLM/embeddings/กราฟจะส่ง trace ขึ้น LangSmith เอง ไม่ต้องเขียนโค้ดสลับ
(SDK รองรับทั้งชื่อ LANGCHAIN_* และ LANGSMITH_* — LANGSMITH_* จะชนะถ้าตั้งทั้งคู่)
ไฟล์นี้แค่ "รายงานสถานะ" ไม่ได้เปิด/ปิดเอง
"""
import os


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def tracing_status() -> tuple[bool, str]:
    """คืน (เปิดอยู่ไหม, ชื่อ project). เปิด = tracing flag ติด และมี API key."""
    enabled = (
        _truthy(os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2"))
        and bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
    )
    project = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "default"
    return enabled, project
