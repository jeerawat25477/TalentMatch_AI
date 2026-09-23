"""CORS origin ที่อ่านจาก env — ตั้งผิดทีเดียวหน้าเว็บใช้ไม่ได้ทั้งใบ

โปรดักชันหน้าเว็บกับ API อยู่โดเมนเดียวกัน (Caddy แยกด้วย path) CORS จึงเป็นตาข่าย
กันพลาด ไม่ใช่ทางหลัก แต่ถ้าวันหนึ่งแยกโดเมน ค่านี้จะกลายเป็นตัวตัดสินทันที
"""
from app.main import DEFAULT_ORIGINS, allowed_origins


def test_ไม่ตั้งค่าใช้ดีฟอลต์ของ_dev():
    assert allowed_origins(None) == DEFAULT_ORIGINS
    assert allowed_origins("") == DEFAULT_ORIGINS
    assert allowed_origins("   ") == DEFAULT_ORIGINS


def test_โดเมนเดียว():
    assert allowed_origins("https://hr.example.com") == ["https://hr.example.com"]


def test_หลายโดเมนคั่นจุลภาคและตัดช่องว่าง():
    assert allowed_origins(" https://a.com , https://b.com ") == [
        "https://a.com",
        "https://b.com",
    ]


def test_ตัดสแลชท้ายออก():
    # Origin header ของเบราว์เซอร์ไม่เคยมี / ท้าย ถ้าไม่ตัดจะไม่ตรงแล้วโดนบล็อก
    assert allowed_origins("https://a.com/") == ["https://a.com"]


def test_ดาวถูกทิ้งเสมอ():
    # allow_credentials=True คู่กับ * เบราว์เซอร์ปฏิเสธอยู่แล้ว และถ้าใช้ได้ก็อันตราย
    assert allowed_origins("*") == DEFAULT_ORIGINS
    assert allowed_origins("*,https://a.com") == ["https://a.com"]


def test_ค่าว่างระหว่างจุลภาคไม่กลายเป็น_origin_ว่าง():
    assert allowed_origins("https://a.com,,") == ["https://a.com"]
