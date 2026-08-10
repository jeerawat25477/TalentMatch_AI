"""ประสานการรันกราฟ + เขียนผลลง DB (นอกโหนด เพื่อคงให้โหนดเป็น pure transformer).

- process_candidate: รันตั้งแต่ต้นจนถึงจุดตัดสิน แล้วเขียน evaluation; auto-resume ถ้า fit>70
- resume_after_decision: หลัง HR ตัดสิน → เขียน state แล้วรันต่อจาก interrupt (ไม่ rerun จากต้น)
"""
import logging
import os
import threading

from psycopg.types.json import Json

from app.agents.bands import should_auto_advance
from app.agents.graph import get_graph
from app.database import get_conn
from app.vectors import index_candidate

log = logging.getLogger(__name__)

# จำกัดจำนวนผู้สมัครที่รันกราฟพร้อมกันทั้งโปรเซส — กันหลาย upload request ยิง LLM
# ชนกันจนทะลุเพดาน RPM ของ Gemini free tier (backoff ใน llm.py รับ burst เล็ก ๆ ต่ออีกชั้น)
_MAX_CONCURRENCY = int(os.getenv("GRAPH_MAX_CONCURRENCY", "2"))
_gate = threading.BoundedSemaphore(_MAX_CONCURRENCY)

# ทะเบียนผู้สมัครที่กราฟกำลังทำงานอยู่ (รวมคนที่ยังรอคิว gate) — ให้ DELETE /jobs/{id}
# ปฏิเสธการลบระหว่างประมวลผล ไม่งั้น _persist_* จะเขียนลงแถวที่ cascade ลบไปแล้ว
# หมายเหตุ: เป็น state ในโปรเซส เหมือน rate limit ล็อกอิน — ใช้ได้กับ backend เรพลิกาเดียว
_active: set[str] = set()
_active_lock = threading.Lock()


def active_candidates() -> frozenset[str]:
    """สำเนาเซ็ต candidate_id ที่กำลังรันกราฟอยู่ ณ ขณะนี้."""
    with _active_lock:
        return frozenset(_active)


def reserve_candidates(candidate_ids: list[str]) -> None:
    """จองทั้งชุดตั้งแต่ก่อนเริ่มลูป — ไม่ใช่ทีละคนตอนถึงคิว.

    ถ้าจองทีละคน คนที่ 3-20 ของ batch จะยังไม่อยู่ในทะเบียนระหว่างที่คนแรกรัน
    ทำให้ทั้งการ์ดกันลบและป้าย "ค้าง" เข้าใจผิดว่าพวกเขาตายไปแล้ว
    """
    with _active_lock:
        _active.update(str(c) for c in candidate_ids)


def release_candidate(candidate_id: str) -> None:
    """ปลดจองหนึ่งคน (idempotent) — เรียกซ้ำได้ปลอดภัย."""
    with _active_lock:
        _active.discard(str(candidate_id))


def _config(candidate_id: str) -> dict:
    """config ต่อการรันกราฟ — thread_id ผูก checkpointer + ป้าย trace ให้ LangSmith.

    run_name/tags/metadata ทำให้หา trace ของผู้สมัครแต่ละคนใน LangSmith เจอง่าย
    (ไม่มีผลถ้าปิด tracing) และไม่กระทบ get_state/update_state ที่ใช้ config ตัวเดียวกัน
    """
    cid = str(candidate_id)
    return {
        "configurable": {"thread_id": cid},
        "run_name": f"screen-candidate-{cid[:8]}",
        "tags": ["talentmatch", "screening"],
        "metadata": {"candidate_id": cid},
    }


def _persist_evaluation(
    job_id: str, candidate_id: str, evaluation: dict, profile: dict, similar: list | None = None
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE candidates
               SET full_name = COALESCE(NULLIF(%s, ''), full_name),
                   email = %s,
                   parsed_resume = %s
               WHERE id = %s""",
            (profile.get("full_name", ""), profile.get("email"), Json(profile), candidate_id),
        )
        # หนึ่งผลประเมินต่อผู้สมัคร: ลบของเดิม (ถ้ามี) ก่อนใส่ใหม่
        conn.execute("DELETE FROM evaluations WHERE candidate_id = %s", (candidate_id,))
        conn.execute(
            """INSERT INTO evaluations
               (job_id, candidate_id, fit_score, gap_analysis, audit_status, audit_log,
                similar_candidates)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                job_id,
                candidate_id,
                evaluation["fit_score"],
                Json(evaluation.get("gaps")),
                evaluation.get("audit_status", "passed"),
                evaluation.get("audit_log", ""),
                Json(similar) if similar else None,
            ),
        )
        conn.commit()


def _persist_outputs(candidate_id: str, state: dict) -> None:
    cid = str(candidate_id)
    plan = (state.get("interview_plans") or {}).get(cid)
    draft = (state.get("email_drafts") or {}).get(cid)

    # state สะสมข้ามรอบ: ถ้า HR กลับคำเป็นปฏิเสธ เส้นทาง reject จะไม่แวะ planner
    # ทำให้ interview_plans ของรอบก่อนยังค้างใน state — ต้องล้างทิ้ง ไม่งั้นหน้าเว็บจะโชว์
    # คำถามสัมภาษณ์คู่กับอีเมลปฏิเสธ
    if (draft or {}).get("kind") == "rejection":
        plan = None

    with get_conn() as conn:
        conn.execute(
            """UPDATE evaluations
               SET interview_plan = %s, email_draft = %s
               WHERE candidate_id = %s""",
            (Json(plan) if plan else None, Json(draft) if draft else None, candidate_id),
        )
        conn.commit()


def process_candidate(
    job_id: str, candidate_id: str, raw_jd: str, analyzed_jd: dict | None, resume_text: str
) -> None:
    """รันกราฟสำหรับผู้สมัครหนึ่งคน (thread_id = candidate_id)."""
    reserve_candidates([candidate_id])  # เผื่อถูกเรียกเดี่ยว ๆ (เช่น reprocess) ที่ยังไม่ได้จอง
    try:
        with _gate:  # จำกัด concurrency กันยิง LLM ทะลุเพดาน RPM
            _process_candidate_locked(job_id, candidate_id, raw_jd, analyzed_jd, resume_text)
    finally:
        release_candidate(candidate_id)


def _process_candidate_locked(
    job_id: str, candidate_id: str, raw_jd: str, analyzed_jd: dict | None, resume_text: str
) -> None:
    graph = get_graph()
    config = _config(candidate_id)
    initial = {
        "raw_jd": raw_jd,
        "analyzed_jd": analyzed_jd,
        "raw_resumes": [
            {"candidate_id": str(candidate_id), "filename": "", "content": resume_text}
        ],
        "parsed_resumes": [],
        "evaluations": [],
        "hr_decision": {},
        "hr_notes": {},
        "interview_plans": {},
        "email_drafts": {},
        "similar_candidates": {},
    }
    state = graph.invoke(initial, config)
    evaluation = state["evaluations"][0]
    similar = (state.get("similar_candidates") or {}).get(str(candidate_id)) or []
    _persist_evaluation(job_id, candidate_id, evaluation, state["parsed_resumes"][0], similar)

    # เก็บเวกเตอร์ไว้ค้นหาผู้สมัครเก่าภายหลัง — ล้มแล้วต้องไม่ทำให้กราฟพัง
    # (เป็นฟีเจอร์เสริม ไม่ใช่ส่วนหนึ่งของการให้คะแนน)
    try:
        index_candidate(str(candidate_id), resume_text)
    except Exception as exc:  # noqa: BLE001
        log.warning("index เวกเตอร์ของผู้สมัคร %s ไม่สำเร็จ: %s", candidate_id, exc)

    snapshot = graph.get_state(config)
    if snapshot.next:
        # พักก่อน interview_planner: auto-resume ถ้าคะแนนสูง, ไม่งั้นรอ HR
        if should_auto_advance(evaluation["fit_score"]):
            state = graph.invoke(None, config)
            _persist_outputs(candidate_id, state)
        else:
            log.info("candidate %s (fit=%s) รอ HR ตัดสิน", candidate_id, evaluation["fit_score"])
    else:
        # จบแล้ว (เส้นทางปฏิเสธ fit<50) — มีอีเมลปฏิเสธพร้อมเขียนลง DB
        _persist_outputs(candidate_id, state)


def get_graph_status(candidate_id: str) -> str:
    """สถานะกราฟของผู้สมัคร — ให้ frontend บอก HR ได้ว่าการกดปุ่มจะทำอะไร.

    - "awaiting_hr" : ค้างอยู่ที่ interrupt รอคำตัดสิน (กดแล้วเดินต่อทันที)
    - "completed"   : จบแล้ว (กดแล้วจะ "ตัดสินใหม่" — สร้างคำถาม/อีเมลทับของเดิม)
    - "processing"  : ยังไม่มี checkpoint (กราฟกำลังรันหรือยังไม่เริ่ม)
    """
    try:
        snapshot = get_graph().get_state(_config(candidate_id))
    except Exception as exc:  # noqa: BLE001 — สถานะเป็นข้อมูลเสริม ห้ามทำให้ API ล้ม
        log.warning("อ่านสถานะกราฟของ %s ไม่ได้: %s", candidate_id, exc)
        return "processing"
    if snapshot.next:
        return "awaiting_hr"
    return "completed" if snapshot.created_at else "processing"


def _drive_to_end(graph, config, max_steps: int = 4) -> dict:
    """เดินกราฟจนจบ — invoke ซ้ำเมื่อโดน interrupt_before ขวางระหว่างทาง.

    ต้องวนเพราะกรณี "ย้อน state" ด้านล่างจะเดินมาถึง interview_planner แบบสด ๆ
    (ไม่ใช่การ resume) interrupt_before จึงทำงานอีกรอบ ต้อง invoke ซ้ำเพื่อผ่านไป
    """
    state: dict = {}
    for _ in range(max_steps):
        state = graph.invoke(None, config)
        if not graph.get_state(config).next:
            return state
    log.warning("กราฟของ %s ยังไม่จบหลังเดิน %s ครั้ง", config, max_steps)
    return state


def resume_after_decision(candidate_id: str, decision: str, notes: str | None) -> None:
    """หลัง HR ตัดสิน: เขียน hr_decision ลง state แล้วเดินกราฟต่อ (ไม่ rerun จากต้น).

    สองสถานการณ์:
    1. กราฟค้างอยู่ที่ interrupt (คะแนน 50–70) — เขียนคำตัดสินแล้วเดินต่อตามปกติ
    2. **กราฟจบไปแล้ว** (คะแนน >70 ที่ auto-advance ไปแล้ว หรือ <50 ที่ถูกปฏิเสธอัตโนมัติ)
       เดิมโค้ดนี้ update_state แล้ว invoke(None) เฉย ๆ ซึ่ง **ไม่มีผลอะไรเลย** เพราะ
       ไม่มีโหนดค้างให้รัน — API ตอบ 200 และหน้าเว็บบอกว่าสำเร็จ ทั้งที่ไม่มีอะไรเปลี่ยน
       ทำให้ HR กู้คนที่ AI ตัดทิ้งผิดไม่ได้เลย
       แก้โดยย้อน state กลับไปเป็น "เพิ่งจบ bias_auditor" (as_node) เพื่อให้ route_candidates
       ตัดสินใหม่โดยมี hr_decision อยู่ในมือ แล้วเดินต่อจากตรงนั้น
    """
    graph = get_graph()
    config = _config(candidate_id)
    cid = str(candidate_id)
    values = {"hr_decision": {cid: decision}, "hr_notes": {cid: notes or ""}}

    if graph.get_state(config).next:
        graph.update_state(config, values)
    else:
        log.info("กราฟของ %s จบไปแล้ว — ย้อนกลับไปที่ router เพื่อรับคำตัดสินของ HR", cid)
        graph.update_state(config, values, as_node="bias_auditor")

    state = _drive_to_end(graph, config)
    _persist_outputs(candidate_id, state)
