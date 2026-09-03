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
