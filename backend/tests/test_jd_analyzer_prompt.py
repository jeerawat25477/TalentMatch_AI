"""jd_analyzer (สัญญากับ structured_invoke) + คำเตือนเกณฑ์บน JobOut."""
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.agents.models import JobRequirement
from app.agents.nodes import jd_analyzer
from app.schemas import JobOut


def test_prompt_formats_without_stray_braces():
    text = jd_analyzer.PROMPT.format(raw_jd="JD_MARKER")
    assert "JD_MARKER" in text
    assert "{" not in text and "}" not in text


def test_analyze_jd_sends_prompt_once_and_returns_dump():
    fake = JobRequirement(job_title="AI Engineer", required_skills=["Python"], preferred_skills=["PyTorch"])
    with patch.object(jd_analyzer, "structured_invoke", return_value=fake) as inv:
        out = jd_analyzer.analyze_jd({"raw_jd": "Python required; PyTorch or TensorFlow", "analyzed_jd": None})
    inv.assert_called_once()
    prompt, model = inv.call_args.args
    assert model is JobRequirement
    assert "PyTorch or TensorFlow" in prompt
    assert out == {"analyzed_jd": fake.model_dump()}


def test_analyze_jd_skips_llm_when_already_analyzed():
    with patch.object(jd_analyzer, "structured_invoke") as inv:
        assert jd_analyzer.analyze_jd({"raw_jd": "x", "analyzed_jd": {"job_title": "x"}}) == {}
    inv.assert_not_called()


def _job(criteria):
    return JobOut(
        id=uuid4(),
        title="t",
        raw_text="r",
        parsed_criteria=criteria,
        created_at=datetime.now(timezone.utc),
    )


def test_job_warnings_empty_without_criteria():
    assert _job(None).criteria_warnings == []


def test_job_warns_when_only_preferred():
    job = _job({"required_skills": [], "preferred_skills": ["PyTorch", "TensorFlow"]})
    assert len(job.criteria_warnings) == 1
    assert "มีแค่ทักษะที่อยากได้" in job.criteria_warnings[0]
    # ต้องออกไปกับ response ด้วย ไม่ใช่แค่ property ใน Python
    assert job.model_dump(mode="json")["criteria_warnings"] == job.criteria_warnings


def test_job_warns_when_required_bloated():
    job = _job({"required_skills": [f"Skill{i}" for i in range(20)], "preferred_skills": []})
    assert any("20 ข้อ" in w for w in job.criteria_warnings)


def test_job_no_warning_for_healthy_criteria():
    job = _job({"required_skills": ["Python", "FastAPI"], "preferred_skills": ["Docker"]})
    assert job.criteria_warnings == []
