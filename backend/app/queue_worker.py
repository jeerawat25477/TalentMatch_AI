"""Worker ที่ดึงงานจาก processing_queue มารันตามโควตาที่เหลือ (ค่าเริ่มต้น 3 เธรด).

ทำไมต้องมีแทน BackgroundTasks: BackgroundTasks อยู่ในโปรเซส — รีสตาร์ตแล้วงานหาย
และมันยิงงานทั้ง batch เข้ากราฟทันทีโดยไม่รู้ว่าโควตาวันนี้เหลือเท่าไร อัปโหลด 20 ไฟล์
คนที่ 7 เป็นต้นไปจึงชน RPD แล้วตายเงียบยกแผง (ดู CLAUDE.md)

**โปรเซสเดียวเท่านั้น** เหมือน active_candidates() และ rate limiter ของล็อกอิน:
backend เป็นเรพลิกาเดียว และ _gate ใน agents/runner.py เป็น semaphore ระดับโปรเซส
ถ้าจะสเกลเป็นหลายเรพลิกาต้องย้ายทั้งสามอย่างพร้อมกัน (claim_next อะตอมมิกอยู่แล้ว
จึงไม่ใช่ตัวที่ขวาง)

**หลายเธรดในโปรเซสเดียว** (QUEUE_WORKERS, ดีฟอลต์ 3): claim_next ใช้ FOR UPDATE SKIP
LOCKED อยู่แล้ว สองเธรดจึงไม่มีทางหยิบงานชิ้นเดียวกัน · ตั้งเป็น 1 แล้วได้พฤติกรรมเดิม
(ทำทีละชิ้น) โดยไม่ต้องแก้โค้ด · เพดานจริงของการยิง LLM พร้อมกันคือ _gate ใน runner.py
(GRAPH_MAX_CONCURRENCY) ไม่ใช่จำนวนเธรดนี้ — ตั้งจำนวนเธรดเกิน gate ก็แค่ไปยืนรอเปล่า ๆ

**ปลุกทันทีเมื่อมีงานใหม่** แทนการรอครบรอบ poll: ก่อนหน้านี้อัปโหลดเสร็จแล้วอาจนั่งรอ
ถึง POLL_SEC วินาทีทั้งที่ไม่มีอะไรทำอยู่เลย · ยังตื่นเองตามรอบไว้เป็นตาข่าย เพราะงานที่ถูก
พักเพราะโควตา (deferred_quota) และแถวที่ reclaim_running() คืนมาหลังรีสตาร์ต ไม่มีใครปลุก

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
# กี่งานที่รันพร้อมกันได้ — ดีฟอลต์ 3 · 1 = พฤติกรรมเดิม (ทีละชิ้น)
WORKERS = max(1, int(os.getenv("QUEUE_WORKERS", "3")))

_stop = threading.Event()
# มีงานใหม่เข้าคิว — job_queue.enqueue* ตั้งค่านี้เพื่อปลุกเธรดที่กำลังนอนรอ
_wake = threading.Event()
_threads: list[threading.Thread] = []
# เช็คโควตา + รับงาน ทำทีละเธรด: สามเธรดที่เช็คพร้อมกันจะเห็นยอดใช้เท่ากันแล้วผ่านหมด
# ทำให้ใช้เกินเพดานที่ตั้งไว้ · ส่วนการ "รันงาน" ยังขนานกันเต็มที่ ไม่อยู่ในล็อกนี้
_claim_lock = threading.Lock()


def wake() -> None:
    """ปลุก worker ให้หยิบงานทันที — เรียกจากเธรดของ request หลัง enqueue (ไม่บล็อก)."""
    _wake.set()


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
            """SELECT c.raw_resume_text, c.job_id, j.raw_text, j.parsed_criteria, j.jd_audit
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
        # ที่มาถูกฝากไว้ใน payload ตอน enqueue — ทำให้ trace ใน LangSmith แยกได้ว่า
        # ผู้สมัครรายนี้มาจาก HR อัปเอง หรือมาจากปากทางรับอีเมล
        source=payload.get("source") or "upload",
        # ผลตรวจอคติของตำแหน่ง ทำครั้งเดียวตอนสร้าง — ต่อผู้สมัครจึงไม่เรียก LLM ตรวจซ้ำ
        jd_audit=data["jd_audit"],
    )


def run_once() -> bool:
    """หยิบและรันงานหนึ่งชิ้น — คืน True ถ้ามีงานให้ทำ (แยกออกมาเพื่อทดสอบได้ตรง ๆ)."""
    # ล็อกครอบแค่ "หยิบงาน + เช็คโควตา" ไม่ครอบการรัน — ไม่งั้นหลายเธรดก็ไม่ต่างจากเธรดเดียว
    with _claim_lock:
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
                _wake.clear()  # งานที่ปลุกไว้ถูกหยิบแล้ว
        except Exception as exc:  # noqa: BLE001 — worker ต้องไม่ตายไม่ว่าเกิดอะไรขึ้น
            log.exception("ลูปคิวล้มทั้งรอบ (จะลองใหม่รอบหน้า): %s", exc)
        # ตื่นเมื่อมีงานใหม่ หรือครบรอบ (ตาข่ายของงานที่ถูกพักไว้/แถวค้างหลังรีสตาร์ต)
        if _wake.wait(POLL_SEC):
            _wake.clear()
    log.info("worker คิวหยุดแล้ว")


def start_worker() -> None:
    """สตาร์ต worker (idempotent) — เรียกจาก lifespan ของ main.py."""
    if any(t.is_alive() for t in _threads):
        return
    _stop.clear()
    _wake.clear()
    _threads.clear()
    for i in range(WORKERS):
        t = threading.Thread(target=_loop, name=f"queue-worker-{i + 1}", daemon=True)
        t.start()
        _threads.append(t)
    log.info("worker คิวเริ่มทำงาน %s เธรด (poll ทุก %s วินาที)", WORKERS, POLL_SEC)


def stop_worker(timeout: float = 5.0) -> None:
    """สั่งหยุดทุกเธรดแล้วรอสั้น ๆ — งานที่กำลังรันอยู่จะรันจนจบ (daemon thread ตายพร้อม
    โปรเซสถ้าเกินเวลา และแถวจะค้าง 'running' ซึ่ง reclaim_running() ตอนบูตหน้าเก็บให้เอง)."""
    _stop.set()
    _wake.set()  # ปลุกเธรดที่กำลังนอนให้เห็น _stop ทันที ไม่ต้องรอครบรอบ
    for t in _threads:
        t.join(timeout=timeout)
    _threads.clear()
