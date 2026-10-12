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


# ---------- หน้า "ค้นหาผู้สมัคร": รวมคนเดียวกันเป็นแถวเดียว ----------
from datetime import datetime, timezone  # noqa: E402

from app.routers.candidates import group_people  # noqa: E402


def _app(id, *, sha=None, text=None, email=None, dist=None, day=1, parsed=True,
         name="A", job="J"):
    return {"id": id, "job_id": f"job-{id}", "job_title": job, "fit_score": 50,
            "created_at": datetime(2026, 9, day, tzinfo=timezone.utc), "full_name": name,
            "email": email, "sha": sha, "text_md5": text, "has_parsed": parsed,
            "distance": dist}


class TestGroupPeople:
    def test_same_file_applications_become_one_person(self):
        out = group_people([_app("1", sha="s", dist=0.3, day=1),
                            _app("2", sha="s", dist=None, day=5)])
        assert len(out) == 1
        p = out[0]
        assert p["merged_by"] == "same_file" and p["file_count"] == 1
        assert [a["candidate_id"] for a in p["applications"]] == ["2", "1"]  # ล่าสุดก่อน

    def test_same_email_different_files(self):
        out = group_people([_app("1", sha="a", email="x@y.com", dist=0.4),
                            _app("2", sha="b", email="X@Y.com ", dist=0.3)])
        assert len(out) == 1
        assert out[0]["merged_by"] == "same_email" and out[0]["file_count"] == 2
        assert out[0]["distance"] == 0.3  # ใช้ค่าที่ดีที่สุด

    def test_transitive_chain(self):
        # 1 ไฟล์ตรง 2, 2 อีเมลตรง 3 → คนเดียวกันทั้งสาม
        out = group_people([_app("1", sha="a", dist=0.2),
                            _app("2", sha="a", email="p@q.com"),
                            _app("3", sha="c", email="p@q.com")])
        assert len(out) == 1 and len(out[0]["applications"]) == 3

    def test_blank_email_does_not_merge(self):
        out = group_people([_app("1", sha="a", email="", dist=0.2),
                            _app("2", sha="b", email="", dist=0.3)])
        assert len(out) == 2

    def test_single_application_is_not_marked_merged(self):
        out = group_people([_app("1", sha="a", dist=0.2)])
        assert out[0]["merged_by"] is None and out[0]["file_count"] == 1

    def test_sorted_by_best_distance(self):
        out = group_people([_app("1", sha="a", dist=0.5, name="ไกล"),
                            _app("2", sha="b", dist=0.1, name="ใกล้")])
        assert [p["full_name"] for p in out] == ["ใกล้", "ไกล"]

    def test_name_comes_from_latest_parsed_application(self):
        # ใบล่าสุดยังไม่วิเคราะห์ (ชื่อยังเป็นชื่อไฟล์) → ใช้ชื่อจากใบที่ AI อ่านแล้ว
        out = group_people([_app("1", sha="a", dist=0.2, day=1, name="สมชาย ใจดี"),
                            _app("2", sha="a", day=9, parsed=False, name="resume_final.pdf")])
        assert out[0]["full_name"] == "สมชาย ใจดี"


class TestSearchPeopleEndpoint:
    def test_blank_query_400(self, client):
        assert client.get("/api/v1/candidates/search/people", params={"q": " "}).status_code == 400

    def test_vector_failure_503(self, client, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("quota")
        monkeypatch.setattr(candidates, "vector_search", boom)
        assert client.get("/api/v1/candidates/search/people", params={"q": "x"}).status_code == 503

    def test_no_hits_returns_empty_without_db(self, client, monkeypatch):
        monkeypatch.setattr(candidates, "vector_search", lambda q, limit=10: [])
        r = client.get("/api/v1/candidates/search/people", params={"q": "x"})
        assert r.status_code == 200 and r.json() == []


class TestMarkHitsDropsDeleted:
    """ผลคล้ายที่เก็บไว้ตอนวิเคราะห์อาจชี้ไปคนที่ถูกลบแล้ว — ต้องไม่โผล่เป็นลิงก์ 404."""

    def test_drops_rows_no_longer_in_db_and_marks_the_rest(self):
        from app.routers.candidates import mark_hits

        by_id = {"me": ME, "b": {"sha": "aaa", "text_md5": None, "email": None}}
        hits = [{"id": "gone", "full_name": "ลบแล้ว"}, {"id": "b", "full_name": "B"}, {"full_name": "ไม่มี id"}]
        assert mark_hits("me", hits, by_id) == [{"id": "b", "full_name": "B", "same_person": "same_file"}]

    def test_all_deleted_gives_empty_list(self):
        from app.routers.candidates import mark_hits

        assert mark_hits("me", [{"id": "gone"}], {"me": ME}) == []
