"""คิว + worker บน DB จริง (app.job_queue / app.queue_worker) — ไม่ยิง LLM สักครั้ง.

รัน: docker compose exec backend python -m pytest tests/test_queue_worker.py -v

สิ่งที่เทสชุดนี้กัน — ทั้งหมดคือเคสที่เคยทำให้ "งานหายเงียบ" มาก่อน:
1. หยิบงานเก่าสุดก่อน (FIFO) และไม่หยิบซ้ำ
2. โควตาไม่พอ → deferred_quota **ไม่ใช่** failed (พรุ่งนี้ต้องรันได้)
3. reclaim_running() กู้แถวที่ค้างตอนโปรเซสตาย — หัวใจของงานนี้ทั้งงาน
4. ลบผู้สมัครแล้วงานในคิวหายตาม (FK cascade) worker จะได้ไม่ไปหยิบงานของคนที่ไม่มีอยู่
"""
import pytest

from app import job_queue, queue_worker
from app.database import get_conn


@pytest.fixture
def job_and_candidates():
    """งาน + ผู้สมัคร 2 คนของตัวเอง แล้วลบทิ้ง — ไม่แตะข้อมูลจริงในฐาน."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสคิว (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        ids = [
            str(
                conn.execute(
                    """INSERT INTO candidates (job_id, full_name, raw_resume_text)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (job["id"], f"ผู้สมัครคิว {i}", "ประสบการณ์ Python 3 ปี"),
                ).fetchone()["id"]
            )
            for i in range(2)
        ]
        conn.commit()
    yield str(job["id"]), ids
    with get_conn() as conn:
        # ลบผู้สมัครตรง ๆ ด้วย ไม่พึ่ง cascade ของ jobs อย่างเดียว — มีเทสที่ปลด job_id
        # ออกเพื่อจำลอง "ข้อมูลหายระหว่างรอคิว" แถวนั้นจะไม่ถูก cascade เก็บ
        conn.execute("DELETE FROM candidates WHERE id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


@pytest.fixture(autouse=True)
def no_leftover_queue():
    """กันงานจากเทสอื่น/ข้อมูลจริงมาปน — เทสนี้ต้องเห็นเฉพาะงานที่ตัวเองสร้าง."""
    with get_conn() as conn:
        stuck = conn.execute(
            "SELECT count(*) AS n FROM processing_queue WHERE status IN ('queued','running')"
        ).fetchone()["n"]
    if stuck:
        pytest.skip(f"มีงานค้างในคิวอยู่ {stuck} ชิ้น — ข้ามเพื่อไม่ให้ไปแย่งงานจริง")
    yield


@pytest.fixture
def ran(monkeypatch) -> list:
    """แทนที่การเดินกราฟด้วยการจดชื่อ — worker ต้องเรียก runner ตัวเดิม ไม่ copy logic."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        queue_worker.runner,
        "process_candidate",
        lambda **kw: calls.append(("process", kw["candidate_id"])),
    )
    monkeypatch.setattr(
        queue_worker.runner,
        "decide_candidate",
        lambda cid, decision, notes: calls.append(("decide", str(cid), decision, notes)),
    )
    return calls


def _status(queue_id) -> str:
    with get_conn() as conn:
        return conn.execute(
            "SELECT status FROM processing_queue WHERE id = %s", (queue_id,)
        ).fetchone()["status"]


class TestClaimOrder:
    def test_หยิบงานเก่าสุดก่อนและไม่หยิบซ้ำ(self, job_and_candidates, ran, monkeypatch):
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: False)
        job_id, (first, second) = job_and_candidates
        job_queue.enqueue(first, job_id, "process")
        job_queue.enqueue(second, job_id, "process")

        assert queue_worker.run_once() is True
        assert queue_worker.run_once() is True
        assert queue_worker.run_once() is False  # คิวหมดแล้ว

        assert [c[1] for c in ran] == [first, second]

    def test_คิวว่างแล้วไม่ทำอะไร(self, ran):
        assert queue_worker.run_once() is False
        assert ran == []


class TestQuotaGate:
    def test_โควตาไม่พอต้องพักไว้ไม่ใช่ล้มเหลว(self, job_and_candidates, ran, monkeypatch):
        """ถ้าตีเป็น failed ผู้สมัครจะขึ้น "วิเคราะห์ไม่สำเร็จ" ทั้งที่พรุ่งนี้รันได้เอง."""
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: True)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")

        assert queue_worker.run_once() is True
        assert ran == []  # ต้องไม่เสียโควตาไปกับงานที่รู้อยู่แล้วว่าไม่พอ

        with get_conn() as conn:
            row = conn.execute(
                "SELECT status, attempts FROM processing_queue WHERE candidate_id = %s",
                (cid,),
            ).fetchone()
        assert row["status"] == "deferred_quota"
        assert row["attempts"] == 0  # โควตาหมดไม่กิน attempts

    def test_งานที่พักไว้ยังไม่ครบเวลาไม่ถูกหยิบซ้ำ(self, job_and_candidates, monkeypatch):
        """deferred_quota เป็นสถานะ "พัก" ที่ worker หยิบกลับมาเองเมื่อครบเวลา
        ไม่ใช่ทันที ไม่งั้นจะวนยิง API รัว ๆ ตอนโควตาหมด."""
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: True)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")
        queue_worker.run_once()
        assert queue_worker.run_once() is False


class TestFailureHandling:
    def test_ล้มชั่วคราวกลับเข้าคิว(self, job_and_candidates, monkeypatch):
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: False)

        def boom(**kw):
            raise RuntimeError("503 Service Unavailable")

        monkeypatch.setattr(queue_worker.runner, "process_candidate", boom)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")
        queue_worker.run_once()

        with get_conn() as conn:
            row = conn.execute(
                "SELECT status, attempts, last_error FROM processing_queue WHERE candidate_id = %s",
                (cid,),
            ).fetchone()
        assert row["status"] == "queued"
        assert row["attempts"] == 1
        assert "503" in row["last_error"]

    def test_โควตาหมดกลางทางก็ยังพักไว้ไม่ใช่ล้มเหลว(self, job_and_candidates, monkeypatch):
        """ตัวนับของเราต่ำกว่าความจริงได้ (มีคนใช้คีย์เดียวกันที่อื่น) จึงต้องมีตาข่าย
        ชั้นสองที่ดัก 429 จริงจากปลายทางด้วย."""
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: False)

        def boom(**kw):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(queue_worker.runner, "process_candidate", boom)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")
        queue_worker.run_once()
        assert _status(_qid(cid)) == "deferred_quota"

    def test_ผู้สมัครหายไประหว่างรอคิวถือว่าล้มถาวร(self, job_and_candidates, ran, monkeypatch):
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: False)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")
        with get_conn() as conn:  # ลบเฉพาะแถวงาน ให้แถวคิวเป็นกำพร้าชั่วคราว
            conn.execute("UPDATE candidates SET job_id = NULL WHERE id = %s", (cid,))
            conn.commit()

        queue_worker.run_once()
        assert ran == []
        assert _status(_qid(cid)) == "failed"


def _qid(candidate_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id FROM processing_queue WHERE candidate_id = %s", (candidate_id,)
        ).fetchone()["id"]


class TestReclaim:
    def test_กู้งานที่ค้างสถานะ_running_ตอนบูต(self, job_and_candidates, monkeypatch):
        """จำลองโปรเซสตายกลางงาน: แถวค้าง running แล้วไม่มีใครมาทำต่อตลอดกาล
        นี่คือปัญหาที่งานทั้งงานนี้มีไว้แก้."""
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: False)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")
        job_queue.claim_next()  # ตีตรา running แล้วปล่อยค้างไว้ (= โปรเซสตาย)
        assert _status(_qid(cid)) == "running"

        assert job_queue.reclaim_running() == 1
        assert _status(_qid(cid)) == "queued"


class TestCascade:
    def test_ลบผู้สมัครแล้วงานในคิวหายตาม(self, job_and_candidates):
        """ถ้าไม่ cascade worker จะหยิบงานของคนที่ไม่มีอยู่ขึ้นมารันจนล้มทุกครั้ง."""
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(cid, job_id, "process")
        with get_conn() as conn:
            conn.execute("DELETE FROM candidates WHERE id = %s", (cid,))
            conn.commit()
            left = conn.execute(
                "SELECT count(*) AS n FROM processing_queue WHERE candidate_id = %s", (cid,)
            ).fetchone()["n"]
        assert left == 0


class TestDecideKind:
    def test_งานตัดสินเรียก_decide_candidate_ตัวเดิม(self, job_and_candidates, ran, monkeypatch):
        """HITL invariant พึ่งพาข้อนี้ทั้งหมด: worker ต้องไม่มี logic เดินกราฟของตัวเอง
        ไม่งั้นการ resume จากจุด interrupt จะกลายเป็นการ rerun จากต้น (เสียโควตา 2 เท่า)."""
        monkeypatch.setattr(queue_worker, "_quota_blocked", lambda kind: False)
        job_id, (cid, _) = job_and_candidates
        job_queue.enqueue(
            cid, job_id, "resume_after_decision", {"decision": "approved", "notes": "ผ่าน"}
        )
        queue_worker.run_once()
        assert ran == [("decide", cid, "approved", "ผ่าน")]


class TestWakeAndParallel:
    """ปลุกทันทีเมื่อมีงานใหม่ + รันหลายเธรดโดยไม่หยิบงานซ้ำกัน."""

    def test_enqueue_ปลุก_worker_ให้ไม่ต้องรอครบรอบ(self, job_and_candidates, monkeypatch):
        job_id, ids = job_and_candidates
        queue_worker._wake.clear()
        job_queue.enqueue(ids[0], job_id, "process")
        assert queue_worker._wake.is_set()

    def test_ปลุกไม่สำเร็จต้องไม่ทำให้_enqueue_ล้ม(self, job_and_candidates, monkeypatch):
        """เข้าคิวสำเร็จสำคัญกว่าการปลุก — ปลุกพังก็แค่เริ่มช้าตามรอบ poll."""
        job_id, ids = job_and_candidates
        monkeypatch.setattr(
            queue_worker, "wake", lambda: (_ for _ in ()).throw(RuntimeError("พัง"))
        )
        job_queue.enqueue(ids[0], job_id, "process")
        with get_conn() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM processing_queue WHERE candidate_id = %s",
                (ids[0],),
            ).fetchone()["n"]
        assert n == 1

    def test_หลายเธรดไม่หยิบงานชิ้นเดียวกัน(self, job_and_candidates, monkeypatch):
        """claim_next ใช้ FOR UPDATE SKIP LOCKED — งาน 2 ชิ้นกับ 4 เธรดต้องรันคนละชิ้น."""
        import threading

        job_id, ids = job_and_candidates
        ran: list[str] = []
        lock = threading.Lock()

        def fake_run(row):
            with lock:
                ran.append(str(row["candidate_id"]))

        monkeypatch.setattr(queue_worker, "_run_job", fake_run)
        for cid in ids:
            job_queue.enqueue(cid, job_id, "process")

        threads = [threading.Thread(target=queue_worker.run_once) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sorted(ran) == sorted(ids)  # ครบทุกชิ้น ไม่ซ้ำ ไม่ขาด

    def test_สตาร์ต_แล้วหยุดได้ครบทุกเธรด(self, monkeypatch):
        monkeypatch.setattr(queue_worker, "WORKERS", 3)
        queue_worker.start_worker()
        try:
            assert len(queue_worker._threads) == 3
            assert all(t.is_alive() for t in queue_worker._threads)
        finally:
            queue_worker.stop_worker(timeout=5)
        assert queue_worker._threads == []
