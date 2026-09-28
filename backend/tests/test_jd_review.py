"""JD Reviewer — ตรวจว่าประกาศใช้คัดกรองเรซูเม่ได้ดีแค่ไหน ก่อนกดวิเคราะห์ (คนละจังหวะกับ jd_analyzer).

สิ่งที่เทสชุดนี้กัน:
1. endpoint นี้ต้อง **ไม่เขียนอะไรลง DB** — เป็นพรีวิวล้วน ๆ
2. โควตา LLM หมดต้องได้ 503 ไม่ใช่ 500 เปล่า ๆ (แบบเดียวกับ /candidates/search)
3. กดรัว ๆ ต้องโดนเบรกก่อนเสียโควตา ไม่ใช่หลังเสีย
4. ห้ามยิง LLM จริงในเทส — monkeypatch ทุกเคส

รัน: docker compose exec backend python -m pytest tests/test_jd_review.py -v
"""
import pytest
from fastapi.testclient import TestClient

from app.agents.models import JDMustHaveReview, JDReview, JDScreeningIssue
from app.agents.nodes.matcher import PREFERRED_WEIGHT, REQUIRED_WEIGHT
from app.agents.nodes import jd_reviewer
from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers import jobs

URL = "/api/v1/jobs/review-jd"

SAMPLE_JD = """ตำแหน่ง: Backend Developer
ต้องมี: Python, Go, Rust, Kubernetes, การตลาด, งานบัญชี, ขยัน อดทน, เก่งคอมพิวเตอร์"""

FAKE_RESULT = JDReview(
    scope_assessment="too_broad",
    scope_comment="รวมหลายบทบาทไว้ในตำแหน่งเดียว",
    unmeasurable=[JDScreeningIssue(phrase="ขยัน อดทน", suggestion="ถามตอนสัมภาษณ์")],
    vague_skills=[JDScreeningIssue(phrase="เก่งคอมพิวเตอร์", suggestion="ระบุเป็น Excel, Word")],
    structure_issues=["ไม่แยกหัวข้อต้องมีกับอยากได้"],
    must_have_review=[
        JDMustHaveReview(skill="งานบัญชี", reason="ไม่เกี่ยวกับตำแหน่ง Backend")
    ],
    posting_tips=["ช่วงเงินเดือน"],
    overall_comment="ควรตัดเกณฑ์ที่ไม่เกี่ยวข้องออกก่อนวิเคราะห์",
)


@pytest.fixture(autouse=True)
def reset_limit():
    """ล้างตัวนับก่อน/หลังทุกเทส — เป็น state ระดับโมดูล จะรั่วข้ามเทสได้."""
    jobs._jd_review_hits.clear()
    yield
    jobs._jd_review_hits.clear()


@pytest.fixture
def fake_llm(monkeypatch) -> list:
    """กันไม่ให้ยิง LLM จริง — เก็บ prompt ที่ถูกส่งไว้ตรวจแทน."""
    prompts: list[str] = []

    def fake(prompt, schema, complex=False):
        prompts.append(prompt)
        return FAKE_RESULT

    monkeypatch.setattr(jd_reviewer, "structured_invoke_once", fake)
    return prompts


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestReviewJdFunction:
    """ฟังก์ชันเดี่ยว — ไม่ใช่โหนดในกราฟ จึงรับ str ตรง ๆ."""

    def test_ส่งข้อความประกาศเข้า_prompt_จริง(self, fake_llm):
        jd_reviewer.review_jd(SAMPLE_JD)
        assert "ขยัน อดทน, เก่งคอมพิวเตอร์" in fake_llm[0]

    def test_prompt_อธิบายวิธีให้คะแนนด้วยน้ำหนักจริงของ_matcher(self, fake_llm):
        """คำแนะนำต้องอิงกลไกของระบบนี้ — น้ำหนักมาจาก matcher.py ไม่เขียนเลขซ้ำ."""
        jd_reviewer.review_jd(SAMPLE_JD)
        assert f"ต้องมี {REQUIRED_WEIGHT}% + อยากได้ {PREFERRED_WEIGHT}%" in fake_llm[0]
        assert "ข้อบังคับ" in fake_llm[0]

    def test_ตรวจเพื่อคัดกรอง_ไม่ใช่เพื่อโพสต์(self, fake_llm):
        """เดิมตั้งบทเป็นที่ปรึกษาก่อนโพสต์ แล้วแนะนำสถานที่ทำงาน/ไฮบริดซึ่งไม่มีผลกับคะแนน."""
        jd_reviewer.review_jd(SAMPLE_JD)
        assert "คัดกรอง" in fake_llm[0]
        assert "ความสำคัญต่ำสุด" in fake_llm[0]  # posting_tips อยู่ท้ายสุด

    def test_ไม่ตรวจอคติซ้ำกับตัวตรวจตอนวิเคราะห์(self, fake_llm):
        jd_reviewer.review_jd(SAMPLE_JD)
        assert "ไม่ต้องตรวจเรื่องอคติ" in fake_llm[0]
        assert "bias_flags" not in fake_llm[0]
        assert "bias_flags" not in JDReview.model_fields

    def test_ตัดประกาศที่ยาวเกินเพดาน(self, fake_llm):
        # ใช้ "X" เป็นตัวเติมเพราะเทมเพลต prompt เป็นภาษาไทยล้วน จะได้นับเฉพาะส่วนที่เป็น JD
        jd_reviewer.review_jd("X" * (jd_reviewer.MAX_JD_CHARS + 500))
        assert fake_llm[0].count("X") == jd_reviewer.MAX_JD_CHARS

    def test_ไม่ผ่าน_retry_เพราะมีคนนั่งรอ(self):
        """ต้องใช้ structured_invoke_once — ถ้าเผลอใช้ตัวมี retry จะค้างเป็นนาทีตอนโควตาหมด."""
        from app.agents.llm import structured_invoke_once

        assert not hasattr(structured_invoke_once, "retry")


class TestAuthGate:
    def test_ต้องล็อกอินก่อน(self, anon):
        assert anon.post(URL, json={"raw_text": SAMPLE_JD}).status_code == 401


class TestValidation:
    @pytest.mark.parametrize("raw", ["", None])
    def test_ข้อความว่างต้อง_422(self, client, fake_llm, raw):
        assert client.post(URL, json={"raw_text": raw}).status_code == 422
        assert fake_llm == []  # ต้องไม่เสียโควตา

    def test_ยาวเกินเพดานต้อง_422_ก่อนเรียก_llm(self, client, fake_llm):
        assert client.post(URL, json={"raw_text": "ก" * 20001}).status_code == 422
        assert fake_llm == []


class TestEndpoint:
    def test_คืนผลรีวิวครบทุกส่วน(self, client, fake_llm):
        r = client.post(URL, json={"raw_text": SAMPLE_JD})
        assert r.status_code == 200
        body = r.json()
        assert body["scope_assessment"] == "too_broad"
        assert body["unmeasurable"][0]["phrase"] == "ขยัน อดทน"
        assert body["vague_skills"][0]["phrase"] == "เก่งคอมพิวเตอร์"
        assert body["structure_issues"] == ["ไม่แยกหัวข้อต้องมีกับอยากได้"]
        assert body["must_have_review"][0]["skill"] == "งานบัญชี"
        assert body["posting_tips"] == ["ช่วงเงินเดือน"]
        assert "bias_flags" not in body and "missing_info" not in body
        assert body["overall_comment"]

    def test_ไม่เขียนอะไรลง_db(self, client, fake_llm):
        """เป็นพรีวิวล้วน ๆ — ห้ามสร้างแถว jobs โดยไม่ตั้งใจ."""
        with get_conn() as conn:
            before = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
        client.post(URL, json={"raw_text": SAMPLE_JD})
        with get_conn() as conn:
            after = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
        assert before == after

    def test_llm_ล้มต้องได้_503_ไม่ใช่_500(self, client, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(jd_reviewer, "structured_invoke_once", boom)
        r = client.post(URL, json={"raw_text": SAMPLE_JD})
        assert r.status_code == 503
        assert "ชั่วคราว" in r.json()["detail"]


class TestRateLimit:
    def test_กดเกินเพดานต้องได้_429(self, client, fake_llm):
        limit = jobs.JD_REVIEW_MAX_PER_MIN
        for _ in range(limit):
            assert client.post(URL, json={"raw_text": SAMPLE_JD}).status_code == 200
        r = client.post(URL, json={"raw_text": SAMPLE_JD})
        assert r.status_code == 429
        # ข้อความต้องบอกทั้งเพดานและเวลาที่ต้องรอ ไม่ใช่ error ดิบ
        assert str(limit) in r.json()["detail"]
        assert "วินาที" in r.json()["detail"]

    def test_ครั้งที่โดนเบรกต้องไม่เสียโควตา(self, client, fake_llm):
        limit = jobs.JD_REVIEW_MAX_PER_MIN
        for _ in range(limit + 3):
            client.post(URL, json={"raw_text": SAMPLE_JD})
        # เรียก LLM แค่เท่าเพดาน ส่วนที่เกินถูกตัดตั้งแต่ก่อนถึง LLM
        assert len(fake_llm) == limit
