"""สูตร fit score — เดิมไม่เคยมีเทสตรง ๆ ทั้งที่เป็นตัวเลขที่ HR ใช้ตัดสินคน.

บั๊กที่ทำให้ต้องเขียนไฟล์นี้ (พบ 2026-09-03): JD ที่ระบุแค่ required ทำให้ฝั่ง preferred
ถูกนับเป็นผ่านเต็ม ผู้สมัครที่ตรงเกณฑ์ 0/19 จึงได้ 40% ซึ่งอธิบายให้ HR เข้าใจไม่ได้เลย

รัน: docker compose exec backend python -m pytest tests/test_scoring.py -v
"""
from app.agents.bands import REVIEW_FROM
from app.agents.nodes.matcher import (
    PREFERRED_WEIGHT,
    REQUIRED_WEIGHT,
    match_candidates,
)


def score(required: list[str], preferred: list[str], owned: list[str]) -> int:
    """คะแนนของผู้สมัครที่มีทักษะ `owned` เทียบกับ JD ที่ให้มา."""
    state = {
        "raw_jd": "",
        "raw_resumes": [{"candidate_id": "c1", "filename": "", "content": "x" * 2000}],
        "analyzed_jd": {"required_skills": required, "preferred_skills": preferred},
        "parsed_resumes": [{"candidate_id": "c1", "skills": owned}],
        "evaluations": [],
        "bias_revision_count": {},
        "bias_revision_pending": {},
        "bias_exclusions": {},
    }
    return match_candidates(state)["evaluations"][0]["fit_score"]


class TestBothSides:
    """JD ระบุครบสองฝั่ง — น้ำหนัก 60/40 ตามบรีฟ."""

    def test_ตรงหมดได้เต็ม(self):
        assert score(["Python"], ["Docker"], ["Python", "Docker"]) == 100

    def test_ไม่ตรงเลยได้ศูนย์(self):
        assert score(["Python"], ["Docker"], ["Excel"]) == 0

    def test_ตรงแต่ฝั่งที่ต้องมี(self):
        assert score(["Python"], ["Docker"], ["Python"]) == REQUIRED_WEIGHT

    def test_ตรงแต่ฝั่งที่อยากได้(self):
        assert score(["Python"], ["Docker"], ["Docker"]) == PREFERRED_WEIGHT


class TestOneSidedJD:
    """JD ระบุฝั่งเดียว — ฝั่งนั้นต้องกลายเป็น 100% ห้ามแจกคะแนนอีกฝั่งให้ฟรี."""

    def test_มีแต่required_ไม่ตรงเลยต้องได้ศูนย์(self):
        # เคสจริงที่เจอ: เดิมได้ 40 เพราะ preferred ถูกนับเป็นผ่านเต็ม
        assert score([f"s{i}" for i in range(19)], [], ["Excel"]) == 0

    def test_มีแต่required_ตรงหมดต้องได้เต็ม(self):
        assert score(["Python", "Docker"], [], ["Python", "Docker"]) == 100

    def test_มีแต่required_ตรงครึ่งเดียว(self):
        assert score(["Python", "Docker"], [], ["Python"]) == 50

    def test_มีแต่preferred_ไม่ตรงเลยต้องได้ศูนย์(self):
        assert score([], ["Docker"], ["Excel"]) == 0

    def test_มีแต่preferred_ตรงหมดต้องได้เต็ม(self):
        assert score([], ["Docker"], ["Docker"]) == 100

    def test_เคสจริง_ตรง_2_จาก_19(self):
        # Somchai: เดิมได้ 46 (2/19 ของ 60 = 6 บวกคะแนนฟรี 40) ตอนนี้ต้องเป็น 11
        req = [f"s{i}" for i in range(19)]
        assert score(req, [], ["s0", "s1"]) == round(100 * 2 / 19)


class TestNoCriteria:
    """JD ไม่มีเกณฑ์ทักษะเลย — ต้องตกแบนด์รอ HR ไม่ใช่ได้ 100 ยกแผง."""

    def test_ไม่มีเกณฑ์เลยได้คะแนนกลาง(self):
        assert score([], [], ["Python"]) == REVIEW_FROM

    def test_เกณฑ์มีแต่ชื่อบทบาทก็ถือว่าไม่มีเกณฑ์(self):
        # is_skill กรอง "engineers"/"product owners" ออก ตัวหารจึงเหลือศูนย์
        assert score(["engineers"], ["product owners"], ["Python"]) == REVIEW_FROM


# ---------- แยกองค์ประกอบคะแนน (score_breakdown) ----------
# หน้าเว็บแสดง "ฝั่งไหนได้กี่คะแนน" จากตัวเลขชุดนี้ตรง ๆ โดยไม่มีสูตรของตัวเอง
# จึงต้องพิสูจน์ว่ามันเป็นสูตรเดียวกับ compute_fit_score ทุกกรณี ไม่ใช่สำเนาที่หลุดได้


def _names(n: int, prefix: str) -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


class TestScoreBreakdown:
    def test_สองฝั่งใช้น้ำหนัก_60_40(self):
        from app.agents.nodes.matcher import score_breakdown

        b = score_breakdown(["a", "b"], ["c"], ["d"], ["e"])
        assert b["required"] == {
            "matched": 2, "total": 3, "weight": REQUIRED_WEIGHT,
            "points": REQUIRED_WEIGHT * 2 / 3,
        }
        assert b["preferred"]["weight"] == PREFERRED_WEIGHT
        assert b["preferred"]["points"] == PREFERRED_WEIGHT / 2
        assert b["no_criteria"] is False

    def test_JD_มีแค่_required_ฝั่งนั้นคิดเต็ม_100_และอีกฝั่งเป็น_None(self):
        """ฝั่งที่ JD ไม่ระบุต้องไม่ถูกโชว์เป็น 0/0 ที่ดูเหมือนคะแนนเสียหาย."""
        from app.agents.nodes.matcher import score_breakdown

        b = score_breakdown(["a"], ["b", "c", "d"], [], [])
        assert b["preferred"] is None
        assert b["required"]["weight"] == 100
        assert b["required"]["points"] == 25
        assert b["total"] == 25

    def test_JD_มีแค่_preferred_ก็คิดเต็ม_100(self):
        from app.agents.nodes.matcher import score_breakdown

        b = score_breakdown([], [], ["a"], ["b"])
        assert b["required"] is None
        assert b["preferred"]["weight"] == 100

    def test_ไม่มีเกณฑ์เลยตรงกับกรณีที่บังคับเป็น_REVIEW_FROM(self):
        from app.agents.nodes.matcher import score_breakdown

        b = score_breakdown([], [], [], [])
        assert b["no_criteria"] is True
        assert b["required"] is None and b["preferred"] is None
        assert b["total"] == REVIEW_FROM

    def test_ผลรวมปัดแล้วเท่า_compute_fit_score_ทุกชุด(self):
        """ถ้าวันไหนมีคนแก้สูตรที่เดียว เทสนี้จะแดงทันที."""
        from app.agents.nodes.matcher import compute_fit_score, score_breakdown

        for mr in range(6):
            for xr in range(6):
                for mp in range(6):
                    for xp in range(6):
                        args = (_names(mr, "r"), _names(xr, "R"), _names(mp, "p"), _names(xp, "P"))
                        b = score_breakdown(*args)
                        assert round(b["total"]) == compute_fit_score(*args), args
                        parts = [s["points"] for s in (b["required"], b["preferred"]) if s]
                        if not b["no_criteria"]:
                            assert abs(sum(parts) - b["total"]) < 1e-9


# ---------- องค์ประกอบคะแนนในหน้ารายละเอียด (routers/candidates) ----------


class TestBreakdownForDetail:
    def test_ไม่มี_gap_analysis_ไม่ส่งองค์ประกอบ(self):
        from app.routers.candidates import _breakdown_for

        assert _breakdown_for(None, None) is None
        assert _breakdown_for({}, 50) is None

    def test_คะแนนตรงสูตรปัจจุบัน(self):
        from app.routers.candidates import _breakdown_for

        gap = {"matched_required": ["a", "b"], "missing_required": ["c"],
               "matched_preferred": ["d"], "missing_preferred": ["e"]}
        b = _breakdown_for(gap, 60)  # 40 + 20
        assert b["matches_stored_score"] is True
        assert round(b["total"]) == 60

    def test_คะแนนที่บันทึกด้วยสูตรเก่าต้องถูกจับได้(self):
        """แถวจริง: AI Engineer ที่ตรง 0 ข้อแต่ได้ 40 จากสูตรเก่าที่แจกฝั่งว่างฟรี."""
        from app.routers.candidates import _breakdown_for

        gap = {"matched_required": [], "missing_required": ["a", "b"],
               "matched_preferred": [], "missing_preferred": []}
        b = _breakdown_for(gap, 40)
        assert b["matches_stored_score"] is False
        assert b["total"] == 0
