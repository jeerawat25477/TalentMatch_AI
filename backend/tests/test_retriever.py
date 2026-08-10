"""เทส retrieval agent (RAG) — เน้น toggle + การส่ง query/exclude ให้ถูก (ไม่เรียก embedding จริง)."""
from app.agents.nodes import retriever

STATE = {
    "parsed_resumes": [{"candidate_id": "cand-1", "skills": ["Python", "FastAPI", "Docker"]}],
    "similar_candidates": {},
}


def test_disabled_is_noop(monkeypatch):
    """RAG_ENABLED ไม่ตั้ง → คืน similar ว่าง โดยไม่แตะ vectors.search."""
    monkeypatch.delenv("RAG_ENABLED", raising=False)
    called = {"n": 0}
    monkeypatch.setattr(retriever, "search", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    out = retriever.retrieve_similar(STATE)
    assert out == {"similar_candidates": {"cand-1": []}}
    assert called["n"] == 0  # ต้องไม่เรียก search เลย


def test_enabled_passes_query_and_excludes_self(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "true")
    captured = {}

    def fake_search(query, limit=10, exclude_candidate_id=None):
        captured["query"] = query
        captured["limit"] = limit
        captured["exclude"] = exclude_candidate_id
        return [
            {"id": "cand-9", "full_name": "Somchai", "job_title": "Dev",
             "fit_score": 100, "distance": 0.12345},
        ]

    monkeypatch.setattr(retriever, "search", fake_search)
    out = retriever.retrieve_similar(STATE)

    # query สร้างจากทักษะ + กันตัวเองออก
    assert "Python" in captured["query"] and "Docker" in captured["query"]
    assert captured["exclude"] == "cand-1"
    hit = out["similar_candidates"]["cand-1"][0]
    assert hit["full_name"] == "Somchai"
    assert hit["distance"] == 0.1235  # ปัดเป็น 4 ตำแหน่ง


def test_enabled_no_skills_returns_empty(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setattr(retriever, "search", lambda *a, **k: 1 / 0)  # ต้องไม่ถูกเรียก
    out = retriever.retrieve_similar(
        {"parsed_resumes": [{"candidate_id": "c2", "skills": []}]}
    )
    assert out == {"similar_candidates": {"c2": []}}


def test_search_failure_is_swallowed(monkeypatch):
    """search พังต้องไม่ทำให้กราฟล้ม — คืน similar ว่างแทน."""
    monkeypatch.setenv("RAG_ENABLED", "true")

    def boom(*a, **k):
        raise RuntimeError("embedding quota exhausted")

    monkeypatch.setattr(retriever, "search", boom)
    out = retriever.retrieve_similar(STATE)
    assert out == {"similar_candidates": {"cand-1": []}}
