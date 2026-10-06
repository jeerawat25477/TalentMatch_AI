"""ป้าย "คนเดียวกัน / น่าจะคนเดียวกัน" ในการ์ดผู้สมัครที่โปรไฟล์คล้ายกัน.

ที่มา (2026-10-06): % ความคล้ายเทียบรายการทักษะกับเรซูเม่ทั้งฉบับ ไฟล์เดียวกันเป๊ะได้แค่ 78%
HR จึงดูไม่ออกว่าแถวนั้นคือคนเดิมที่เคยสมัครตำแหน่งอื่น · ไม่ใช้ AI ไม่แตะคะแนน
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.routers import candidates
from app.routers.candidates import same_person

ME = {"sha": "aaa", "text_md5": "t1", "email": "Jee@Example.com"}


class TestSamePerson:
    def test_same_file_by_sha(self):
        assert same_person(ME, {"sha": "aaa", "text_md5": "zz", "email": None}) == "same_file"

    def test_same_file_by_text_when_old_row_has_no_sha(self):
        # แถวที่เข้ามาก่อนมีคอลัมน์ sha256 เป็น NULL — ข้อความตรงทุกตัวอักษรก็คือไฟล์เดียวกัน
        assert same_person(ME, {"sha": None, "text_md5": "t1", "email": None}) == "same_file"

    def test_same_email_ignores_case_and_spaces(self):
        other = {"sha": "bbb", "text_md5": "t2", "email": "  jee@example.COM "}
        assert same_person(ME, other) == "same_email"

    def test_file_match_wins_over_email(self):
        assert same_person(ME, {"sha": "aaa", "email": "jee@example.com"}) == "same_file"

    def test_empty_values_never_match(self):
        # ว่างกับว่างห้ามนับว่าตรง — ไม่งั้นทุกคนที่ AI แกะอีเมลไม่ได้จะกลายเป็นคนเดียวกัน
        blank = {"sha": None, "text_md5": None, "email": ""}
        assert same_person(blank, dict(blank)) is None
        assert same_person({"email": "  "}, {"email": "  "}) is None

    def test_different_people(self):
        assert same_person(ME, {"sha": "ccc", "text_md5": "t3", "email": "x@y.com"}) is None


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestSearchRelativeTo:
    def _hits(self):
        return [{"id": "11111111-1111-1111-1111-111111111111", "full_name": "A",
                 "email": None, "job_id": None, "job_title": "Dev",
                 "fit_score": 60, "distance": 0.2}]

    def test_relative_to_excludes_self_and_marks_rows(self, client, monkeypatch):
        seen = {}

        def fake_search(q, limit=10, exclude_candidate_id=None):
            seen["exclude"] = exclude_candidate_id
            return self._hits()

        monkeypatch.setattr(candidates, "vector_search", fake_search)
        monkeypatch.setattr(
            candidates, "_mark_same_person",
            lambda cid, hits: [{**h, "same_person": "same_file"} for h in hits],
        )
        me = "22222222-2222-2222-2222-222222222222"
        r = client.get("/api/v1/candidates/search", params={"q": "python", "relative_to": me})
        assert r.status_code == 200
        assert seen["exclude"] == me
        assert r.json()[0]["same_person"] == "same_file"

    def test_without_relative_to_behaves_as_before(self, client, monkeypatch):
        seen = {}

        def fake_search(q, limit=10, exclude_candidate_id=None):
            seen["exclude"] = exclude_candidate_id
            return self._hits()

        def must_not_run(*a, **k):
            raise AssertionError("ไม่มี relative_to ต้องไม่แตะ DB เพื่อติดป้าย")

        monkeypatch.setattr(candidates, "vector_search", fake_search)
        monkeypatch.setattr(candidates, "_mark_same_person", must_not_run)
        r = client.get("/api/v1/candidates/search", params={"q": "python"})
        assert r.status_code == 200
        assert seen["exclude"] is None
        assert r.json()[0]["same_person"] is None
