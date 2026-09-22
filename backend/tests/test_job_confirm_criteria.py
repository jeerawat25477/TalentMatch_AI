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

    def test_ทางเดิมยังใช้ได้(self, client):
        """ส่งแค่ข้อความ = ให้ AI อ่านตอนสร้าง เหมือนก่อนมีขั้นยืนยัน."""
        with patch("app.routers.jobs.extract_jd", side_effect=fake_extract) as m:
            res = client.post("/api/v1/jobs", json={"raw_text": JD})
        assert res.status_code == 201 and m.call_count == 1
        assert res.json()["parsed_criteria"]["required_skills"] == ["Python", "FastAPI"]
