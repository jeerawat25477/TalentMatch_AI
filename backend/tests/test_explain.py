"""ประโยคอธิบายคะแนน — ต้องไม่โกหก HR ในเคสขอบ.

เคสที่อันตรายที่สุดคือ JD ไม่มีเกณฑ์ทักษะเลย: matcher บังคับคะแนนเป็น 50 (REVIEW_FROM)
ซึ่งไม่ได้มาจากการเทียบทักษะ ถ้าประโยคบอกว่า "ได้ 50% เพราะขาดทักษะ..." จะเข้าใจผิดทันที

รัน: docker compose exec backend python -m pytest tests/test_explain.py -v
"""
import pytest

from app.agents.bands import REVIEW_FROM
from app.agents.explain import MAX_NAMED_SKILLS, explain_score


def gaps(m_req=(), x_req=(), m_pref=(), x_pref=()):
    return {
        "matched_required": list(m_req),
        "missing_required": list(x_req),
        "matched_preferred": list(m_pref),
        "missing_preferred": list(x_pref),
    }


class TestNoCriteria:
    """JD ไม่มีทักษะให้เทียบ — ห้ามอ้างว่าคะแนนมาจากทักษะ."""

    @pytest.mark.parametrize("g", [gaps(), {}, None])
    def test_ไม่อ้างว่ามาจากทักษะ(self, g):
        got = explain_score(g, REVIEW_FROM)
        assert "เพราะ" not in got
        assert f"{REVIEW_FROM}%" not in got
        assert "JD" in got


class TestBothSides:
    def test_ขาดบางข้อทั้งสองฝั่ง(self):
        got = explain_score(
            gaps(["Python"], ["Docker", "K8s"], ["Redis"], ["Kafka"]), 65
        )
        assert got.startswith("ได้ 65% เพราะ")
        assert "ขาดทักษะที่ต้องมี 2 จาก 3 ข้อ (Docker, K8s)" in got
        assert "ขาดทักษะที่อยากได้ 1 จาก 2 ข้อ (Kafka)" in got

    def test_ครบทุกข้อทั้งสองฝั่ง(self):
        got = explain_score(gaps(["Python", "SQL"], [], ["Redis"], []), 100)
        assert "มีทักษะที่ต้องมีครบทุกข้อ (2/2)" in got
        assert "มีทักษะที่อยากได้ครบทุกข้อ (1/1)" in got
        assert "ขาด" not in got

    def test_ไม่มีเลยสักข้อ(self):
        got = explain_score(gaps([], ["Docker"], [], ["Kafka"]), 0)
        assert "ไม่มีทักษะที่ต้องมีเลยสักข้อ (0/1)" in got
        assert "ขาด Docker" in got


class TestOneSidedJD:
    """JD ระบุแค่ฝั่งเดียว — อีกฝั่งต้องไม่โผล่ในประโยคเลย."""

    def test_มีแต่ทักษะที่ต้องมี(self):
        got = explain_score(gaps(["Python"], ["Docker"]), 30)
        assert "ทักษะที่ต้องมี" in got
        assert "ทักษะที่อยากได้" not in got

    def test_มีแต่ทักษะที่อยากได้(self):
        got = explain_score(gaps(m_pref=["Redis"], x_pref=["Kafka"]), 80)
        assert "ทักษะที่อยากได้" in got
        assert "ทักษะที่ต้องมี" not in got


class TestSkillNameTruncation:
    def test_ยกชื่อไม่เกินเพดานแล้วสรุปที่เหลือ(self):
        missing = ["A", "B", "C", "D", "E"]
        got = explain_score(gaps(["Python"], missing), 20)
        # ยกมา MAX_NAMED_SKILLS ตัวแรก ที่เหลือสรุป — กันประโยคยาวเป็นย่อหน้า
        assert "A, B, C และอีก 2 ข้อ" in got
        assert "D" not in got.split("และอีก")[0]

    def test_พอดีเพดานไม่ต้องสรุป(self):
        missing = ["A", "B", "C"][:MAX_NAMED_SKILLS]
        got = explain_score(gaps(["Python"], missing), 20)
        assert "และอีก" not in got
