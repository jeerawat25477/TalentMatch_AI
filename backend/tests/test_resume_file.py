"""ไฟล์เรซูเม่ PDF ต้นฉบับ — เก็บตอนรับไฟล์ + เสิร์ฟให้ HR เปิดดู (ไม่ยิง LLM).

รัน: docker compose exec backend python -m pytest tests/test_resume_file.py -v

สิ่งที่เทสชุดนี้กัน:
1. ไฟล์ที่รับจริงถูกเก็บ ไฟล์ซ้ำ/อ่านไม่ออกไม่ถูกเก็บ
2. **เก็บไฟล์พังแล้วการรับใบสมัครต้องไม่พัง** และไม่พาทั้งชุดอัปโหลดหายไปด้วย
3. endpoint ต้องล็อกอิน · ไม่มีไฟล์ = 404 · header กันเบราว์เซอร์เดาชนิดไฟล์และกันแคช
4. ลบผู้สมัครแล้วไฟล์หายไปด้วย (ข้อมูลส่วนบุคคล)
"""
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import resume_ingest
from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.resume_ingest import Verdict, admit_resume

TEXT = "Somchai Jaidee Python developer five years FastAPI PostgreSQL Docker Kubernetes " * 4


def make_pdf(text: str = TEXT) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), text[:90], fontsize=9)
    page.insert_text((40, 80), text[90:180], fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def job():
    with get_conn() as conn:
        jid = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES ('เทสไฟล์ต้นฉบับ (ลบได้)', 'x') RETURNING id"
        ).fetchone()["id"]
        conn.commit()
    yield str(jid)
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (jid,))
        conn.commit()


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


def admit(job_id, content, filename="ใบสมัคร สมชาย.pdf", seen=None, existing=None):
    with get_conn() as conn:
        verdict, cid = admit_resume(
            conn, job_id, filename, content, seen if seen is not None else set(), existing or set()
        )
        conn.commit()
    return verdict, cid


def stored(cid):
    with get_conn() as conn:
        return conn.execute(
            "SELECT pdf_bytes, filename, size_bytes FROM candidate_files WHERE candidate_id = %s",
            (cid,),
        ).fetchone()


class TestStore:
    def test_ไฟล์ที่รับจริงถูกเก็บครบทุกไบต์(self, job):
        pdf = make_pdf()
        verdict, cid = admit(job, pdf)
        assert verdict is Verdict.ACCEPTED
        row = stored(cid)
        assert bytes(row["pdf_bytes"]) == pdf
        assert row["size_bytes"] == len(pdf)
        assert row["filename"] == "ใบสมัคร สมชาย.pdf"

    def test_ไฟล์ซ้ำไม่ถูกเก็บซ้ำ(self, job):
        pdf = make_pdf()
        admit(job, pdf)
        with get_conn() as conn:
            existing = resume_ingest.existing_hashes_for_job(conn, job)
        verdict, cid = admit(job, pdf, existing=existing)
        assert verdict is Verdict.DUPLICATE and cid is None
        with get_conn() as conn:
            n = conn.execute(
                """SELECT count(*) AS n FROM candidate_files f
                     JOIN candidates c ON c.id = f.candidate_id WHERE c.job_id = %s""",
                (job,),
            ).fetchone()["n"]
        assert n == 1

    def test_ไฟล์อ่านไม่ออกไม่ถูกเก็บ(self, job, monkeypatch):
        calls = []
        monkeypatch.setattr(resume_ingest, "save_resume_file", lambda *a: calls.append(a))
        verdict, _ = admit(job, make_pdf(text=""))
        assert verdict is Verdict.UNREADABLE
        assert calls == []

    def test_เก็บไฟล์พังแล้วใบสมัครยังเข้าระบบ_และไม่พาทั้งชุดหาย(self, job, monkeypatch):
        """ส่ง candidate_id ที่ไม่ใช่ UUID ให้ INSERT พังจริงใน DB — พิสูจน์ว่า SAVEPOINT ย้อนแค่
        ส่วนของไฟล์ ไม่ทำให้ทรานแซกชันของทั้งชุดอัปโหลด abort."""
        real = resume_ingest.save_resume_file

        def broken(conn, cid, content, filename):
            return real(conn, "ไม่ใช่-uuid", content, filename)  # INSERT error จริงใน DB

        monkeypatch.setattr(resume_ingest, "save_resume_file", broken)
        with get_conn() as conn:
            seen: set[str] = set()
            v1, c1 = admit_resume(conn, job, "a.pdf", make_pdf(), seen, set())
            v2, c2 = admit_resume(conn, job, "b.pdf", make_pdf("Another " + TEXT), seen, set())
            conn.commit()
        assert (v1, v2) == (Verdict.ACCEPTED, Verdict.ACCEPTED)
        with get_conn() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM candidates WHERE id = ANY(%s)", ([c1, c2],)
            ).fetchone()["n"]
        assert n == 2
        assert stored(c1) is None

    def test_ลบผู้สมัครแล้วไฟล์หายไปด้วย(self, job):
        _, cid = admit(job, make_pdf())
        with get_conn() as conn:
            conn.execute("DELETE FROM candidates WHERE id = %s", (cid,))
            conn.commit()
        assert stored(cid) is None


class TestEndpoint:
    def test_ต้องล็อกอินก่อน(self, job):
        _, cid = admit(job, make_pdf())
        assert TestClient(app).get(f"/api/v1/candidates/{cid}/resume.pdf").status_code == 401

    def test_คืนไฟล์ต้นฉบับพร้อม_header_ที่ปลอดภัย(self, client, job):
        pdf = make_pdf()
        _, cid = admit(job, pdf)
        res = client.get(f"/api/v1/candidates/{cid}/resume.pdf")
        assert res.status_code == 200
        assert res.content == pdf
        assert res.headers["content-type"] == "application/pdf"
        assert res.headers["x-content-type-options"] == "nosniff"
        assert "no-store" in res.headers["cache-control"]
        disp = res.headers["content-disposition"]
        assert disp.startswith("inline")
        assert "filename*=UTF-8''" in disp  # ชื่อไทยเข้ารหัสแล้ว header ไม่พัง

    def test_ไม่มีไฟล์คืน_404(self, client, job):
        with get_conn() as conn:
            cid = conn.execute(
                "INSERT INTO candidates (job_id, full_name) VALUES (%s, 'ผู้สมัครเก่า') RETURNING id",
                (job,),
            ).fetchone()["id"]
            conn.commit()
        assert client.get(f"/api/v1/candidates/{cid}/resume.pdf").status_code == 404

    def test_รายละเอียดผู้สมัครบอกว่ามีไฟล์ไหม(self, client, job):
        _, with_file = admit(job, make_pdf())
        with get_conn() as conn:
            without = conn.execute(
                "INSERT INTO candidates (job_id, full_name) VALUES (%s, 'ผู้สมัครเก่า') RETURNING id",
                (job,),
            ).fetchone()["id"]
            conn.commit()
        assert client.get(f"/api/v1/candidates/{with_file}").json()["has_resume_file"] is True
        assert client.get(f"/api/v1/candidates/{without}").json()["has_resume_file"] is False
