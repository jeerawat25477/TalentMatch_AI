"""สคริปต์เติม jobs.jd_audit ให้ตำแหน่งเก่า — ไม่ต่อ DB ไม่เรียก LLM จริง."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.agents.models import BiasAudit  # noqa: E402
from backfill_jd_audit import plan  # noqa: E402


def _row(title, text, audit=None):
    return {"id": title, "title": title, "raw_text": text, "jd_audit": audit,
            "parsed_criteria": {"required_skills": ["Python"], "preferred_skills": []}}


def _boom(*a, **k):
    raise AssertionError("ดีฟอลต์ต้องไม่เรียก LLM")


def test_ดีฟอลต์ใช้กฎอย่างเดียวไม่เรียก_llm():
    out = plan([_row("A", "เพศชาย Python"), _row("B", "Python")], with_llm=False, llm=_boom)
    assert [(t, a["status"], a["llm_checked"]) for _, t, a in out] == [
        ("A", "flagged", False), ("B", "passed", False),
    ]


def test_ข้ามตำแหน่งที่มีผลตรวจแล้ว():
    out = plan([_row("A", "เพศชาย", audit={"status": "passed"})], with_llm=False, llm=_boom)
    assert out == []


def test_with_llm_เรียกหนึ่งครั้งต่อตำแหน่ง():
    calls = []

    def fake(*args):
        calls.append(args)
        return BiasAudit(is_biased=False, audit_status="passed", audit_log="ไม่พบ")

    out = plan([_row("A", "Python"), _row("B", "Python")], with_llm=True, llm=fake)
    assert len(calls) == 2 and all(a["llm_checked"] for _, _, a in out)


def test_llm_ล้มตำแหน่งเดียวไม่หยุดทั้งชุด():
    def flaky(text, *rest):
        if "พัง" in text:
            raise RuntimeError("quota")
        return BiasAudit(is_biased=False, audit_status="passed", audit_log="ไม่พบ")

    out = plan([_row("A", "พัง เพศชาย"), _row("B", "Python")], with_llm=True, llm=flaky)
    assert [(a["status"], a["llm_checked"]) for _, _, a in out] == [
        ("flagged", False), ("passed", True),
    ]
