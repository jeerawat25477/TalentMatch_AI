"""รูปโปรไฟล์จากเรซูเม่ + สวิตช์แสดงรูปหน้าคัดกรอง — ไม่ยิง LLM.

รัน: docker compose exec backend python -m pytest tests/test_candidate_photo.py -v

สิ่งที่เทสชุดนี้กัน:
1. heuristic เลือกรูปถูก — ตัดรูปเล็ก ตัดแถบยาว เลือกรูปใหญ่สุด ไม่มีรูปคืน None
2. **ดึงรูปพังแล้วการรับไฟล์ต้องไม่พัง** — รูปเป็นของแถม ใบสมัครสำคัญกว่า
3. ไม่มีรูป → 404 (หน้าเว็บใช้เป็นสัญญาณกลับไปตัวอักษรย่อ) และต้องล็อกอินก่อน
4. สวิตช์ดีฟอลต์ปิดเสมอ และบูตใหม่ต้องไม่ทับค่าที่ HR เปิดไว้
"""
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import resume_ingest
from app.auth import get_current_user
from app.database import SCHEMA_PATH, get_conn
from app.main import app
from app.resume_ingest import Verdict, admit_resume
from app.resume_photo import extract_candidate_photo, is_photo_candidate
from app.routers.settings import SCREENING_PHOTOS_DEFAULT, SCREENING_PHOTOS_KEY
from app.settings import get_setting, invalidate, set_setting

SETTING_URL = "/api/v1/settings/screening-photos"
TEXT = "Somchai Jaidee Python developer five years FastAPI PostgreSQL Docker Kubernetes " * 4


def make_pdf(sizes: list[tuple[int, int]], text: str = TEXT) -> bytes:
    """PDF หนึ่งหน้า มีข้อความพอผ่านด่านอ่านไม่ออก + รูปสีทึบตามขนาดพิกเซลที่ให้."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), text[:90], fontsize=9)
    page.insert_text((40, 80), text[90:180], fontsize=9)
    y = 100
    for i, (w, h) in enumerate(sizes):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
        pix.clear_with(40 * (i + 1) % 255)
        page.insert_image(pymupdf.Rect(40, y, 40 + w / 4, y + h / 4), pixmap=pix)
        y += h / 4 + 10
    data = doc.tobytes()
    doc.close()
    return data


def dims(image: bytes) -> tuple[int, int]:
    pix = pymupdf.Pixmap(image)
    return pix.width, pix.height


class TestHeuristic:
    @pytest.mark.parametrize("w,h", [(200, 200), (300, 400), (240, 200), (80, 80)])
    def test_รูปขนาดคนรับ(self, w, h):
        assert is_photo_candidate(w, h)

    @pytest.mark.parametrize("w,h", [(40, 40), (79, 100), (100, 79)])
    def test_รูปเล็กเกินไปตัดทิ้ง(self, w, h):
        assert not is_photo_candidate(w, h)

    @pytest.mark.parametrize("w,h", [(800, 100), (100, 400), (400, 200)])
    def test_แถบยาวหรือแคบผิดปกติตัดทิ้ง(self, w, h):
        assert not is_photo_candidate(w, h)

    def test_เลือกรูปที่ใหญ่ที่สุดในบรรดาที่ผ่านเกณฑ์(self):
        # ไอคอนเล็ก + แบนเนอร์ใหญ่กว่า + รูปคนสองขนาด → ต้องได้รูปคน 240x300
        pdf = make_pdf([(40, 40), (1200, 150), (120, 120), (240, 300)])
        image, mime = extract_candidate_photo(pdf)
        assert mime in ("image/png", "image/jpeg")
        assert dims(image) == (240, 300)

    def test_ไม่มีรูปเลยคืน_none(self):
        assert extract_candidate_photo(make_pdf([])) is None

    def test_มีแต่ไอคอนกับแถบคืน_none(self):
        assert extract_candidate_photo(make_pdf([(32, 32), (900, 60)])) is None

    def test_ภาพเต็มหน้าไม่นับเป็นรูปโปรไฟล์(self):
        """เรซูเม่สแกน/พื้นหลังเต็มหน้า สัดส่วน A4 (~0.71) ผ่านเกณฑ์สัดส่วน ต้องมีด่านแยก."""
        doc = pymupdf.open(stream=make_pdf([]), filetype="pdf")
        page = doc[0]
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 909, 1287), False)
        page.insert_image(page.rect, pixmap=pix, overlay=False)
        assert extract_candidate_photo(doc.tobytes()) is None

    def test_ภาพเต็มหน้าไม่บังรูปโปรไฟล์จริง(self):
        doc = pymupdf.open(stream=make_pdf([(200, 260)]), filetype="pdf")
        page = doc[0]
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 909, 1287), False)
        page.insert_image(page.rect, pixmap=pix, overlay=False)
        image, _ = extract_candidate_photo(doc.tobytes())
        assert dims(image) == (200, 260)

    def test_ดูเฉพาะหน้าแรก(self):
        doc = pymupdf.open(stream=make_pdf([]), filetype="pdf")
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
        page.insert_image(pymupdf.Rect(40, 40, 140, 140), pixmap=pix)
        assert extract_candidate_photo(doc.tobytes()) is None


@pytest.fixture
def job():
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสรูปผู้สมัคร (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        conn.commit()
    jid = str(row["id"])
    yield jid
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (jid,))  # cascade รูปไปด้วย
        conn.commit()


def admit(job_id: str, content: bytes):
    with get_conn() as conn:
        verdict, cid = admit_resume(conn, job_id, "resume.pdf", content, set(), set())
        conn.commit()
    return verdict, cid


def photo_row(cid):
    with get_conn() as conn:
        return conn.execute(
            "SELECT content_type FROM candidate_photos WHERE candidate_id = %s", (cid,)
        ).fetchone()


class TestAdmitResume:
    def test_รับไฟล์ที่มีรูปแล้วบันทึกรูป(self, job):
        verdict, cid = admit(job, make_pdf([(200, 240)]))
        assert verdict is Verdict.ACCEPTED
        assert photo_row(cid) is not None

    def test_ไม่มีรูปก็รับไฟล์ตามปกติ(self, job):
        verdict, cid = admit(job, make_pdf([]))
        assert verdict is Verdict.ACCEPTED
        assert photo_row(cid) is None

    def test_ดึงรูปพังแล้วการรับไฟล์ต้องไม่พัง(self, job, monkeypatch):
        def boom(_):
            raise RuntimeError("PDF เพี้ยน")

        monkeypatch.setattr(resume_ingest, "extract_candidate_photo", boom)
        verdict, cid = admit(job, make_pdf([(200, 240)]))
        assert verdict is Verdict.ACCEPTED
        with get_conn() as conn:
            assert conn.execute(
                "SELECT 1 FROM candidates WHERE id = %s", (cid,)
            ).fetchone()
        assert photo_row(cid) is None

    def test_insert_รูปพังต้องไม่ทำให้ทั้งชุดหาย(self, job, monkeypatch):
        """content_type ผิด CHECK → INSERT error ต้องย้อนแค่ savepoint ไม่ใช่ทั้งทรานแซกชัน."""
        monkeypatch.setattr(
            resume_ingest, "extract_candidate_photo", lambda _: (b"x", "image/gif")
        )
        with get_conn() as conn:
            seen: set[str] = set()
            v1, c1 = admit_resume(conn, job, "a.pdf", make_pdf([(200, 240)]), seen, set())
            v2, c2 = admit_resume(conn, job, "b.pdf", make_pdf([], "Another person " + TEXT), seen, set())
            conn.commit()
        assert (v1, v2) == (Verdict.ACCEPTED, Verdict.ACCEPTED)
        with get_conn() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM candidates WHERE id = ANY(%s)", ([c1, c2],)
            ).fetchone()["n"]
        assert n == 2

    def test_ไฟล์ซ้ำไม่พยายามดึงรูป(self, job, monkeypatch):
        pdf = make_pdf([(200, 240)])
        admit(job, pdf)
        calls = []
        monkeypatch.setattr(
            resume_ingest, "extract_candidate_photo", lambda b: calls.append(b)
        )
        with get_conn() as conn:
            existing = resume_ingest.existing_hashes_for_job(conn, job)
            verdict, _ = admit_resume(conn, job, "x.pdf", pdf, set(), existing)
        assert verdict is Verdict.DUPLICATE
        assert calls == []

    def test_ไฟล์อ่านไม่ออกไม่พยายามดึงรูป(self, job, monkeypatch):
        calls = []
        monkeypatch.setattr(
            resume_ingest, "extract_candidate_photo", lambda b: calls.append(b)
        )
        verdict, _ = admit(job, make_pdf([(200, 240)], text=""))
        assert verdict is Verdict.UNREADABLE
        assert calls == []


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestPhotoEndpoint:
    def test_ต้องล็อกอินก่อน(self, job):
        _, cid = admit(job, make_pdf([(200, 240)]))
        assert TestClient(app).get(f"/api/v1/candidates/{cid}/photo").status_code == 401

    def test_มีรูปคืนไบต์พร้อมชนิดไฟล์(self, client, job):
        _, cid = admit(job, make_pdf([(200, 240)]))
        res = client.get(f"/api/v1/candidates/{cid}/photo")
        assert res.status_code == 200
        assert res.headers["content-type"] in ("image/png", "image/jpeg")
        assert "no-store" in res.headers["cache-control"]
        assert dims(res.content) == (200, 240)

    def test_ไม่มีรูปคืน_404(self, client, job):
        _, cid = admit(job, make_pdf([]))
        assert client.get(f"/api/v1/candidates/{cid}/photo").status_code == 404

    def test_ไม่สนสวิตช์หน้าคัดกรอง(self, client, job):
        """หน้าพนักงานต้องเห็นรูปเสมอ — endpoint จึงห้ามดูสวิตช์."""
        _, cid = admit(job, make_pdf([(200, 240)]))
        before = dict(get_setting(SCREENING_PHOTOS_KEY, SCREENING_PHOTOS_DEFAULT))
        try:
            set_setting(SCREENING_PHOTOS_KEY, {"enabled": False})
            assert client.get(f"/api/v1/candidates/{cid}/photo").status_code == 200
        finally:
            set_setting(SCREENING_PHOTOS_KEY, before)


class TestScreeningPhotosSetting:
    @pytest.fixture(autouse=True)
    def restore(self):
        invalidate()
        before = dict(get_setting(SCREENING_PHOTOS_KEY, SCREENING_PHOTOS_DEFAULT))
        yield
        set_setting(SCREENING_PHOTOS_KEY, before)
        invalidate()

    def test_ต้องล็อกอินก่อน(self):
        anon = TestClient(app)
        assert anon.get(SETTING_URL).status_code == 401
        assert anon.patch(SETTING_URL, json={"enabled": True}).status_code == 401

    def test_seed_ใหม่ต้องเป็นปิดเสมอ(self, client):
        with get_conn() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = %s", (SCREENING_PHOTOS_KEY,))
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
        invalidate()
        assert client.get(SETTING_URL).json() == {"enabled": False}

    def test_บูตใหม่ต้องไม่ทับค่าที่_HR_เปิดไว้(self, client):
        client.patch(SETTING_URL, json={"enabled": True})
        with get_conn() as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
        invalidate()
        assert client.get(SETTING_URL).json() == {"enabled": True}

    def test_เปิดปิดแล้วเห็นผลทันที(self, client):
        assert client.patch(SETTING_URL, json={"enabled": True}).json()["enabled"] is True
        assert client.get(SETTING_URL).json()["enabled"] is True
        assert client.patch(SETTING_URL, json={"enabled": False}).json()["enabled"] is False
        assert client.get(SETTING_URL).json()["enabled"] is False

    def test_ค่าที่ไม่ใช่_bool_ต้อง_422(self, client):
        assert client.patch(SETTING_URL, json={}).status_code == 422
