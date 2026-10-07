"""สูตรวัดผลของ scripts/eval_search.py — ตัวเลขฐานของหน้าค้นหามาจากสองฟังก์ชันนี้."""
from scripts.eval_search import CASES, first_relevant_rank, summarize


def test_rank_counts_any_email_of_a_person():
    # คนที่รวมจากหลายไฟล์มีหลายอีเมล — ตรงอีเมลไหนก็นับว่าใช่
    people = [{"x@a.com"}, {"old@b.com", "me@b.com"}, set()]
    assert first_relevant_rank(people, {"me@b.com"}) == 2


def test_rank_none_when_not_found():
    assert first_relevant_rank([{"x@a.com"}], {"y@a.com"}) is None
    assert first_relevant_rank([], {"y@a.com"}) is None


def test_summarize():
    s = summarize([1, 2, None, 4])
    assert s["n"] == 4
    assert s["hit1"] == 0.25
    assert s["hit3"] == 0.5
    assert abs(s["mrr"] - (1 + 0.5 + 0.25) / 4) < 1e-9


def test_summarize_empty():
    assert summarize([])["mrr"] == 0.0


def test_cases_are_well_formed():
    queries = [q for q, _, _ in CASES]
    assert len(queries) == len(set(queries)), "คำค้นซ้ำทำให้ค่าเฉลี่ยเอียง"
    for _, _, relevant in CASES:
        assert all(e == e.strip().lower() for e in relevant), "อีเมลต้องเป็นตัวเล็กไม่มีช่องว่าง"
