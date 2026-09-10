"""จุดตัดวันของตัวนับโควตา (app.llm_quota) — ต้องตรงกับรอบจริงของ Google.

รัน: docker compose exec backend python -m pytest tests/test_llm_quota.py -v

ทำไมถึงสำคัญ: Google รีเซ็ต RPD ตอนเที่ยงคืน Pacific ถ้าเราตัดวันคนละจุด call ที่ใช้
ตอนเช้า (เวลาไทย) จะถูกคิดสองต่อ — กินโควตาจริงของ "เมื่อวาน" ฝั่ง Google แต่โผล่ในยอด
"วันนี้" ของเรา ทำให้ช่วงบ่ายถูกพักงานทิ้งไว้ทั้งที่โควตาจริงรีเซ็ตไปแล้ว
ของเดิมใช้ UTC ซึ่งตอบผิด 30.6% ของเวลาทั้งปี

ยิงที่ quota_date(now, tz) ตรง ๆ จึงไม่ต้อง mock เวลาหรือ env เลย
(แพตเทิร์นเดียวกับ test_rate_limit.py)
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.llm_quota import _FALLBACK_OFFSET, _quota_tz, quota_date

PT = ZoneInfo("America/Los_Angeles")


def utc(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class TestรอบจริงของGoogle:
    """หน้าร้อน Pacific = UTC-7 → วันใหม่เริ่มตอน 07:00 UTC (14:00 น. เวลาไทย)."""

    def test_ก่อนเที่ยงคืน_pacific_ยังเป็นเมื่อวาน(self):
        """เคสที่ของเดิมพัง: ตี 3 UTC = 10 โมงเช้าไทย = ยังเป็นเมื่อวานฝั่ง Google
        แต่สูตร UTC เดิมตอบเป็นวันใหม่ไปแล้ว."""
        assert quota_date(utc(2026, 9, 10, 3), PT) == date(2026, 9, 9)

    def test_ขอบเขตหน้าร้อนอยู่ที่_07_00_utc(self):
        assert quota_date(utc(2026, 9, 10, 6, 59), PT) == date(2026, 9, 9)
        assert quota_date(utc(2026, 9, 10, 7, 0), PT) == date(2026, 9, 10)

    def test_ขอบเขตหน้าหนาวเลื่อนเป็น_08_00_utc(self):
        """พิสูจน์ว่าตาม DST จริง ไม่ได้ฮาร์ดโค้ดออฟเซ็ตไว้ตัวเดียว."""
        assert quota_date(utc(2026, 12, 10, 7, 59), PT) == date(2026, 12, 9)
        assert quota_date(utc(2026, 12, 10, 8, 0), PT) == date(2026, 12, 10)

    def test_utc_ตอบผิดจริงในช่วงคาบเกี่ยว(self):
        """ยืนยันว่าปัญหาที่กำลังแก้มีอยู่จริง ไม่ใช่แก้ของที่ไม่ได้เสีย."""
        t = utc(2026, 9, 10, 3)
        assert t.date() != quota_date(t, PT)


class Testทางถอยเมื่ออ่านเขตเวลาไม่ได้:
    def test_ยังคืนวันที่ได้โดยไม่ต้องมีฐานข้อมูลเขตเวลา(self):
        assert quota_date(utc(2026, 9, 10, 3), None) == date(2026, 9, 9)
        assert quota_date(utc(2026, 9, 10, 9), None) == date(2026, 9, 10)

    def test_หน้าหนาวทางถอยตรงกับ_pacific_เป๊ะ(self):
        """ออฟเซ็ตคงที่ 8 ชม. = PST พอดี ช่วงหน้าหนาวจึงไม่คลาดเลย."""
        for hh in range(24):
            t = utc(2026, 12, 10, hh)
            assert quota_date(t, None) == quota_date(t, PT)

    def test_ทางถอยไม่เคยตอบเร็วกว่า_pacific_สักครั้งในหนึ่งปี(self):
        """invariant ที่ห้ามหลุด — เหตุผลที่ _FALLBACK_OFFSET เป็น 8 ไม่ใช่ 7.

        "เร็วกว่า" = คิดว่าขึ้นวันใหม่แล้วทั้งที่ Google ยังไม่รีเซ็ต → สั่งงานไปเจอ 429
        กลางทาง ส่วน "ช้ากว่า" แค่พักงานเกินจำเป็นแล้วรอบหน้าก็รันเอง
        ถ้าใครแก้เป็น 7 เทสนี้จะพัง
        """
        t, end = utc(2026, 1, 1), utc(2027, 1, 1)
        while t < end:
            assert quota_date(t, None) <= quota_date(t, PT)
            t += timedelta(minutes=30)

    def test_ออฟเซ็ตต้องเป็น_8_ชั่วโมง(self):
        assert _FALLBACK_OFFSET == timedelta(hours=8)


class Testวันเปลี่ยนDST:
    """วันถอยเวลามี 25 ชม. วันเดินหน้ามี 23 ชม. — ต้องไม่ทำให้วันที่เพี้ยนหรือระเบิด."""

    @pytest.mark.parametrize(
        "moment", [utc(2026, 3, 8, 9, 30), utc(2026, 11, 1, 8, 30)]
    )
    def test_ตอบได้ไม่โยน_exception(self, moment):
        assert isinstance(quota_date(moment, PT), date)

    @pytest.mark.parametrize("day", [(2026, 3, 8), (2026, 11, 1)])
    def test_วันที่ต้องไม่เดินถอยหลังเมื่อเวลาเดินหน้า(self, day):
        """ถ้าวันที่ถอยหลังได้ ตัวนับจะกระโดดกลับไปอ่านแถวเก่าที่ยอดสูงกว่า
        แล้วพักงานทั้งที่โควตาเพิ่งรีเซ็ต."""
        t = utc(*day)
        end = t + timedelta(days=2)
        prev = quota_date(t, PT)
        while t < end:
            now = quota_date(t, PT)
            assert now >= prev
            prev = now
            t += timedelta(minutes=5)


class Testการอ่านเขตเวลาจากEnv:
    def test_อิมเมจนี้อ่านเขตเวลาได้จริง(self):
        """ถ้าเทสนี้พัง แปลว่าฐานอิมเมจเปลี่ยนไปเป็นตัวที่ไม่มี /usr/share/zoneinfo
        ระบบจะยังทำงานด้วยทางถอย แต่ควรรู้ตัว ไม่ใช่ปล่อยให้เงียบ."""
        assert _quota_tz() is not None

    @pytest.mark.parametrize("bad", ["Mars/Olympus", "../../etc/passwd", ""])
    def test_ชื่อโซนที่ใช้ไม่ได้ต้องถอยไปใช้ทางสำรอง_ไม่ใช่ระเบิด(self, bad, monkeypatch):
        """ชื่อที่ไม่มีจริงโยน ZoneInfoNotFoundError แต่ชื่อผิดรูปโยน ValueError
        ซึ่งคนละคลาสกัน — ดักแคบไปแล้ว env ที่พิมพ์ผิดจะทำให้ทั้งแอปล่ม."""
        import app.llm_quota as q

        monkeypatch.setattr(q, "_QUOTA_TZ_NAME", bad)
        q._quota_tz.cache_clear()
        try:
            assert q._quota_tz() is None
        finally:
            q._quota_tz.cache_clear()  # คืนแคชให้เทสอื่นเห็นค่าจริง


class TestTodayต่อกับของจริง:
    def test_today_ใช้เส้นทางเดียวกับ_quota_date(self):
        """today() ต้องเป็นแค่ตัวห่อบาง ๆ ไม่มี logic ของตัวเอง — ไม่งั้นจะมีจุดตัดวัน
        สองแหล่งที่หลุดไม่ตรงกันภายหลัง (บทเรียนเดียวกับ bands.py)."""
        from app.llm_quota import today

        assert today() == quota_date(datetime.now(timezone.utc), _quota_tz())
