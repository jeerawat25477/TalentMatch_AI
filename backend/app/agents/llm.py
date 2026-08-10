"""ตัวช่วยสร้าง LLM (Gemini) + เรียกแบบ structured output พร้อม retry/backoff.

เจตนาตามบรีฟคือ Flash เป็นดีฟอลต์ และ Pro สำหรับขั้น matching/bias ที่เน้นคุณภาพ
แต่มีข้อจำกัดจริงสองข้อ:
  1. Gemini 1.5 (ตามบรีฟ) ถูกปลดระวางแล้ว — API คืน 404 NOT_FOUND
  2. Gemini Pro ใช้ไม่ได้บน free tier — API คืน 429 พร้อม "limit: 0"
จึงตั้งดีฟอลต์เป็น flash ทั้งสองชั้น และเปิดให้ override ผ่าน env
เมื่ออัปเกรดเป็นแพลนมีค่าใช้จ่ายแล้ว ตั้ง GEMINI_COMPLEX_MODEL=gemini-2.5-pro ได้ทันที.

การเรียก LLM ทุกจุดควรผ่าน structured_invoke() เพื่อได้ exponential backoff อัตโนมัติ
เมื่อชน rate limit ชั่วคราว (429/503) — สำคัญเพราะระบบ batch อาจยิงถี่จนชนเพดาน RPM
หมายเหตุ: backoff แก้ได้แค่ลิมิต "ต่อนาที" (RPM) — ลิมิต "ต่อวัน" (RPD, free tier = 20/วัน)
retry ไปก็ไม่หาย ต้องสลับโมเดลหรืออัปเกรดแพลน.
"""
import logging
import os
from typing import Type, TypeVar

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
COMPLEX_MODEL = os.getenv("GEMINI_COMPLEX_MODEL", "gemini-2.5-flash")

# จำนวนครั้งสูงสุดและเพดานเวลาหน่วง (วินาที) — ปรับผ่าน env ได้
MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "5"))
MAX_BACKOFF = int(os.getenv("LLM_MAX_BACKOFF", "60"))

# คีย์เวิร์ดของ error ที่ "ลองใหม่แล้วมีโอกาสหาย" (ชั่วคราว) — ไม่ retry 404/400/permission
_RETRYABLE_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "503",
    "unavailable",
    "500",
    "internal",
    "deadline",
    "timeout",
)

TModel = TypeVar("TModel", bound=BaseModel)


def get_llm(complex: bool = False) -> ChatGoogleGenerativeAI:
    """คืน chat model. complex=True → ชั้นวิเคราะห์เชิงลึก (matching/bias)."""
    return ChatGoogleGenerativeAI(
        model=COMPLEX_MODEL if complex else DEFAULT_MODEL,
        temperature=0,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


def _is_retryable(exc: BaseException) -> bool:
    """retry เฉพาะ error ชั่วคราว (429/503/timeout) — ไม่ retry 404/auth ที่ยิงซ้ำก็ไม่หาย."""
    return any(marker in str(exc).lower() for marker in _RETRYABLE_MARKERS)


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=MAX_BACKOFF),
    retry=retry_if_exception(_is_retryable),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def structured_invoke(prompt: str, schema: Type[TModel], complex: bool = False) -> TModel:
    """เรียก LLM ให้คืน schema (Pydantic) พร้อม exponential backoff เมื่อชน rate limit."""
    return get_llm(complex).with_structured_output(schema).invoke(prompt)
