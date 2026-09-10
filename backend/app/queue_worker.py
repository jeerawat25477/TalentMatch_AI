"""Worker ตัวเดียวที่ดึงงานจาก processing_queue มารันทีละชิ้นตามโควตาที่เหลือ.

ทำไมต้องมีแทน BackgroundTasks: BackgroundTasks อยู่ในโปรเซส — รีสตาร์ตแล้วงานหาย
และมันยิงงานทั้ง batch เข้ากราฟทันทีโดยไม่รู้ว่าโควตาวันนี้เหลือเท่าไร อัปโหลด 20 ไฟล์
คนที่ 7 เป็นต้นไปจึงชน RPD แล้วตายเงียบยกแผง (ดู CLAUDE.md)

**ตัวเดียวเท่านั้น** เหมือน active_candidates() และ rate limiter ของล็อกอิน:
backend เป็นเรพลิกาเดียว และ _gate ใน agents/runner.py เป็น semaphore ระดับโปรเซส
ถ้าจะสเกลเป็นหลายเรพลิกาต้องย้ายทั้งสามอย่างพร้อมกัน (claim_next อะตอมมิกอยู่แล้ว
จึงไม่ใช่ตัวที่ขวาง)

ใช้ threading.Thread ไม่ใช่ asyncio task เพราะ graph.invoke() เป็น blocking call —
วางบน event loop จะไปบล็อก request ของ FastAPI ทั้งเซิร์ฟเวอร์
"""
import logging
import os
import threading

from app.agents import runner
from app.agents.llm import COMPLEX_MODEL, DEFAULT_MODEL
from app.database import get_conn
from app.job_queue import (
    claim_next,
    classify_failure,
    estimate_cost,
    mark,
    next_state,
)
from app.llm_quota import GEMINI_DAILY_CHAT_QUOTA, has_room, used_today

log = logging.getLogger(__name__)

POLL_SEC = int(os.getenv("QUEUE_POLL_SEC", "10"))

_stop = threading.Event()
_thread: threading.Thread | None = None


class _JobDataMissing(Exception):
    """แถวผู้สมัคร/งานหายไประหว่างที่งานรออยู่ในคิว — ล้มถาวร ไม่ต้องลองใหม่."""


def _quota_blocked(kind: str) -> bool:
    """โควตาวันนี้เหลือไม่พอสำหรับงานชนิดนี้หรือเปล่า.

    เช็คทั้งสองโมเดลที่กราฟใช้ (ดีฟอลต์/complex) เพราะโควตาคิดแยกต่อโมเดล —
    งานหนึ่งชิ้นเรียกทั้งคู่ ถ้าฝั่งใดฝั่งหนึ่งเต็มก็รันไม่จบอยู่ดี
    """
    cost = estimate_cost(kind)
    for model in {DEFAULT_MODEL, COMPLEX_MODEL}:
        if not has_room(used_today(model), cost, GEMINI_DAILY_CHAT_QUOTA):
            log.info(
                "พักงาน %s ไว้ — โควตา %s วันนี้เหลือไม่พอ (ใช้ไป %s/%s ต้องการอีก %s)",
                kind, model, used_today(model), GEMINI_DAILY_CHAT_QUOTA, cost,
            )
            return True
    return False


def _run_job(row: dict) -> None:
    """เรียกฟังก์ชันเดิมใน runner.py ตาม kind — **ห้าม copy logic ของกราฟมาที่นี่**.

    process_candidate / decide_candidate จอง _active + เข้าคิว _gate + ปลดจองใน
    finally ให้อยู่แล้ว การเรียกของเดิมจึงทำให้ทะเบียน ป้าย stalled การ์ดกันลบ
    และที่สำคัญที่สุดคือ **HITL invariant** (resume จาก interrupt ไม่ rerun จากต้น)
    ยังทำงานเหมือนเดิมทั้งหมดโดยไม่ต้องทำอะไรเพิ่ม
    """
    cid = str(row["candidate_id"])
    kind = row["kind"]
    payload = row["payload"] or {}

    if kind == "resume_after_decision":
        runner.decide_candidate(cid, payload["decision"], payload.get("notes"))
        return

    # process / reprocess — อ่านข้อความสดจาก DB ไม่ใช่จาก payload:
    # คิวอยู่ข้ามวันได้ สำเนาที่แช่ไว้ตั้งแต่ตอน enqueue อาจเป็นฉบับเก่าถ้า JD ถูกแก้
    with get_conn() as conn:
        data = conn.execute(
            """SELECT c.raw_resume_text, c.job_id, j.raw_text, j.parsed_criteria
                 FROM candidates c
                 JOIN jobs j ON j.id = c.job_id
                WHERE c.id = %s""",
            (cid,),
        ).fetchone()
    if data is None:
        raise _JobDataMissing(f"ไม่พบผู้สมัคร {cid} หรือตำแหน่งงานของเขาแล้ว")

    runner.process_candidate(
        job_id=str(data["job_id"]),
        candidate_id=cid,
        raw_jd=data["raw_text"],
        analyzed_jd=data["parsed_criteria"],
        resume_text=data["raw_resume_text"] or "",
    )


def run_once() -> bool:
    """หยิบและรันงานหนึ่งชิ้น — คืน True ถ้ามีงานให้ทำ (แยกออกมาเพื่อทดสอบได้ตรง ๆ)."""
    row = claim_next()
    if row is None:
        return False

    qid, attempts, kind = row["id"], row["attempts"], row["kind"]

    # เช็คโควตา "ก่อน" รัน แล้วพักไว้ทั้งชิ้น — ไม่ข้ามไปงานถัดไปในรอบนี้ เพราะคิวเป็น
    # FIFO ถ้าปล่อยให้งานที่ถูกกว่าแซงคิว ลำดับที่ HR เห็นจะอธิบายไม่ได้
    if _quota_blocked(kind):
        mark(qid, "deferred_quota", attempts, "โควตา AI วันนี้เหลือไม่พอ")
        return True

    try:
        _run_job(row)
    except _JobDataMissing as exc:
        mark(qid, "failed", attempts + 1, str(exc))
        log.warning("งาน %s ตกไป: %s", qid, exc)
    except Exception as exc:  # noqa: BLE001 — งานชิ้นเดียวล้มต้องไม่ทำให้ worker ตาย
        outcome = classify_failure(exc)
        status, new_attempts = next_state(outcome, attempts)
        mark(qid, status, new_attempts, f"{type(exc).__name__}: {exc}")
        log.exception("งาน %s (%s) ล้ม [%s] -> %s: %s", qid, kind, outcome, status, exc)
    else:
        status, new_attempts = next_state("ok", attempts)
        mark(qid, status, new_attempts)
    return True


def _loop() -> None:
    while not _stop.is_set():
        try:
            # ทำต่อเนื่องจนคิวหมด แล้วค่อยไปนอน — ไม่งั้น batch 20 คนจะใช้เวลา
            # อย่างน้อย 20 × POLL_SEC เพียงเพราะรอนาฬิกา
            while not _stop.is_set() and run_once():
                pass
        except Exception as exc:  # noqa: BLE001 — worker ต้องไม่ตายไม่ว่าเกิดอะไรขึ้น
            log.exception("ลูปคิวล้มทั้งรอบ (จะลองใหม่รอบหน้า): %s", exc)
        _stop.wait(POLL_SEC)
    log.info("worker คิวหยุดแล้ว")


def start_worker() -> None:
    """สตาร์ต worker (idempotent) — เรียกจาก lifespan ของ main.py."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="queue-worker", daemon=True)
    _thread.start()
    log.info("worker คิวเริ่มทำงาน (poll ทุก %s วินาที)", POLL_SEC)


def stop_worker(timeout: float = 5.0) -> None:
    """สั่งหยุดแล้วรอสั้น ๆ — งานที่กำลังรันอยู่จะรันจนจบ (daemon thread ตายพร้อมโปรเซส
    ถ้าเกินเวลา และแถวจะค้าง 'running' ซึ่ง reclaim_running() ตอนบูตหน้าเก็บให้เอง)."""
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
