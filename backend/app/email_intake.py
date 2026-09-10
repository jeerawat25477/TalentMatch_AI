"""ปากทางรับใบสมัครทางอีเมล — worker ดึงเมลจาก IMAP แล้วป้อนเข้า pipeline เดิม.

ขอบเขตที่ห้ามเกิน: worker นี้ **"รับเข้า" อย่างเดียว ไม่ "ตอบออก"**
อีเมลตอบผู้สมัครยังต้องให้ HR อ่านและกดยืนยันเองผ่าน POST /candidates/{id}/email/send
เหมือนเดิมทุกประการ — มนุษย์คือด่านกันไม่ให้ระบบกลายเป็น spam relay
(ดู CLAUDE.md "Email send is synchronous and HR-gated") ไฟล์นี้จึงไม่ import email_sender

หลักการที่ห้ามละเมิด:
  1. **ดีฟอลต์ปิด และปิดแล้วต้องหลับสนิท** — ไม่เปิด socket ไป IMAP ไม่แตะเมล ไม่กินโควตา
     (แพตเทิร์นเดียวกับ RAG no-op) สวิตช์อยู่ใน DB จึงเปิด/ปิดสดได้ ไม่ต้องรีสตาร์ต
  2. **ห้ามเดาตำแหน่งงานด้วย LLM** — จับคู่จาก apply+<job_id>@ หรือ [job:<id>] ใน subject
     เท่านั้น จับไม่ได้ = ทิ้งไว้ในกล่อง ไม่ดึงเข้าระบบ (โควตามีวันละ 20 call ห้ามผลาญ)
  3. **อ่านอย่างเดียว** — select(readonly=True) + BODY.PEEK ไม่ mark-read ไม่ move
     ไม่ลบ ไม่ตอบ · HR ต้องเห็นเมลในกล่องเหมือนที่ไม่มีระบบนี้อยู่
  4. งานเข้ากราฟผ่าน processing_queue เสมอ — throttle/deferred_quota เดิมคุมปริมาณให้

ใช้ imaplib + email ของ stdlib ล้วน ไม่เพิ่ม dependency (หลักการเดียวกับที่เลือก
Postgres แทน Redis สำหรับคิว)
"""
import email
import imaplib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Optional
from uuid import UUID

from app.agents.runner import reserve_candidates
from app.database import get_conn
from app.job_queue import enqueue
from app.resume_ingest import (
    MAX_FILES,
    Verdict,
    admit_resume,
    existing_hashes_for_job,
)
from app.settings import get_setting, patch_setting

log = logging.getLogger(__name__)

SETTING_KEY = "email_intake"
DEFAULT_SETTING = {
    "enabled": False,
    "last_uid_seen": None,
    "uid_validity": None,
    "last_poll_at": None,
    "last_error": None,
}

IMAP_HOST = os.getenv("IMAP_HOST", "")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
IMAP_MAILBOX = os.getenv("IMAP_MAILBOX", "INBOX")
IMAP_POLL_SECONDS = int(os.getenv("IMAP_POLL_SECONDS", "120"))

# ลูปตื่นถี่กว่ารอบ poll โดยตั้งใจ: ผู้ใช้ต้องการให้สวิตช์เปิด/ปิดมีผลเกือบทันที
# ถ้าหลับยาว 120 วิ แคชค่าตั้งค่า 10 วิก็ช่วยอะไรไม่ได้ — ตื่นทุก 15 วิเพื่อ "เช็คสวิตช์"
# แต่ยิง IMAP จริงเฉพาะเมื่อเปิดอยู่ *และ* ครบรอบ poll แล้ว
_TICK_SEC = min(IMAP_POLL_SECONDS, 15)

# uuid ในรูปแบบมาตรฐาน 36 ตัวอักษร — ยังต้องเอาไปให้ UUID() ตรวจซ้ำอีกชั้น
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

# รับ plus-addressing ของกล่องใด ๆ ไม่ใช่เฉพาะกล่องชื่อ "apply"
# เดิม hardcode ไว้ว่า apply+<uuid>@ ซึ่งพังทันทีถ้า IMAP_USER ไม่ได้ชื่อ apply:
# หน้าเว็บสร้างที่อยู่จาก IMAP_USER (เช่น recruit+<uuid>@) แต่ตัวจับคู่มองหา apply+
# → ใบสมัครที่ส่งมาตามที่หน้าเว็บบอกจะถูกตีเป็น unmatched ทั้งหมดแบบเงียบ ๆ
# ทั้งสองฝั่งต้องผูกกันเสมอ (มีเทสล็อกไว้: ที่อยู่ที่ apply_address_template สร้าง
# ต้องถูก extract_job_id จับได้)
_APPLY_RE = re.compile(rf"[A-Za-z0-9._%-]+\+({_UUID})@", re.I)
_SUBJECT_RE = re.compile(rf"\[job:\s*({_UUID})\s*\]", re.I)

# header ที่อาจมีที่อยู่ปลายทางแบบ plus-addressing (Delivered-To มาก่อนเพราะเชื่อถือได้สุด:
# ผู้ส่งปลอม To/Cc ได้ แต่ Delivered-To ถูกเติมโดยเซิร์ฟเวอร์ปลายทาง)
_ADDRESS_HEADERS = ("delivered-to", "to", "cc", "x-original-to")

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def imap_configured() -> bool:
    """ตั้งค่า IMAP ครบพอจะเชื่อมต่อได้ไหม (ไม่ครบ = ฟีเจอร์นี้ปิดถาวร)."""
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def apply_address_template() -> Optional[str]:
    """ที่อยู่ที่ผู้สมัครต้องส่งเมลมา ในรูปแบบที่หน้าเว็บเติม job_id เองได้.

    เช่น IMAP_USER = "recruit@company.com" → "recruit+{job_id}@company.com"
    คืน None เมื่อยังไม่ได้ตั้ง IMAP_USER (หน้าเว็บจะซ่อนบล็อกนั้นแทนที่จะโชว์ที่อยู่พิการ)

    **ต้องมาจาก IMAP_USER แหล่งเดียวเท่านั้น ห้ามตั้งเป็นค่าคนละตัว** — ถ้าหน้าเว็บโชว์
    กล่องหนึ่งแต่ worker ดึงจากอีกกล่อง ใบสมัครจะไหลเข้ากล่องที่ไม่มีใครอ่านโดยไม่มี
    อะไรเตือนเลย เป็นความล้มเหลวแบบเงียบที่แพงที่สุดของฟีเจอร์นี้

    หมายเหตุความปลอดภัย: ที่อยู่นี้ไม่ใช่ความลับ — มันคือสิ่งที่จะถูกประกาศให้ผู้สมัคร
    ส่งเมลเข้ามา ส่วนรหัสผ่านยังไม่วิ่งผ่าน API เหมือนเดิม (ดู routers/settings.py)
    """
    if "@" not in IMAP_USER:
        return None
    local, _, domain = IMAP_USER.partition("@")
    if not local or not domain:
        return None
    return f"{local}+{{job_id}}@{domain}"


def intake_status_line() -> str:
    """ข้อความรายงานตอนบูต — แพตเทิร์นเดียวกับ tracing_status().

    ต้องบอกให้ชัดตั้งแต่บูตว่าใช้ได้ไหม ไม่งั้น HR กดสวิตช์เปิดแล้วเงียบ
    โดยไม่มีทางรู้ว่าเพราะ env ไม่ครบ
    """
    if not imap_configured():
        return (
            "ปากทางรับอีเมลปิดถาวร — ยังไม่ได้ตั้ง IMAP_HOST/IMAP_USER/IMAP_PASSWORD "
            "(ตั้งใน backend/.env แล้ว docker compose up -d backend)"
        )
    enabled = bool(get_setting(SETTING_KEY, DEFAULT_SETTING).get("enabled"))
    state = "เปิดอยู่" if enabled else "ปิดอยู่ (เปิดได้จากหน้าตั้งค่า ไม่ต้องรีสตาร์ต)"
    return f"ปากทางรับอีเมลพร้อมใช้งาน {state} → {IMAP_USER} ที่ {IMAP_HOST}:{IMAP_PORT}"


# ---------- การจับคู่ตำแหน่งงาน (ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมี IMAP) ----------


def extract_job_id(headers: dict[str, str], subject: str) -> Optional[str]:
    """หา job_id จากที่อยู่ปลายทาง apply+<uuid>@ หรือ [job:<uuid>] ใน subject.

    ลำดับความน่าเชื่อถือ: Delivered-To > To > Cc > X-Original-To > subject
    ที่อยู่ปลายทางมาก่อน subject เสมอ เพราะ subject ผู้ส่งพิมพ์อะไรก็ได้

    คืน None เมื่อจับคู่ไม่ได้ — ผู้เรียกต้องทิ้งเมลไว้ในกล่อง **ห้ามเดาด้วย LLM**
    (เปลืองโควตาที่มีวันละ 20 call และเดาผิดแปลว่าผู้สมัครไปโผล่ผิดตำแหน่ง)
    """
    lower = {(k or "").lower(): (v or "") for k, v in headers.items()}
    for name in _ADDRESS_HEADERS:
        found = _APPLY_RE.search(lower.get(name, ""))
        if found and _valid_uuid(found.group(1)):
            return found.group(1).lower()

    found = _SUBJECT_RE.search(subject or "")
    if found and _valid_uuid(found.group(1)):
        return found.group(1).lower()
    return None


def _valid_uuid(text: str) -> bool:
    try:
        UUID(text)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _decode(raw: Optional[str]) -> str:
    """แปลง header ที่เข้ารหัส MIME (=?UTF-8?B?...?=) เป็นข้อความอ่านได้.

    subject ภาษาไทยมาแบบเข้ารหัสเสมอ ถ้าไม่ถอดจะเก็บลง log เป็นขยะอ่านไม่ออก
    """
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:  # noqa: BLE001 — header เสียไม่ควรทำให้ทั้งฉบับตกไป
        return raw


def _pdf_attachments(msg) -> list[tuple[str, bytes]]:
    """ไฟล์แนบที่อาจเป็นเรซูเม่ — คัดด้วยไบต์จริงทีหลังใน admit_resume.

    ไม่กรองด้วย Content-Type ตรงนี้เพราะผู้ส่งกำหนดค่านั้นเองได้ (บางไคลเอนต์ส่ง PDF
    มาเป็น application/octet-stream ด้วย) ตัวตัดสินจริงคือ magic byte %PDF- ในด่านถัดไป
    """
    out: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() not in ("attachment", "inline"):
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("ถอดไฟล์แนบไม่สำเร็จ ข้ามไฟล์นี้: %s", exc)
            continue
        if not payload:
            continue
        out.append((_decode(part.get_filename()) or "resume.pdf", payload))
        if len(out) >= MAX_FILES:
            log.warning("อีเมลฉบับนี้แนบไฟล์เกิน %s ไฟล์ — รับเท่าเพดาน", MAX_FILES)
            break
    return out


def _log_intake(
    uid: str,
    uid_validity: Optional[str],
    from_addr: str,
    subject: str,
    outcome: str,
    detail: str = "",
    job_id: Optional[str] = None,
    candidate_id=None,
) -> None:
    """บันทึกผลของอีเมลหนึ่งฉบับ — ทั้งที่รับเข้าและที่ปฏิเสธ.

    เขียนลง DB ไม่ใช่แค่ log ไฟล์ เพราะ HR ต้องเห็นได้จากหน้าเว็บว่ามีเมลจับคู่ไม่ได้
    กี่ฉบับและเพราะอะไร โดยไม่ต้องให้ใครไปเปิด container log ให้
    """
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO email_intake_log
                   (uid, uid_validity, from_addr, subject, job_id, candidate_id,
                    outcome, detail)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    uid, uid_validity, from_addr[:320], subject[:500],
                    job_id, str(candidate_id) if candidate_id else None,
                    outcome, (detail or "")[:1000] or None,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 — log ล้มต้องไม่ทำให้การรับเมลล้มตาม
        log.warning("บันทึก email_intake_log ไม่สำเร็จ: %s", exc)


# ---------- ประมวลผลอีเมลหนึ่งฉบับ ----------

_VERDICT_OUTCOME = {
    Verdict.DUPLICATE: "duplicate",
    Verdict.UNREADABLE: "unreadable",
    Verdict.NOT_PDF: "no_attachment",
    Verdict.TOO_LARGE: "no_attachment",
}


def process_message(uid: str, raw_bytes: bytes, uid_validity: Optional[str] = None) -> str:
    """แกะอีเมลหนึ่งฉบับแล้วรับเข้าระบบถ้าผ่านทุกด่าน — คืนชื่อผลลัพธ์ที่บันทึกไว้.

    แยกออกมาจากลูป IMAP เพื่อให้ทดสอบได้ด้วยไบต์อีเมลดิบ ไม่ต้องมีเซิร์ฟเวอร์จริง
    """
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    headers = {k: str(v) for k, v in msg.items()}
    subject = _decode(msg.get("Subject"))
    from_addr = parseaddr(str(msg.get("From") or ""))[1]

    job_id = extract_job_id(headers, subject)
    if job_id is None:
        log.info("อีเมล uid=%s จาก %s จับคู่ตำแหน่งงานไม่ได้ — ทิ้งไว้ในกล่อง", uid, from_addr)
        _log_intake(uid, uid_validity, from_addr, subject, "unmatched",
                    "ไม่พบ apply+<job_id>@ ในผู้รับ และไม่พบ [job:<id>] ใน subject")
        return "unmatched"

    with get_conn() as conn:
        job = conn.execute(
            "SELECT id, status FROM jobs WHERE id = %s", (job_id,)
        ).fetchone()
    if job is None:
        log.info("อีเมล uid=%s อ้างถึงตำแหน่งงาน %s ที่ไม่มีอยู่", uid, job_id)
        _log_intake(uid, uid_validity, from_addr, subject, "unmatched",
                    f"ไม่พบตำแหน่งงาน {job_id}", job_id=job_id)
        return "unmatched"
    if job["status"] == "closed":
        # กฎเดียวกับ upload_resumes ที่ตอบ 409 เมื่องานปิดรับ — ทางเข้าสองทางต้องไม่ขัดกัน
        log.info("อีเมล uid=%s ส่งมาที่ตำแหน่งงาน %s ที่ปิดรับแล้ว", uid, job_id)
        _log_intake(uid, uid_validity, from_addr, subject, "job_closed",
                    "ตำแหน่งงานนี้ปิดรับสมัครแล้ว", job_id=job_id)
        return "job_closed"

    attachments = _pdf_attachments(msg)
    if not attachments:
        log.info("อีเมล uid=%s จาก %s ไม่มีไฟล์แนบ", uid, from_addr)
        _log_intake(uid, uid_validity, from_addr, subject, "no_attachment",
                    "ไม่มีไฟล์แนบในอีเมลฉบับนี้", job_id=job_id)
        return "no_attachment"

    accepted: list[str] = []
    last_outcome = "no_attachment"
    seen_in_batch: set[str] = set()
    with get_conn() as conn:
        existing = existing_hashes_for_job(conn, job_id)
        for filename, content in attachments:
            # ด่านชุดเดียวกับที่ HR อัปโหลดเองเป๊ะ (app/resume_ingest.py)
            verdict, candidate_id = admit_resume(
                conn, job_id, filename, content, seen_in_batch, existing
            )
            if verdict is Verdict.ACCEPTED:
                accepted.append(str(candidate_id))
                last_outcome = "matched"
                log.info(
                    "รับเรซูเม่ %s จาก %s เข้าตำแหน่งงาน %s (candidate=%s)",
                    filename, from_addr, job_id, candidate_id,
                )
                _log_intake(uid, uid_validity, from_addr, subject, "matched",
                            f"ไฟล์ {filename}", job_id=job_id, candidate_id=candidate_id)
            else:
                outcome = _VERDICT_OUTCOME.get(verdict, "error")
                if last_outcome != "matched":
                    last_outcome = outcome
                log.info("ข้ามไฟล์ %s จากอีเมล uid=%s: %s", filename, uid, verdict.value)
                _log_intake(uid, uid_validity, from_addr, subject, outcome,
                            f"ไฟล์ {filename}: {verdict.value}", job_id=job_id)
        conn.commit()

    if accepted:
        # เหมือน upload_resumes ทุกประการ: จองทะเบียนก่อน แล้วเข้าคิว ไม่ยิงเข้ากราฟตรง
        # payload บอกที่มาไว้ให้ LangSmith แยก trace ได้ (ดู runner._config)
        reserve_candidates(accepted)
        for cid in accepted:
            enqueue(cid, job_id, "process", {"source": "email"})
    return last_outcome


# ---------- ลูป IMAP ----------


def _connect() -> imaplib.IMAP4_SSL:
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    client.login(IMAP_USER, IMAP_PASSWORD)
    return client


def _uid_validity(client) -> Optional[str]:
    """UIDVALIDITY ของกล่องปัจจุบัน — UID มีความหมายเฉพาะคู่กับค่านี้เท่านั้น."""
    try:
        typ, data = client.status(IMAP_MAILBOX, "(UIDVALIDITY)")
        if typ == "OK" and data:
            found = re.search(rb"UIDVALIDITY\s+(\d+)", data[0] or b"")
            if found:
                return found.group(1).decode()
    except Exception as exc:  # noqa: BLE001 — อ่านไม่ได้ก็ยังทำงานต่อได้ แค่ระวังน้อยลง
        log.warning("อ่าน UIDVALIDITY ไม่ได้: %s", exc)
    return None


def poll_once(client, state: dict) -> dict:
    """ดึงเมลใหม่หนึ่งรอบ — คืน state ที่อัปเดตแล้ว (แยกออกมาให้เทสฉีด client ปลอมได้).

    client ต้อง select กล่องแบบ readonly มาแล้ว
    """
    validity = _uid_validity(client)
    last_uid = state.get("last_uid_seen")
    stored_validity = state.get("uid_validity")

    if validity and stored_validity and validity != stored_validity:
        # กล่องถูกสร้างใหม่/ย้ายผู้ให้บริการ — เลข UID ชุดเดิมใช้เทียบไม่ได้อีกต่อไป
        # ถ้าดันใช้ต่อ จะข้ามเมลใหม่ทั้งกล่องเงียบ ๆ หรือดูดซ้ำทั้งกล่อง
        log.warning(
            "UIDVALIDITY เปลี่ยนจาก %s เป็น %s — เริ่มนับ UID ใหม่ทั้งกล่อง",
            stored_validity, validity,
        )
        last_uid = None

    start = (int(last_uid) + 1) if last_uid else 1
    typ, data = client.uid("SEARCH", None, f"UID {start}:*")
    if typ != "OK":
        raise RuntimeError(f"IMAP SEARCH ล้มเหลว: {typ}")

    raw_ids = (data[0] or b"").split()
    # IMAP ตอบ "UID n:*" โดยคืนฉบับล่าสุดมาด้วยเสมอแม้ไม่มีของใหม่จริง
    # ถ้าไม่กรองซ้ำตรงนี้ จะประมวลผลฉบับเดิมทุกรอบ poll แล้วเสียโควตาไปเรื่อย ๆ
    uids = sorted(int(u) for u in raw_ids if int(u) >= start)

    state = dict(state)
    state["uid_validity"] = validity or stored_validity
    for uid in uids:
        try:
            # BODY.PEEK[] ไม่ใช่ BODY[] — ตัวหลังตั้งแฟล็ก \Seen ให้อัตโนมัติ
            # ซึ่งเท่ากับไปแตะสถานะเมลของ HR ทั้งที่เราสัญญาว่าอ่านอย่างเดียว
            typ, fetched = client.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not fetched or not isinstance(fetched[0], tuple):
                log.warning("ดึงอีเมล uid=%s ไม่สำเร็จ (%s) ข้ามไปก่อน", uid, typ)
                continue
            process_message(str(uid), fetched[0][1], state.get("uid_validity"))
        except Exception as exc:  # noqa: BLE001 — ฉบับเดียวพังต้องไม่พาทั้งรอบตาย
            log.exception("ประมวลผลอีเมล uid=%s ล้มเหลว: %s", uid, exc)
            _log_intake(str(uid), state.get("uid_validity"), "", "", "error", str(exc))
        # อัปเดตทีละฉบับ ไม่ใช่ท้าย batch — ถ้า worker ตายกลางทาง รอบหน้าจะได้ไม่
        # เริ่มจากศูนย์แล้วประมวลผลฉบับที่ทำไปแล้วซ้ำ (เสียโควตาและได้ผู้สมัครซ้ำ)
        state["last_uid_seen"] = str(uid)
        patch_setting(SETTING_KEY, {
            "last_uid_seen": state["last_uid_seen"],
            "uid_validity": state["uid_validity"],
        }, DEFAULT_SETTING)
    return state


def run_poll_cycle() -> None:
    """หนึ่งรอบเต็ม: ต่อ IMAP → select readonly → ดึงเมล → ปิดการเชื่อมต่อ."""
    client = None
    try:
        client = _connect()
        # readonly=True ทำให้เซิร์ฟเวอร์ไม่ยอมให้เปลี่ยนแฟล็กใด ๆ — เป็นด่านเชิงโครงสร้าง
        # ไม่ใช่แค่ "เราตั้งใจจะไม่ทำ" · HR ต้องเห็นเมลในกล่องเหมือนไม่มีระบบนี้อยู่
        typ, _ = client.select(IMAP_MAILBOX, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"เปิดกล่อง {IMAP_MAILBOX} ไม่ได้: {typ}")
        state = dict(get_setting(SETTING_KEY, DEFAULT_SETTING))
        poll_once(client, state)
        patch_setting(SETTING_KEY, {
            "last_poll_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }, DEFAULT_SETTING)
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:  # noqa: BLE001 — ปิดไม่สำเร็จก็ปล่อย socket หลุดไป
                pass


def _loop() -> None:
    last_poll = 0.0
    while not _stop.is_set():
        try:
            # เช็คสวิตช์ **ก่อน** ทุกอย่าง — ปิดอยู่คือไม่แตะ IMAP เลยแม้แต่การเปิด socket
            enabled = bool(get_setting(SETTING_KEY, DEFAULT_SETTING).get("enabled"))
            due = time.monotonic() - last_poll >= IMAP_POLL_SECONDS
            if enabled and imap_configured() and due:
                last_poll = time.monotonic()
                run_poll_cycle()
        except Exception as exc:  # noqa: BLE001 — worker ห้ามตายถาวรไม่ว่าเกิดอะไร
            log.exception("รอบดึงอีเมลล้มเหลว (จะลองใหม่รอบหน้า): %s", exc)
            try:
                patch_setting(SETTING_KEY, {"last_error": str(exc)[:500]}, DEFAULT_SETTING)
            except Exception:  # noqa: BLE001
                pass
        _stop.wait(_TICK_SEC)
    log.info("worker รับอีเมลหยุดแล้ว")


def start_intake_worker() -> None:
    """สตาร์ต worker (idempotent) — เรียกจาก lifespan ของ main.py.

    ไม่สตาร์ตเลยถ้า env ไม่ครบ: ไม่มีอะไรให้ทำ และการมีเธรดวนเปล่า ๆ ทำให้เข้าใจผิดว่า
    ระบบพร้อมทำงานทั้งที่ไม่พร้อม
    """
    global _thread
    if not imap_configured():
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="email-intake", daemon=True)
    _thread.start()
    log.info("worker รับอีเมลเริ่มทำงาน (ตื่นทุก %s วิ, ดึงเมลทุก %s วิเมื่อเปิดสวิตช์)",
             _TICK_SEC, IMAP_POLL_SECONDS)


def stop_intake_worker(timeout: float = 5.0) -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
