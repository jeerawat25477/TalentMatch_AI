"""ขั้น "ยืนยันเกณฑ์" ก่อนสร้างตำแหน่ง — POST /jobs/analyze + POST /jobs พร้อมเกณฑ์ที่ยืนยันแล้ว.

รัน: docker compose exec backend python -m pytest tests/test_job_confirm_criteria.py -v

LLM ถูก mock ทั้งไฟล์ ไม่เสียโควตา

สิ่งที่เทสชุดนี้กัน:
1. วิเคราะห์แล้ว **ยังไม่มีอะไรถูกบันทึก** — HR ต้องกดยืนยันก่อน
2. สร้างด้วยเกณฑ์ที่ยืนยันแล้ว **ต้องไม่เรียก AI ซ้ำ** (AI อ่านไปแล้วตอนวิเคราะห์)
3. HR แก้ร่าง → เก็บของ AI ไว้ให้ "คืนค่าตามที่ AI ดึง" · ไม่แก้ → ถือว่าเป็นของ AI ล้วน
4. AI อ่านไม่สำเร็จ → ยังสร้างตำแหน่งได้ด้วยเกณฑ์ที่ HR กรอกเอง
5. ทางเดิม (ส่งแค่ข้อความ) ยังใช้ได้เหมือนเดิม
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agents.models import JDExtraction, JDSkillItem, JobRequirement
from app.auth import get_current_user
from app.database import get_conn
from app.main import app

JD = """Senior Python Developer
Requirements:
Backend: Python, FastAPI
Nice to have: Docker หรือ Kubernetes"""


def item(name, necessity="must", section="qualifications", group="", line=None, kind="technology"):
    return JDSkillItem(
        source_line=line if line is not None else name, name=name, kind=kind,
        necessity=necessity, section=section, group=group,
    )


def extraction() -> JDExtraction:
    quals = "Backend: Python, FastAPI"
    nice = "Nice to have: Docker หรือ Kubernetes"
    return JDExtraction(
        job_title="Senior Python Developer", min_experience_years=3, education="ป.ตรี",
        items=[
            item("Python", line=quals), item("FastAPI", line=quals),
            item("Docker", necessity="one_of", group="c", line=nice),
            item("Kubernetes", necessity="one_of", group="c", line=nice),
        ],
    )


def fake_extract(raw_jd, once=False):
    from app.agents.nodes.jd_analyzer import to_requirement

    ex = extraction()
    return to_requirement(ex, raw_jd), ex


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_real_bias_llm():
    """/jobs/analyze เรียก audit_jd ต่อจากร่างเกณฑ์ — ห้ามหลุดไปเรียก Gemini จริงในเทสต์."""
    from app.agents.models import BiasAudit

    from app.routers import jobs

    # เพดาน 5 ครั้ง/นาทีเก็บในหน่วยความจำต่อผู้ใช้ — เทสต์ในไฟล์นี้เรียก analyze เกินนั้น
    jobs._reanalyze_hits.clear()
    passed = BiasAudit(is_biased=False, audit_status="passed", audit_log="ไม่พบ")
    with patch("app.routers.jobs.audit_jd", return_value=passed) as m:
        yield m


@pytest.fixture(autouse=True)
def clean_jobs():
    """ลบตำแหน่งที่เทสสร้าง (จับจาก raw_text) — cascade เก็บของที่เหลือ."""
    yield
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE raw_text = %s", (JD,))
        conn.commit()


def created(conn):
    return conn.execute(
        """SELECT id, title, parsed_criteria, jd_extraction, ai_criteria, criteria_edited_at
             FROM jobs WHERE raw_text = %s""",
        (JD,),
    ).fetchall()


class TestAnalyze:
    def test_ต้องล็อกอินก่อน(self):
        assert TestClient(app).post("/api/v1/jobs/analyze", json={"raw_text": JD}).status_code == 401

    def test_คืนร่างเกณฑ์โดยไม่บันทึกอะไร(self, client):
        with patch("app.routers.jobs.extract_jd", side_effect=fake_extract) as m:
            body = client.post("/api/v1/jobs/analyze", json={"raw_text": JD}).json()
        assert m.call_args.kwargs["once"] is True  # HR นั่งรอ ไม่ retry
        assert body["job_title"] == "Senior Python Developer"
        assert body["min_experience_years"] == 3
        assert body["required_skills"] == ["Python", "FastAPI"]
        assert body["preferred_skills"] == ["Docker | Kubernetes"]
        assert body["extraction"]["items"]  # ป้ายดิบส่งกลับไปให้ยืนยัน
        with get_conn() as conn:
            assert created(conn) == []

    def test_บอกที่มาของแต่ละข้อจากบรรทัดจริงในประกาศ(self, client):
        with patch("app.routers.jobs.extract_jd", side_effect=fake_extract):
            body = client.post("/api/v1/jobs/analyze", json={"raw_text": JD}).json()
        assert body["sources"]["Python"] == ["Backend: Python, FastAPI"]
        # กลุ่มรวมบรรทัดของทุกตัวเลือก
        assert body["sources"]["Docker | Kubernetes"] == ["Nice to have: Docker หรือ Kubernetes"]

    def test_มีคำเตือนเมื่อเกณฑ์น่าสงสัย(self, client):
        def bloated(raw_jd, once=False):
            skills = [f"Skill{i}" for i in range(20)]  # เกิน BLOATED_REQUIRED (15)
            ex = JDExtraction(job_title="T", min_experience_years=0, education="",
                              items=[item(s) for s in skills])
            return JobRequirement(job_title="T", min_experience_years=0, education="",
                                  required_skills=skills, preferred_skills=[]), ex

        with patch("app.routers.jobs.extract_jd", side_effect=bloated):
            body = client.post("/api/v1/jobs/analyze", json={"raw_text": JD}).json()
        assert any("ต้องมี" in w for w in body["warnings"])

    def test_ai_ล้มคืน_502(self, client):
        with patch("app.routers.jobs.extract_jd", side_effect=RuntimeError("boom")):
            res = client.post("/api/v1/jobs/analyze", json={"raw_text": JD})
        assert res.status_code == 502

    def test_โควตาเต็มคืน_429_โดยไม่เรียก_ai(self, client):
        with patch("app.routers.jobs.has_room", return_value=False), \
             patch("app.routers.jobs.extract_jd") as m:
            res = client.post("/api/v1/jobs/analyze", json={"raw_text": JD})
        assert res.status_code == 429 and m.call_count == 0

    # ── ตรวจอคติของประกาศครั้งเดียวตอนวิเคราะห์ (2026-09-28) ──

    def test_เช็คโควตาให้พอสองครั้ง(self, client):
        """ร่างเกณฑ์ + ตรวจอคติ = 2 call — เหลือ 1 ต้องไม่เริ่ม ไม่งั้นตายกลางทาง."""
        from app.routers.jobs import ANALYZE_COST

        with patch("app.routers.jobs.has_room", return_value=False) as room, \
             patch("app.routers.jobs.extract_jd") as m:
            client.post("/api/v1/jobs/analyze", json={"raw_text": JD})
        assert ANALYZE_COST == 2 and room.call_args.args[1] == 2 and m.call_count == 0

    def test_ตัวตรวจเห็นเกณฑ์ที่ร่างแล้ว(self, client, no_real_bias_llm):
        """ต้องรันหลังร่างเกณฑ์ ไม่ใช่คู่กัน — ไม่งั้นชี้เกณฑ์ทักษะที่มีอคติไม่ได้."""
        with patch("app.routers.jobs.extract_jd", side_effect=fake_extract):
            body = client.post("/api/v1/jobs/analyze", json={"raw_text": JD}).json()
        args = no_real_bias_llm.call_args.args
        assert args[1] == ["Python", "FastAPI"] and args[2] == ["Docker | Kubernetes"]
        assert body["bias"]["status"] == "passed" and body["bias"]["llm_checked"] is True
        assert body["bias_llm"]["audit_status"] == "passed"

    def test_ตัวตรวจล้มแล้ววิเคราะห์ยังสำเร็จด้วยกฎตายตัว(self, client, no_real_bias_llm):
        no_real_bias_llm.side_effect = RuntimeError("quota")
        biased = JD + "\nเพศชาย อายุไม่เกิน 30 ปี"
        with patch("app.routers.jobs.extract_jd", side_effect=fake_extract):
            res = client.post("/api/v1/jobs/analyze", json={"raw_text": biased})
        assert res.status_code == 200
        bias = res.json()["bias"]
        assert bias["status"] == "flagged" and bias["llm_checked"] is False
        assert "เพศชาย" in bias["jd_criteria"]
        assert res.json()["bias_llm"] is None


class TestCreateWithConfirmedCriteria:
    def confirm(self, **over):
        ex = extraction()
        body = {
            "job_title": "Senior Python Developer",
            "min_experience_years": 3,
            "education": "ป.ตรี",
            "required_skills": ["Python", "FastAPI"],
            "preferred_skills": ["Docker | Kubernetes"],
            "extraction": ex.model_dump(),
        }
        body.update(over)
        return {"raw_text": JD, "criteria": body}

    def test_ไม่เรียก_ai_ซ้ำและบันทึกเกณฑ์ที่ยืนยัน(self, client):
        with patch("app.routers.jobs.extract_jd") as m:
            res = client.post("/api/v1/jobs", json=self.confirm())
        assert res.status_code == 201 and m.call_count == 0
        job = res.json()
        assert job["title"] == "Senior Python Developer"
        assert job["parsed_criteria"]["required_skills"] == ["Python", "FastAPI"]
        with get_conn() as conn:
            row = created(conn)[0]
        assert row["jd_extraction"]["items"]  # ป้ายดิบถูกเก็บ (สคริปต์จัดฝั่งใหม่ต้องใช้)

    def test_ไม่แก้ร่างถือว่าเป็นของ_ai_ล้วน(self, client):
        client.post("/api/v1/jobs", json=self.confirm())
        with get_conn() as conn:
            row = created(conn)[0]
        assert row["ai_criteria"] is None and row["criteria_edited_at"] is None

    def test_แก้ร่างแล้วเก็บของ_ai_ไว้ให้คืนค่าได้(self, client):
        client.post("/api/v1/jobs", json=self.confirm(required_skills=["Python"]))
        with get_conn() as conn:
            row = created(conn)[0]
        assert row["criteria_edited_at"] is not None
        assert row["ai_criteria"]["required_skills"] == ["Python", "FastAPI"]
        assert row["parsed_criteria"]["required_skills"] == ["Python"]

    def test_สลับลำดับอย่างเดียวไม่นับว่าแก้(self, client):
        """ทำความสะอาดทั้งสองฝั่งก่อนเทียบ — ช่องว่างเกินต้องไม่ถูกนับว่าแก้."""
        client.post("/api/v1/jobs", json=self.confirm(required_skills=[" Python ", "FastAPI"]))
        with get_conn() as conn:
            row = created(conn)[0]
        assert row["ai_criteria"] is None and row["criteria_edited_at"] is None

    def test_ai_ล้มแล้ว_hr_กรอกเองยังสร้างได้(self, client):
        res = client.post("/api/v1/jobs", json=self.confirm(
            extraction=None, required_skills=["Python"], preferred_skills=[],
        ))
        assert res.status_code == 201
        with get_conn() as conn:
            row = created(conn)[0]
        assert row["jd_extraction"] is None
        assert row["ai_criteria"] is None  # ไม่มีของ AI ให้คืนค่า
        assert row["criteria_edited_at"] is not None  # แต่เป็นเกณฑ์ที่คนกรอก ไม่ใช่ของ AI
        assert row["parsed_criteria"]["required_skills"] == ["Python"]

    def _audit(self):
        with get_conn() as conn:
            return conn.execute(
                "SELECT jd_audit FROM jobs WHERE raw_text LIKE %s", (JD + "%",)
            ).fetchone()["jd_audit"]

    def test_เก็บผลตรวจของตำแหน่งจากที่_llm_ตรวจไว้(self, client):
        from app.agents.models import BiasAudit

        llm = BiasAudit(
            is_biased=True, audit_status="flagged", audit_log="ใช้สถาบันเป็นเกณฑ์",
            biased_required_skills=["FastAPI", "ไม่อยู่ในเกณฑ์แล้ว"],
        )
        client.post("/api/v1/jobs", json=self.confirm(bias_llm=llm.model_dump()))
        audit = self._audit()
        assert audit["status"] == "flagged" and audit["llm_checked"] is True
        assert audit["log"].startswith("ใช้สถาบันเป็นเกณฑ์")
        # ชื่อที่ HR ลบไปแล้วในขั้นยืนยันถอดไม่ได้อยู่ดี — กรองทิ้งตอนเก็บ
        assert audit["biased_required_skills"] == ["FastAPI"]

    def test_กฎตายตัวคำนวณใหม่ฝั่ง_server_แม้หน้าเว็บไม่ส่งผลตรวจมา(self, client):
        global JD
        original = JD
        JD = original + "\nเพศชาย อายุไม่เกิน 30 ปี"
        try:
            client.post("/api/v1/jobs", json=self.confirm())  # ไม่มี bias_llm
            audit = self._audit()
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM jobs WHERE raw_text = %s", (JD,))
                conn.commit()
            JD = original
        assert audit["status"] == "flagged" and audit["llm_checked"] is False
        assert "เพศชาย" in audit["jd_criteria"]

    def test_ยืนยันถ้อยคำตั้งแต่ขั้นยืนยันเกณฑ์(self, client):
        global JD
        original = JD
        JD = original + "\nเพศหญิง"
        reason = "งานตรวจค้นตัวผู้โดยสารหญิง กฎหมายกำหนด"
        try:
            res = client.post("/api/v1/jobs", json=self.confirm(bias_acks=[
                {"phrase": "เพศหญิง", "reason": reason},
                {"phrase": "แต่งขึ้นเอง", "reason": reason},  # ไม่อยู่ในผลตรวจ → ทิ้ง
            ]))
            short = client.post("/api/v1/jobs", json=self.confirm(bias_acks=[
                {"phrase": "เพศหญิง", "reason": "ok"},
            ]))
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM jobs WHERE raw_text = %s", (JD,))
                conn.commit()
            JD = original
        bias = res.json()["bias"]
        assert res.status_code == 201 and bias["status"] == "passed"
        assert [a["phrase"] for a in bias["acknowledged"]] == ["เพศหญิง"]
        assert bias["acknowledged"][0]["by"] == "admin-test"  # จาก token ไม่ใช่จากหน้าเว็บ
        assert short.status_code == 422  # เหตุผลสั้นเกิน ไม่สร้างตำแหน่ง

    def test_ประกาศสะอาดไม่มี_llm_ผ่าน(self, client):
        client.post("/api/v1/jobs", json=self.confirm())
        audit = self._audit()
        assert audit["status"] == "passed" and audit["jd_criteria"] == []

    def test_ทางเดิมยังใช้ได้(self, client):
        """ส่งแค่ข้อความ = ให้ AI อ่านตอนสร้าง เหมือนก่อนมีขั้นยืนยัน."""
        with patch("app.routers.jobs.extract_jd", side_effect=fake_extract) as m:
            res = client.post("/api/v1/jobs", json={"raw_text": JD})
        assert res.status_code == 201 and m.call_count == 1
        assert res.json()["parsed_criteria"]["required_skills"] == ["Python", "FastAPI"]


class TestBiasedSkillTypedByHR:
    """ช่องโหว่ 2026-10-07: HR พิมพ์ทักษะที่ตรงกับอคติกลับเข้าเกณฑ์ได้หลัง AI ตรวจไปแล้ว
    → บันทึกไม่ได้ (409) จนกว่าจะลบออก หรือยืนยันถ้อยคำนั้นว่าจำเป็นพร้อมเหตุผล."""

    PHRASE = "เป็นเจ้าของภาษาอังกฤษ (Native English speaker)"

    def payload(self, required, acks=()):
        from app.agents.models import BiasAudit

        llm = BiasAudit(is_biased=True, audit_status="flagged", audit_log="กีดกันตามถิ่นกำเนิด",
                        biased_jd_criteria=[self.PHRASE])
        body = TestCreateWithConfirmedCriteria().confirm(
            required_skills=required, bias_llm=llm.model_dump(),
            bias_acks=[{"phrase": self.PHRASE, "reason": r} for r in acks],
        )
        body["raw_text"] = JD + "\n- " + self.PHRASE  # LLM ยกถ้อยคำได้เฉพาะที่อยู่ในประกาศจริง
        return body

    def _cleanup(self):
        with get_conn() as conn:
            conn.execute("DELETE FROM jobs WHERE raw_text LIKE %s", (JD + "%",))
            conn.commit()

    def test_ทักษะอคติที่ยังไม่ยืนยันบันทึกไม่ได้(self, client):
        try:
            res = client.post("/api/v1/jobs", json=self.payload(["Python", "Native English speaker"]))
            assert res.status_code == 409
            detail = res.json()["detail"]
            assert detail["code"] == "biased_skill"
            assert detail["skills"][0]["skill"] == "Native English speaker"
            assert detail["skills"][0]["phrase"] == self.PHRASE
            with get_conn() as conn:
                n = conn.execute("SELECT count(*) AS n FROM jobs WHERE raw_text LIKE %s",
                                 (JD + "%",)).fetchone()["n"]
            assert n == 0, "409 ต้องไม่บันทึกอะไร"
        finally:
            self._cleanup()

    def test_ยืนยันถ้อยคำแล้วบันทึกได้และนับคะแนน(self, client):
        try:
            res = client.post("/api/v1/jobs", json=self.payload(
                ["Python", "Native English speaker"], acks=["งานแปลเอกสารให้ลูกค้าต่างชาติ"]))
            assert res.status_code == 201
            assert "Native English speaker" in res.json()["parsed_criteria"]["required_skills"]
        finally:
            self._cleanup()

    def test_ไม่มีทักษะอคติทำงานเหมือนเดิม(self, client):
        try:
            assert client.post("/api/v1/jobs", json=self.payload(["Python", "English"])).status_code == 201
        finally:
            self._cleanup()
