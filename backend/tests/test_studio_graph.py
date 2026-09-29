"""กราฟของ LangGraph Studio ต้องเป็นกราฟเดียวกับระบบจริง — ไม่งั้น Studio โชว์แผนภาพที่ระบบไม่ได้ใช้."""
from app.agents import graph as graph_mod
from app.agents import studio
from app.agents.runner import initial_state
from app.agents.state import HRSystemState
from scripts.studio_input import build


class _FakeCompiled:
    def __init__(self, kwargs):
        self.kwargs = kwargs


def test_studio_graph_has_same_nodes_and_edges_as_real_graph():
    real = graph_mod.build_graph().compile().get_graph()
    mine = studio.graph.get_graph()
    assert set(mine.nodes) == set(real.nodes)
    edges = lambda g: {(e.source, e.target, e.conditional) for e in g.edges}  # noqa: E731
    assert edges(mine) == edges(real)


def test_studio_pauses_where_production_pauses(monkeypatch):
    """จุดพักรอ HR ต้องตรงกับ get_graph() — อ่านจากการ compile จริงของ get_graph."""
    captured = {}

    class _Builder:
        def compile(self, **kwargs):
            captured.update(kwargs)
            return _FakeCompiled(kwargs)

    monkeypatch.setattr(graph_mod, "build_graph", lambda: _Builder())
    monkeypatch.setattr(graph_mod, "get_checkpointer", lambda: object())
    monkeypatch.setattr(graph_mod, "_compiled", None)
    graph_mod.get_graph()
    assert captured["interrupt_before"] == studio.INTERRUPT_BEFORE


def test_studio_graph_has_no_checkpointer():
    """langgraph dev มีที่เก็บ state ของตัวเอง — ผูก PostgresSaver จะปนกับ thread ผู้สมัครจริง."""
    assert studio.graph.checkpointer is None


def test_initial_state_covers_every_state_field():
    state = initial_state("c1", "JD", {"required_skills": []}, "resume", {"status": "passed"})
    assert set(state) == set(HRSystemState.__annotations__)
    assert state["raw_resumes"][0] == {"candidate_id": "c1", "filename": "", "content": "resume"}


def test_studio_input_uses_the_same_state_builder():
    row = {"raw_text": "JD", "parsed_criteria": {"required_skills": ["Python"]},
           "raw_resume_text": None, "jd_audit": None}
    out = build(row, "c9")
    assert out == initial_state("c9", "JD", {"required_skills": ["Python"]}, "", None)
