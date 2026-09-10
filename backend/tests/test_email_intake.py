"""ปากทางรับใบสมัครทางอีเมล (app.email_intake) — ไม่ต้องมีกล่องเมลจริง ไม่ยิง LLM.

รัน: docker compose exec backend python -m pytest tests/test_email_intake.py -v

สิ่งที่เทสชุดนี้กัน เรียงตามความสำคัญ:
1. **ปิดแล้วต้องหลับสนิท** — ไม่แตะ IMAP เลยแม้แต่การเปิด socket (หลักการข้อ 1 ของผู้ใช้)
2. จับคู่ตำแหน่งงานจาก apply+<job_id>@ / [job:<id>] เท่านั้น ห้ามเดา
3. UIDVALIDITY เปลี่ยน = เลข UID เดิมใช้ไม่ได้ ต้องเริ่มนับใหม่ ไม่ใช่ข้ามทั้งกล่อง
4. last_uid_seen เดินทีละฉบับ — worker ตายกลางทางแล้วต้องไม่ดูดซ้ำ (เสียโควตา)
5. ไฟล์แนบต้องผ่านด่านชุดเดียวกับที่ HR อัปโหลดเอง (app/resume_ingest.py)
"""
import uuid
from email.message import EmailMessage
from pathlib import Path

import pytest

from app import email_intake
from app.agents.runner import release_candidate
from app.database import get_conn
from app.email_intake import SETTING_KEY
from app.settings import get_setting, invalidate, set_setting

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"
JOB_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _pdf(name: str = "strong_somchai.pdf") -> bytes:
    return (SAMPLES / name).read_bytes()


def build_email(
    to: str = f"apply+{JOB_UUID}@company.com",
    subject: str = "สมัครงานตำแหน่ง Backend",
    attachments: list[tuple[str, bytes]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "somchai@example.com"
    msg["To"] = to
    msg["Subject"] = subject
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    msg.set_content("เรียน ฝ่ายบุคคล ผมขอสมัครงานตำแหน่งนี้ครับ")
    for filename, data in attachments or []:
        msg.add_attachment(
            data, maintype="application", subtype="pdf", filename=filename
        )
    return msg.as_bytes()


class FakeIMAP:
    """เลียนแบบ imaplib.IMAP4_SSL เท่าที่ email_intake ใช้ — รวมรูปแบบ tuple แปลก ๆ ของมัน."""

    def __init__(self, messages: dict[int, bytes], uid_validity: str = "1000"):
        self.messages = messages
        self.uid_validity = uid_validity
        self.fetched: list[int] = []
        self.commands: list[str] = []
        self.selected_readonly: bool | None = None

    def select(self, mailbox, readonly=False):
        self.selected_readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def status(self, mailbox, what):
        return "OK", [f"{mailbox} (UIDVALIDITY {self.uid_validity})".encode()]

    def uid(self, command, *args):
        self.commands.append(command.upper())
        if command.upper() == "SEARCH":
            start = int(str(args[1]).split()[1].split(":")[0])
            hits = [u for u in sorted(self.messages) if u >= start]
            # IMAP ตอบ "UID n:*" โดยคืนฉบับล่าสุดมาด้วยเสมอแม้ไม่มีของใหม่ — จำลองไว้
            if not hits and self.messages:
                hits = [max(self.messages)]
            return "OK", [" ".join(str(u) for u in hits).encode()]
        if command.upper() == "FETCH":
            uid = int(args[0])
            self.fetched.append(uid)
            raw = self.messages[uid]
            return "OK", [(f"{uid} (BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(f"คำสั่งที่ไม่ควรถูกเรียก: {command}")

    def logout(self):
        return "BYE", []


@pytest.fixture(autouse=True)
def clean_state():
    """กันเทสไปเปื้อนของจริง: คืนค่าตั้งค่าเดิม และเก็บกวาดแถว log ที่เทสสร้าง.

    เทสในไฟล์นี้เรียกโค้ดจริงที่เขียน DB (patch_setting / email_intake_log) ถ้าไม่คืนค่า
    last_uid_seen ของจริงจะถูกทับด้วยเลขปลอมจากเทส แล้วรอบ poll จริงจะข้ามเมลจริงไป
    """
    invalidate()
    before = dict(get_setting(SETTING_KEY, {}))
    with get_conn() as conn:
        existing = {
            str(r["id"])
            for r in conn.execute("SELECT id FROM email_intake_log").fetchall()
        }
    yield
    set_setting(SETTING_KEY, before)
    invalidate()
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM email_intake_log").fetchall()
        junk = [str(r["id"]) for r in rows if str(r["id"]) not in existing]
        if junk:
            conn.execute("DELETE FROM email_intake_log WHERE id = ANY(%s)", (junk,))
            conn.commit()


@pytest.fixture
def no_setting_writes(monkeypatch) -> list:
    """ดักการเขียนค่าตั้งค่า — เทส poll_once สนใจแค่ว่า uid เดินถูก ไม่ต้องเขียนของจริง."""
    writes: list[dict] = []
    monkeypatch.setattr(email_intake, "patch_setting", lambda k, v, d=None: writes.append(v))
    return writes


@pytest.fixture
def job():
    """ตำแหน่งงานเปิดรับของตัวเอง แล้วลบทิ้ง (cascade เก็บผู้สมัคร/คิวให้)."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสรับอีเมล (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        conn.commit()
    jid = str(row["id"])
    yield jid
    with get_conn() as conn:
        ids = [
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM candidates WHERE job_id = %s", (jid,)
            ).fetchall()
        ]
        conn.execute("DELETE FROM email_intake_log WHERE job_id = %s", (jid,))
        conn.execute("DELETE FROM jobs WHERE id = %s", (jid,))
        conn.commit()
    for cid in ids:
        release_candidate(cid)


def _outcomes(job_id: str) -> list[str]:
    with get_conn() as conn:
        return [
            r["outcome"]
            for r in conn.execute(
                "SELECT outcome FROM email_intake_log WHERE job_id = %s ORDER BY created_at",
                (job_id,),
            ).fetchall()
        ]


class TestExtractJobId:
    def test_เจอใน_to_แบบ_plus_addressing(self):
        got = email_intake.extract_job_id({"To": f"apply+{JOB_UUID}@company.com"}, "")
        assert got == JOB_UUID

    def test_delivered_to_ชนะ_to(self):
        """ผู้ส่งปลอม To ได้ แต่ Delivered-To เซิร์ฟเวอร์ปลายทางเป็นคนเติม."""
        other = str(uuid.uuid4())
        got = email_intake.extract_job_id(
            {"To": f"apply+{other}@company.com",
             "Delivered-To": f"apply+{JOB_UUID}@company.com"},
            "",
        )
        assert got == JOB_UUID

    def test_เจอใน_cc(self):
        assert email_intake.extract_job_id(
            {"Cc": f"apply+{JOB_UUID}@company.com"}, ""
        ) == JOB_UUID

    def test_ทางสำรองใน_subject(self):
        assert email_intake.extract_job_id(
            {"To": "hr@company.com"}, f"สมัครงาน [job:{JOB_UUID}]"
        ) == JOB_UUID

    def test_ที่อยู่ผู้รับชนะ_subject(self):
        """subject ผู้ส่งพิมพ์อะไรก็ได้ จึงต้องมาทีหลังที่อยู่ปลายทางเสมอ."""
        other = str(uuid.uuid4())
        assert email_intake.extract_job_id(
            {"To": f"apply+{JOB_UUID}@company.com"}, f"[job:{other}]"
        ) == JOB_UUID

    @pytest.mark.parametrize(
        "headers, subject",
        [
            ({"To": "hr@company.com"}, "สมัครงานครับ"),
            ({"To": "apply+not-a-uuid@company.com"}, ""),
            ({"To": "apply+12345678-1234-1234-1234-12345678901@company.com"}, ""),
            ({}, ""),
        ],
    )
    def test_จับคู่ไม่ได้ต้องคืน_none(self, headers, subject):
        """คืน None = ทิ้งเมลไว้ในกล่อง **ห้ามเดาตำแหน่งด้วย LLM** (เปลืองโควตา)."""
        assert email_intake.extract_job_id(headers, subject) is None


class TestTemplateMatchesMatcher:
    """ที่อยู่ที่หน้าเว็บโชว์ กับที่อยู่ที่ตัวจับคู่รู้จัก ต้องเป็นอันเดียวกันเสมอ.

    บั๊กจริงที่เทสนี้เกิดมาเพื่อกัน (เจอตอนทดสอบรวม 2026-09-10): ตัวจับคู่เคย hardcode
    ว่าต้องเป็น `apply+<uuid>@` แต่ apply_address_template สร้างที่อยู่จาก IMAP_USER
    พอกล่องชื่อ recruit@ หน้าเว็บก็บอกผู้สมัครว่า recruit+<uuid>@ ซึ่งตัวจับคู่ไม่รู้จัก
    → ใบสมัครทุกฉบับที่ส่งมาตามที่ระบบบอกเองถูกตีเป็น unmatched แบบเงียบ ๆ
    """

    @pytest.mark.parametrize(
        "mailbox",
        ["apply@company.com", "recruit@talentmatch.local", "hr.team+x@sub.domain.co.th",
         "jobs-2026@company.co.th"],
    )
    def test_ที่อยู่ที่ระบบสร้างเองต้องถูกจับคู่ได้เสมอ(self, monkeypatch, mailbox):
        from app import email_intake as ei

        monkeypatch.setattr(ei, "IMAP_USER", mailbox)
        template = ei.apply_address_template()
        assert template is not None
        address = template.replace("{job_id}", JOB_UUID)
        assert ei.extract_job_id({"To": address}, "") == JOB_UUID


class TestProcessMessage:
    def test_จับคู่ได้ต้องสร้างผู้สมัครและเข้าคิว(self, job):
        raw = build_email(
            to=f"apply+{job}@company.com",
            attachments=[("somchai.pdf", _pdf())],
        )
        assert email_intake.process_message("1", raw) == "matched"

        with get_conn() as conn:
            cands = conn.execute(
                "SELECT id FROM candidates WHERE job_id = %s", (job,)
            ).fetchall()
            queued = conn.execute(
                """SELECT q.status, q.kind, q.payload FROM processing_queue q
                     JOIN candidates c ON c.id = q.candidate_id
                    WHERE c.job_id = %s""",
                (job,),
            ).fetchall()
        assert len(cands) == 1
        assert len(queued) == 1
        assert queued[0]["kind"] == "process"
        assert queued[0]["status"] == "queued"
        # ที่มาต้องติดไปกับงาน เพื่อให้ trace ใน LangSmith แยก upload ออกจาก email ได้
        assert queued[0]["payload"]["source"] == "email"
        assert _outcomes(job) == ["matched"]

    def test_ไฟล์เดิมส่งซ้ำต้องไม่สร้างผู้สมัครเพิ่ม(self, job):
        raw = build_email(
            to=f"apply+{job}@company.com", attachments=[("somchai.pdf", _pdf())]
        )
        email_intake.process_message("1", raw)
        # ฉบับที่สอง ชื่อไฟล์ต่างแต่ไบต์เดิม — sha256 ต้องจับได้
        raw2 = build_email(
            to=f"apply+{job}@company.com", attachments=[("resume-final.pdf", _pdf())]
        )
        assert email_intake.process_message("2", raw2) == "duplicate"

        with get_conn() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM candidates WHERE job_id = %s", (job,)
            ).fetchone()["n"]
        assert n == 1
        assert _outcomes(job) == ["matched", "duplicate"]

    def test_ไม่มีไฟล์แนบ(self, job):
        raw = build_email(to=f"apply+{job}@company.com")
        assert email_intake.process_message("1", raw) == "no_attachment"
        assert _outcomes(job) == ["no_attachment"]

    def test_ไฟล์แนบที่ไม่ใช่_pdf_ถูกปฏิเสธด้วยไบต์จริง(self, job):
        """ตั้งชื่อ .pdf และประกาศ Content-Type เป็น pdf ก็ไม่ช่วย — ตัดสินที่ magic byte."""
        raw = build_email(
            to=f"apply+{job}@company.com",
            attachments=[("ไวรัส.pdf", b"MZ\x90\x00 this is not a pdf")],
        )
        assert email_intake.process_message("1", raw) == "no_attachment"
        with get_conn() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM candidates WHERE job_id = %s", (job,)
            ).fetchone()["n"]
        assert n == 0

    def test_ตำแหน่งงานปิดรับแล้วต้องไม่รับเข้า(self, job):
        """กฎเดียวกับ upload_resumes ที่ตอบ 409 — ทางเข้าสองทางต้องไม่ขัดกัน."""
        with get_conn() as conn:
            conn.execute("UPDATE jobs SET status = 'closed' WHERE id = %s", (job,))
            conn.commit()
        raw = build_email(
            to=f"apply+{job}@company.com", attachments=[("somchai.pdf", _pdf())]
        )
        assert email_intake.process_message("1", raw) == "job_closed"
        with get_conn() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM candidates WHERE job_id = %s", (job,)
            ).fetchone()["n"]
        assert n == 0

    def test_อ้างถึงตำแหน่งงานที่ไม่มีอยู่(self):
        ghost = str(uuid.uuid4())
        raw = build_email(
            to=f"apply+{ghost}@company.com", attachments=[("somchai.pdf", _pdf())]
        )
        assert email_intake.process_message("1", raw) == "unmatched"

    def test_จับคู่ไม่ได้ต้องไม่แตะ_db(self):
        raw = build_email(to="hr@company.com", attachments=[("somchai.pdf", _pdf())])
        with get_conn() as conn:
            before = conn.execute("SELECT count(*) AS n FROM candidates").fetchone()["n"]
        assert email_intake.process_message("1", raw) == "unmatched"
        with get_conn() as conn:
            after = conn.execute("SELECT count(*) AS n FROM candidates").fetchone()["n"]
        assert before == after


class TestPollOnce:
    def test_ดึงเฉพาะฉบับที่ใหม่กว่า_last_uid(self, job, monkeypatch, no_setting_writes):
        seen: list[str] = []
        monkeypatch.setattr(
            email_intake, "process_message", lambda uid, raw, v=None: seen.append(uid)
        )
        raw = build_email(to=f"apply+{job}@company.com")
        client = FakeIMAP({1: raw, 2: raw, 3: raw})

        state = email_intake.poll_once(client, {"last_uid_seen": "1", "uid_validity": "1000"})
        assert seen == ["2", "3"]
        assert state["last_uid_seen"] == "3"

    def test_ไม่มีเมลใหม่ต้องไม่ประมวลผลฉบับเดิมซ้ำ(self, monkeypatch, no_setting_writes):
        """IMAP ตอบ "UID n:*" โดยคืนฉบับล่าสุดมาด้วยเสมอ ถ้าไม่กรองจะดูดซ้ำทุกรอบ."""
        seen: list[str] = []
        monkeypatch.setattr(
            email_intake, "process_message", lambda uid, raw, v=None: seen.append(uid)
        )
        client = FakeIMAP({1: b"x", 2: b"x", 3: b"x"})
        email_intake.poll_once(client, {"last_uid_seen": "3", "uid_validity": "1000"})
        assert seen == []

    def test_uidvalidity_เปลี่ยนต้องเริ่มนับใหม่ทั้งกล่อง(self, monkeypatch, no_setting_writes):
        """กล่องถูกสร้างใหม่ = เลข UID คนละชุด ถ้าใช้ค่าเดิมต่อจะข้ามเมลใหม่ทั้งกล่องเงียบ ๆ."""
        seen: list[str] = []
        monkeypatch.setattr(
            email_intake, "process_message", lambda uid, raw, v=None: seen.append(uid)
        )
        client = FakeIMAP({1: b"x", 2: b"x"}, uid_validity="9999")
        state = email_intake.poll_once(
            client, {"last_uid_seen": "50", "uid_validity": "1000"}
        )
        assert seen == ["1", "2"]
        assert state["uid_validity"] == "9999"

    def test_ฉบับกลางพังต้องไม่หยุดฉบับที่เหลือ_และ_uid_เดินทีละฉบับ(self, monkeypatch, no_setting_writes):
        """ถ้าอัปเดต uid ตอนท้าย batch อย่างเดียว worker ตายกลางทางแล้วรอบหน้าจะดูดซ้ำ."""
        seen: list[str] = []

        def flaky(uid, raw, v=None):
            seen.append(uid)
            if uid == "2":
                raise RuntimeError("ฉบับนี้พัง")

        monkeypatch.setattr(email_intake, "process_message", flaky)
        client = FakeIMAP({1: b"x", 2: b"x", 3: b"x"})
        state = email_intake.poll_once(client, {"last_uid_seen": None, "uid_validity": "1000"})

        assert seen == ["1", "2", "3"]      # ฉบับที่ 3 ยังได้ไปต่อ
        assert state["last_uid_seen"] == "3"

    def test_ต้องใช้_body_peek_ไม่ใช่_body(self, monkeypatch, no_setting_writes):
        """BODY[] ตั้งแฟล็ก \\Seen ให้อัตโนมัติ = ไปแตะสถานะเมลของ HR."""
        monkeypatch.setattr(email_intake, "process_message", lambda *a, **k: None)

        used: list[str] = []

        class Spy(FakeIMAP):
            def uid(self, command, *args):
                if command.upper() == "FETCH":
                    used.append(args[1])
                return super().uid(command, *args)

        email_intake.poll_once(Spy({1: b"x"}), {"last_uid_seen": None, "uid_validity": "1000"})
        assert used == ["(BODY.PEEK[])"]


class TestSleepsWhenDisabled:
    """หลักการข้อ 1 ของผู้ใช้: ปิดแล้วต้องไม่ต่อ IMAP ไม่แตะเมล ไม่กินโควตาเลย."""

    def test_ปิดอยู่ต้องไม่เปิด_socket_ไป_imap(self, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("ปิดอยู่แต่ยังพยายามต่อ IMAP — ผิดหลักการข้อ 1")

        monkeypatch.setattr(email_intake.imaplib, "IMAP4_SSL", explode)
        monkeypatch.setattr(email_intake, "get_setting", lambda *a, **k: {"enabled": False})
        monkeypatch.setattr(email_intake, "imap_configured", lambda: True)

        # จำลองหนึ่ง tick ของลูป: เช็คสวิตช์แล้วต้องผ่านไปเงียบ ๆ ไม่เรียก run_poll_cycle
        called: list[int] = []
        monkeypatch.setattr(email_intake, "run_poll_cycle", lambda: called.append(1))
        email_intake._stop.set()
        try:
            email_intake._loop()
        finally:
            email_intake._stop.clear()
        assert called == []

    def test_env_ไม่ครบต้องไม่สตาร์ต_worker_เลย(self, monkeypatch):
        monkeypatch.setattr(email_intake, "imap_configured", lambda: False)
        monkeypatch.setattr(email_intake, "_thread", None)
        email_intake.start_intake_worker()
        assert email_intake._thread is None

    def test_ข้อความรายงานตอนบูตบอกสาเหตุที่ปิด(self, monkeypatch):
        monkeypatch.setattr(email_intake, "imap_configured", lambda: False)
        assert "IMAP_HOST" in email_intake.intake_status_line()
