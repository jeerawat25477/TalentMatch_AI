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
# ค่าเริ่มต้นเท่ากับจำนวนเธรดของ worker (QUEUE_WORKERS = 3) — ตั้งน้อยกว่านั้นเธรดที่เกินจะ
# ไปยืนรอหน้าประตูเปล่า ๆ · Tier 1 ของ Gemini ให้ 1,000 req/นาที เพดานจริงจึงไม่ใช่ตัวนี้
_MAX_CONCURRENCY = int(os.getenv("GRAPH_MAX_CONCURRENCY", "3"))
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


def _config(candidate_id: str, source: str = "upload") -> dict:
    """config ต่อการรันกราฟ — thread_id ผูก checkpointer + ป้าย trace ให้ LangSmith.

    run_name/tags/metadata ทำให้หา trace ของผู้สมัครแต่ละคนใน LangSmith เจอง่าย
    (ไม่มีผลถ้าปิด tracing) และไม่กระทบ get_state/update_state ที่ใช้ config ตัวเดียวกัน

    `source` บอกว่าผู้สมัครรายนี้เข้าระบบมาทางไหน ("upload" = HR ลากไฟล์เอง,
    "email" = ปากทางรับอีเมลอัตโนมัติ) มีดีฟอลต์ไว้เพื่อให้ผู้เรียกเดิมไม่ต้องแก้
    และเพื่อให้ get_state/update_state ที่ไม่รู้ที่มายังสร้าง config เดิมได้
    (ค่านี้อยู่ใน tags/metadata เท่านั้น ไม่แตะ configurable จึงไม่กระทบ checkpoint)
    """
    cid = str(candidate_id)
    return {
        "configurable": {"thread_id": cid},
        "run_name": f"screen-candidate-{cid[:8]}",
        "tags": ["talentmatch", "screening", f"source:{source}"],
        "metadata": {"candidate_id": cid, "source": source},
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
                similar_candidates, bias_revision, skill_evidence, score_explanation,
                confidence)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                job_id,
                candidate_id,
                evaluation["fit_score"],
                Json(evaluation.get("gaps")),
                evaluation.get("audit_status", "passed"),
                evaluation.get("audit_log", ""),
                Json(similar) if similar else None,
                Json(evaluation["bias_revision"]) if evaluation.get("bias_revision") else None,
                Json(evaluation["skill_evidence"]) if evaluation.get("skill_evidence") else None,
                evaluation.get("score_explanation") or None,
                evaluation.get("confidence") or None,
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


def _persist_plan(candidate_id: str, plan: dict) -> None:
    """บันทึกคำถามสัมภาษณ์ทันทีที่ planner เสร็จ — ไม่รอจนกราฟเดินจบ.

    เดิมคำถามถูกเขียนพร้อมร่างอีเมลตอนท้ายรอบเท่านั้น ถ้า email_drafter ล้ม (เช่นโควตา
    หมด) คำถามที่ planner สร้างเสร็จแล้วและจ่ายโควตาไปแล้วจะค้างอยู่ใน checkpoint
    โดยไม่เคยถึงหน้าเว็บ — เคยเกิดจริงกับผู้สมัครที่ HR อนุมัติไปแล้ว

    ล้าง email_draft ไปพร้อมกัน เพราะร่างเดิม (ถ้ามี) เป็นของเส้นทางรอบก่อน ถ้าคงไว้แล้ว
    drafter รอบนี้ล้ม หน้าเว็บจะโชว์คำถามสัมภาษณ์คู่กับอีเมลปฏิเสธเก่า · ไม่แตะ
    email_sent_at/email_sent_to ซึ่งเป็นร่องรอยการส่งจริง
    """
    with get_conn() as conn:
        conn.execute(
            """UPDATE evaluations
               SET interview_plan = %s, email_draft = NULL
               WHERE candidate_id = %s""",
            (Json(plan), candidate_id),
        )
        conn.commit()


def _has_evaluation(candidate_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM evaluations WHERE candidate_id = %s", (candidate_id,)
        ).fetchone()
    return row is not None


# โหนดหลังจุดตัดสิน — checkpoint ที่ค้างที่โหนดเหล่านี้ (หรือจบแล้ว) แปลว่าช่วงคัดกรอง
# เสร็จครบอยู่ใน state แล้ว
_AFTER_SCREENING = frozenset({"interview_planner", "email_drafter"})


def _resume_point(has_checkpoint: bool, next_nodes: tuple) -> str:
    """งาน process รอบนี้ควรเริ่มตรงไหน — ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมีกราฟ.

    - "fresh"            : ไม่เคยรัน → รันจากต้นด้วยข้อมูลตั้งต้น
    - "resume_screening" : ล้มกลางช่วงคัดกรอง → เดินต่อจากโหนดที่ล้ม
    - "after_screening"  : คัดกรองเสร็จแล้ว → ข้ามไปช่วงหลังเลย

    ⚠️ ห้าม invoke(ข้อมูลตั้งต้น) บน thread ที่มี checkpoint อยู่แล้ว LangGraph จะเริ่มใหม่
    จาก entry (พิสูจน์ด้วยกราฟจำลอง 2026-09-17) = จ่าย resume_parser กับ bias_auditor ซ้ำ
    และ _persist_evaluation ลบแถว evaluations ทิ้งสร้างใหม่ · เดิมเกิดทุกครั้งที่คิวลองงาน
    process ใหม่หลัง auto-advance ล้ม
    """
    if not has_checkpoint:
        return "fresh"
    if not next_nodes or any(n in _AFTER_SCREENING for n in next_nodes):
        return "after_screening"
    return "resume_screening"


def process_candidate(
    job_id: str,
    candidate_id: str,
    raw_jd: str,
    analyzed_jd: dict | None,
    resume_text: str,
    source: str = "upload",
    jd_audit: dict | None = None,
) -> None:
    """รันกราฟสำหรับผู้สมัครหนึ่งคน (thread_id = candidate_id).

    `jd_audit` = ผลตรวจอคติของตำแหน่ง (jobs.jd_audit) ส่งเข้า state ให้ bias_auditor อ่าน
    None = ตำแหน่งเก่าที่ยังไม่มีผลตรวจ โหนดจะใช้กฎตายตัวอย่างเดียว (ไม่เรียก LLM)
    """
    reserve_candidates([candidate_id])  # เผื่อถูกเรียกเดี่ยว ๆ (เช่น reprocess) ที่ยังไม่ได้จอง
    try:
        with _gate:  # จำกัด concurrency กันยิง LLM ทะลุเพดาน RPM
            _process_candidate_locked(
                job_id, candidate_id, raw_jd, analyzed_jd, resume_text, source, jd_audit
            )
    finally:
        release_candidate(candidate_id)


def _process_candidate_locked(
    job_id: str,
    candidate_id: str,
    raw_jd: str,
    analyzed_jd: dict | None,
    resume_text: str,
    source: str = "upload",
    jd_audit: dict | None = None,
) -> None:
    graph = get_graph()
    config = _config(candidate_id, source)
    snapshot = graph.get_state(config)
    point = _resume_point(bool(snapshot.created_at), tuple(snapshot.next or ()))
    if point != "fresh":
        log.info(
            "candidate %s มี checkpoint อยู่แล้ว (%s) — เดินต่อ ไม่รันใหม่จากต้น",
            candidate_id, point,
        )
        _continue_candidate(graph, config, job_id, candidate_id, resume_text, point)
        return

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
        "bias_revision_count": {},
        "bias_revision_pending": {},
        "bias_exclusions": {},
        "jd_audit": jd_audit,
    }
    state = graph.invoke(initial, config)
    _save_screening(job_id, candidate_id, state, resume_text)
    _after_screening(graph, config, candidate_id, state)


def _save_screening(job_id: str, candidate_id: str, state: dict, resume_text: str) -> None:
    """เขียนผลช่วงคัดกรองลง DB + index เวกเตอร์ (ครั้งเดียวต่อผู้สมัคร)."""
    evaluation = state["evaluations"][0]
    similar = (state.get("similar_candidates") or {}).get(str(candidate_id)) or []
    _persist_evaluation(job_id, candidate_id, evaluation, state["parsed_resumes"][0], similar)

    # เก็บเวกเตอร์ไว้ค้นหาผู้สมัครเก่าภายหลัง — ล้มแล้วต้องไม่ทำให้กราฟพัง
    # (เป็นฟีเจอร์เสริม ไม่ใช่ส่วนหนึ่งของการให้คะแนน)
    try:
        index_candidate(str(candidate_id), resume_text)
    except Exception as exc:  # noqa: BLE001
        log.warning("index เวกเตอร์ของผู้สมัคร %s ไม่สำเร็จ: %s", candidate_id, exc)


def _after_screening(graph, config, candidate_id: str, state: dict) -> None:
    """ช่วงหลังคัดกรอง: auto-advance / รอ HR / เดินต่อจากที่ค้าง / บันทึกผลที่จบแล้ว."""
    next_nodes = tuple(graph.get_state(config).next or ())
    evaluation = state["evaluations"][0]
    if next_nodes == ("interview_planner",):
        # พักก่อน interview_planner: auto-resume ถ้าคะแนนสูง, ไม่งั้นรอ HR
        if should_auto_advance(evaluation["fit_score"]):
            state = _drive_to_end(graph, config)
            _persist_outputs(candidate_id, state)
        else:
            log.info("candidate %s (fit=%s) รอ HR ตัดสิน", candidate_id, evaluation["fit_score"])
    elif next_nodes:
        # ค้างหลัง planner (เช่น drafter ล้มรอบก่อน) — เดินต่อจากตรงนั้น
        state = _drive_to_end(graph, config)
        _persist_outputs(candidate_id, state)
    else:
        # จบแล้ว (เส้นทางปฏิเสธ fit<50 หรือรอบก่อนจบแต่ยังไม่ได้บันทึก)
        _persist_outputs(candidate_id, state)


def _continue_candidate(
    graph, config, job_id: str, candidate_id: str, resume_text: str, point: str
) -> None:
    """งาน process ที่ถูกลองใหม่ — เดินต่อจาก checkpoint ไม่ใช่รันจากต้น."""
    if point == "resume_screening":
        # เดินต่อจากโหนดคัดกรองที่ล้ม — invoke(None) หยุดเองที่ interrupt หรือจบ
        graph.invoke(None, config)
    state = graph.get_state(config).values
    # มีแถว evaluations แล้ว = บันทึกไปแล้ว ห้ามเรียกซ้ำ: _persist_evaluation ลบแถวเดิม
    # ทิ้งสร้างใหม่ ซึ่งพาคอลัมน์อย่าง email_sent_at หายไปด้วย
    if not _has_evaluation(candidate_id):
        _save_screening(job_id, candidate_id, state, resume_text)
    _after_screening(graph, config, candidate_id, state)


def resolve_graph_status(
    has_checkpoint: bool,
    next_nodes: tuple,
    hr_decision: str | None,
    fit_score: int | None,
) -> str:
    """แปลง checkpoint เป็นสถานะที่ UI ใช้ — ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมีกราฟ.

    - "processing"  : ยังไม่มี checkpoint
    - "completed"   : กราฟเดินจบแล้ว (กดตัดสินแล้วจะ "ตัดสินใหม่" ทับของเดิม)
    - "awaiting_hr" : พักที่ interrupt จริง ยังไม่มีคำตัดสิน และคะแนนไม่อยู่ช่วงผ่านอัตโนมัติ
    - "interrupted" : ค้างกลางทาง — ตัดสินแล้วแต่ไม่เดินต่อ, คะแนนผ่านแต่ auto-advance ล้ม,
                      หรือค้างที่โหนดอื่นที่ไม่ใช่จุดพักรอ HR

    เดิมถือว่ากราฟที่ยังไม่จบทุกตัวคือ "รอ HR" ผู้สมัครที่ HR อนุมัติไปแล้วแต่ drafter ล้ม
    จึงถูกบอกว่ายังรอคำตัดสิน และไม่มีใครรู้ว่าต้องสั่งทำต่อ

    ⚠️ ผู้เรียกที่รู้ว่ากราฟกำลังรันหรือรอคิวอยู่ต้องทับ "interrupted" เป็น "processing" เอง —
    checkpoint ถูกบันทึกทุกขั้น ระหว่างเดินจึงดูเหมือนค้างชั่วขณะ
    """
    if not has_checkpoint:
        return "processing"
    if not next_nodes:
        return "completed"
    undecided = hr_decision in (None, "pending")
    auto = fit_score is not None and should_auto_advance(fit_score)
    if tuple(next_nodes) == ("interview_planner",) and undecided and not auto:
        return "awaiting_hr"
    return "interrupted"


def get_graph_status(
    candidate_id: str, hr_decision: str | None = None, fit_score: int | None = None
) -> str:
    """สถานะกราฟของผู้สมัคร — ให้ frontend บอก HR ว่าการกดปุ่มจะทำอะไร (ดู resolve_graph_status)."""
    try:
        snapshot = get_graph().get_state(_config(candidate_id))
    except Exception as exc:  # noqa: BLE001 — สถานะเป็นข้อมูลเสริม ห้ามทำให้ API ล้ม
        log.warning("อ่านสถานะกราฟของ %s ไม่ได้: %s", candidate_id, exc)
        return "processing"
    return resolve_graph_status(
        bool(snapshot.created_at), tuple(snapshot.next or ()), hr_decision, fit_score
    )


def _drive_to_end(graph, config, max_steps: int = 4) -> dict:
    """เดินกราฟจนจบ — invoke ซ้ำเมื่อโดน interrupt_before ขวางระหว่างทาง.

    ต้องวนเพราะกรณี "ย้อน state" ด้านล่างจะเดินมาถึง interview_planner แบบสด ๆ
    (ไม่ใช่การ resume) interrupt_before จึงทำงานอีกรอบ ต้อง invoke ซ้ำเพื่อผ่านไป
    """
    state: dict = {}
    for _ in range(max_steps):
        state = _advance(graph, config)
        if not graph.get_state(config).next:
            return state
    log.warning("กราฟของ %s ยังไม่จบหลังเดิน %s ครั้ง", config, max_steps)
    return state


def _advance(graph, config) -> dict:
    """เดินกราฟหนึ่งช่วง (ถึง interrupt หรือจบ) และบันทึกคำถามทันทีที่ planner เสร็จ.

    ใช้ stream แทน invoke เพื่อเห็นผลของแต่ละโหนดตอนที่มันเสร็จ ไม่ใช่ตอนทั้งช่วงจบ ·
    ถ้าโหนดถัดไปล้ม exception ยังหลุดออกไปตามเดิม (คิวต้องรู้เพื่อลองใหม่) แต่คำถามที่
    จ่ายโควตาไปแล้วถูกบันทึกไว้ก่อนแล้ว
    """
    cid = config["configurable"]["thread_id"]
    for chunk in graph.stream(None, config, stream_mode="updates"):
        update = chunk.get("interview_planner") if isinstance(chunk, dict) else None
        plan = ((update or {}).get("interview_plans") or {}).get(cid)
        # แผนว่าง = คนที่ถูกปฏิเสธ ไม่บันทึกกลางทาง ปล่อยให้ _persist_outputs ท้ายรอบล้างตามเดิม
        if plan and plan.get("questions"):
            _persist_plan(cid, plan)
    return graph.get_state(config).values


def decide_candidate(candidate_id: str, decision: str, notes: str | None) -> None:
    """ตัดสินหนึ่งคนแบบ "เข้าคิว" — ห่อ resume_after_decision ด้วยทะเบียน + semaphore.

    เดิม resume_after_decision ถูกเรียกตรง ๆ จาก BackgroundTask โดยไม่ผ่านทั้งสองอย่าง
    ต่างจาก process_candidate ทำให้:
      1. ทะเบียน _active มองไม่เห็นการตัดสินที่กำลังรัน — การ์ดกันลบ (jobs/candidates)
         และป้าย "ค้าง" (_is_stalled) จึงตัดสินใจบนข้อมูลที่ไม่ครบ และการกดปุ่มซ้ำ
         (หรือ bulk ซ้ำ) จะรันคนเดิมซ้อนกัน
      2. ไม่ผ่าน _gate = ตัดสินหลายคนพร้อมกันแล้วยิง LLM ขนานไม่จำกัด ชนเพดาน RPM

    ตัวห่อนี้จึงเป็นทางเข้าเดียวของการตัดสิน ทั้งปุ่มเดี่ยวและ bulk
    (resume_after_decision เดิมไม่มี try/except — exception หลุดเข้า BackgroundTask runner
    ที่นี่จึงต้อง finally release เสมอ ไม่งั้นผู้สมัครค้างในทะเบียนถาวรจนลบไม่ได้)
    """
    reserve_candidates([candidate_id])  # ปกติ router จองไว้แล้ว เรียกซ้ำได้ปลอดภัย
    try:
        with _gate:
            resume_after_decision(candidate_id, decision, notes)
    finally:
        release_candidate(candidate_id)


def _fresh_screening(cid: str, state: dict) -> dict:
    """เกณฑ์และผลประเมินล่าสุดจาก DB สำหรับเขียนทับ state ก่อนเดินต่อหลัง HR ตัดสิน.

    checkpoint ถือ analyzed_jd กับ evaluations ของตอนที่กราฟเดินครั้งแรก ถ้า HR แก้เกณฑ์ทักษะ
    ระหว่างนั้น (app/criteria_edit.py คำนวณคะแนนใหม่ลง DB) แล้วมากดอนุมัติ planner จะตั้งคำถาม
    จากทักษะที่ขาดตามเกณฑ์เก่า · ที่นี่เอาค่าจาก DB มาแทนเฉพาะ fit_score กับ gaps ส่วนฟิลด์อื่น
    ของ evaluation ใน state (audit ฯลฯ) คงเดิม · state ไม่มี reducer จึงเขียนทับได้ตรง ๆ
    ถ้าหาไม่เจอ (ยังไม่มีแถว) คืน {} = ใช้ state เดิม
    """
    with get_conn() as conn:
        row = conn.execute(
            """SELECT j.parsed_criteria, e.fit_score, e.gap_analysis
                 FROM candidates c
                 JOIN jobs j ON j.id = c.job_id
                 JOIN evaluations e ON e.candidate_id = c.id
                WHERE c.id = %s""",
            (cid,),
        ).fetchone()
    old = (state.get("evaluations") or [None])[0]
    if row is None or not old:
        return {}
    # gap_analysis เป็น NULL ได้ในแถวเก่า — ห้ามเอา {} ไปทับ gaps ที่ state มีอยู่จริง
    gaps = row["gap_analysis"] if row["gap_analysis"] is not None else old.get("gaps")
    fresh: dict = {"evaluations": [{**old, "fit_score": row["fit_score"], "gaps": gaps}]}
    if row["parsed_criteria"]:
        fresh["analyzed_jd"] = row["parsed_criteria"]
    return fresh


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
    # เติมเกณฑ์และผลประเมินล่าสุดจาก DB ลงใน update_state ครั้งเดียวกัน (as_node ระบุชัดข้างล่าง)
    values.update(_fresh_screening(cid, graph.get_state(config).values or {}))

    # ⚠️ ระบุ as_node เองทุกกรณี ห้ามปล่อยให้ LangGraph เดาจาก checkpoint ล่าสุด:
    # ถ้า checkpoint นั้นเกิดจาก update_state (เช่นรอบก่อน rewind แล้ว planner ล้ม) มันเดาผิด
    # แล้ว next กลายเป็นว่าง = กราฟ "จบ" ทั้งที่ยังไม่ได้ทำอะไร คิวจะนับว่าสำเร็จแบบเงียบ ๆ
    # (พิสูจน์ด้วยกราฟจำลอง 2026-09-17)
    next_nodes = tuple(graph.get_state(config).next or ())
    if not next_nodes or "interview_planner" in next_nodes:
        # จบแล้ว หรือพัก/ล้มที่ interview_planner — ย้อนไปหลัง auditor ให้ router ตัดสินใหม่
        # โดยมีคำตัดสินของ HR อยู่ในมือ (ไม่มี LLM ในช่วงนี้ ต้นทุนเท่าเดิม)
        if not next_nodes:
            log.info("กราฟของ %s จบไปแล้ว — ย้อนกลับไปที่ router เพื่อรับคำตัดสินของ HR", cid)
        graph.update_state(config, values, as_node="bias_auditor")
    elif "email_drafter" in next_nodes:
        # planner เสร็จแล้วแต่ drafter ล้ม — ต่อที่ drafter ไม่สร้างคำถามใหม่ (ประหยัด 1 call)
        graph.update_state(config, values, as_node="interview_planner")
    else:
        # ค้างกลางช่วงคัดกรองทั้งที่มีคำตัดสินแล้ว — ไม่ควรเกิด เพราะ HR ตัดสินได้หลังมีผล
        log.warning("กราฟของ %s ค้างที่ %s ขณะมีคำตัดสินของ HR", cid, next_nodes)
        graph.update_state(config, values)

    state = _drive_to_end(graph, config)
    _persist_outputs(candidate_id, state)
