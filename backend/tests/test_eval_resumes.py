"""สูตรของ scripts/eval_resumes.py — ตัวเลขวัดผลตามบรีฟข้อ 7 มาจากฟังก์ชันเหล่านี้."""
from scripts.eval_resumes import CASES, jaccard, same_name, skill_scores, strip_personal


def test_recall_and_precision_use_system_matching():
    sc = skill_scores(["NodeJS", "Python", "Cobol"], must=["Node.js", "Python", "Go"], ok=[])
    assert sc["recall"] == 2 / 3 and sc["missed"] == ["Go"]
    assert sc["precision"] == 2 / 3 and sc["extra"] == ["Cobol"]


def test_acceptable_extras_are_not_penalised_nor_required():
    sc = skill_scores(["Python", "Machine Learning"], must=["Python"], ok=["Machine Learning"])
    assert sc["recall"] == 1.0 and sc["precision"] == 1.0


def test_empty_parse_scores_zero_precision():
    assert skill_scores([], must=["Python"], ok=[])["precision"] == 0.0


def test_same_name_ignores_case_and_spacing():
    assert same_name(" natthapong  SRISUK", "Natthapong Srisuk")
    assert not same_name("Natthapong", "Natthapong Srisuk")


def test_strip_personal_removes_only_personal_lines():
    text = "ธนกฤต ใจดี\nเพศ: ชาย · อายุ: 22 ปี\nศาสนา: พุทธ\nPython, SQL"
    assert strip_personal(text) == "ธนกฤต ใจดี\nPython, SQL"


def test_jaccard():
    assert jaccard(["A", "b"], ["a", "B"]) == 1.0
    assert jaccard(["a"], ["b"]) == 0.0


def test_cases_cover_brief_variety():
    assert len(CASES) == 9  # + ไฟล์สแกน = 10 แบบ ตามบรีฟ (10–20)
    for f, (name, targets, must, ok, _) in CASES.items():
        assert name and targets and must, f
        assert not set(must) & set(ok), f"{f}: ทักษะอยู่ทั้งสองช่อง"


def test_live_target_calls_real_parser_with_file_text():
    from scripts.eval_resumes import live_target

    seen = []

    def fake_parse(state):
        seen.append(state["raw_resumes"][0]["content"])
        return {"parsed_resumes": [{"full_name": "A", "skills": ["Python"]}]}

    target = live_target({"a.pdf": "ข้อความ A", "b.pdf": "ข้อความ B"}, parse=fake_parse)
    assert target({"file": "b.pdf"}) == {"profile": {"full_name": "A", "skills": ["Python"]}}
    assert seen == ["ข้อความ B"]


def test_evaluators_score_live_output_like_replay():
    from types import SimpleNamespace

    from scripts.eval_resumes import ev_name, ev_precision, ev_recall

    run = SimpleNamespace(outputs={"profile": {"full_name": "Somchai Jaidee", "skills": ["Python", "Docker"]}})
    ex = SimpleNamespace(outputs={"name": "somchai  jaidee", "must": ["Python", "SQL"], "ok": ["Docker"]})
    assert ev_recall(run, ex) == {"key": "skill_recall", "score": 0.5}
    assert ev_precision(run, ex) == {"key": "skill_precision", "score": 1.0}
    assert ev_name(run, ex) == {"key": "name_correct", "score": 1}
