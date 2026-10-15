"""ส่งอีเมล (เชิญสัมภาษณ์ / ปฏิเสธ) — ผ่าน SMTP หรือ Gmail API เลือกด้วย EMAIL_TRANSPORT.

- `smtp` (ดีฟอลต์): dev ใช้ MailHog (mailhog:1025, ไม่ต้อง auth) หรือ SMTP จริงผ่าน env
- `gmail_api`: ส่งผ่าน HTTPS พอร์ต 443 — สำหรับเครื่องที่ผู้ให้เช่าบล็อกพอร์ต SMTP ขาออก
  (DigitalOcean บล็อก 25/465/587 ของบัญชีใหม่ พบตอนขึ้น VPS 2026-10-15) · ขอสิทธิ์แค่
  `gmail.send` (ส่งได้ อ่านกล่องไม่ได้) · ตั้งค่าครั้งเดียวด้วย `scripts/gmail_oauth_setup.py`

ทุกค่าอ่านจาก env ตอนส่งจริง (ไม่ cache) เพื่อให้เปลี่ยน .env แล้วมีผลโดยไม่ต้อง rebuild
Gmail API ขอ access token ใหม่ทุกครั้งที่ส่ง (+1 request) แทนการเก็บไว้ — HR กดส่งทีละฉบับ
นาน ๆ ครั้ง โค้ดที่ไม่มีสถานะง่ายกว่าและไม่มีจังหวะ token หมดอายุค้างอยู่ในหน่วยความจำ

หมายเหตุความปลอดภัย: ใช้ email.message.EmailMessage สร้างอีเมล ซึ่งกัน header injection
ให้ในตัว (จะไม่ยอมให้ค่า header มี CR/LF) และยัง sanitize subject อีกชั้นกันไว้แน่น ·
ทั้งสองทางส่งอีเมลที่สร้างจากฟังก์ชันเดียวกัน · ห้าม log token/secret — error ของ Google
เก็บแค่รหัสสถานะกับข้อความสั้น ๆ ของมัน
"""
import base64
import json
import logging
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

log = logging.getLogger(__name__)

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_HTTP_TIMEOUT = 15

# Google ตอบสองคำนี้เมื่อสิทธิ์/ตัวตนใช้ไม่ได้แล้ว — แก้ด้วยการตั้งค่าใหม่ ไม่ใช่กดส่งซ้ำ จึงเป็น 503
_RESETUP_HINT = (
    "ให้รัน python3 backend/scripts/gmail_oauth_setup.py บนเครื่องใหม่ "
    "(ถ้าแอปใน Google Cloud ยังเป็น Testing สิทธิ์จะหมดทุก 7 วัน — ต้องกดเผยแพร่เป็น In production)"
)


class EmailConfigError(RuntimeError):
    """ตั้งค่าอีเมลไม่ครบ/ใช้ไม่ได้ — แยกจาก error ตอนส่งจริงเพื่อให้ router ตอบต่างกันได้ (503)."""


class GmailApiError(RuntimeError):
    """Gmail API ตอบ error ตอนส่ง (ชั่วคราว/ฝั่ง Google) — router ตอบ 502 ให้ HR กดใหม่."""


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _clean_header(value: str) -> str:
    """ตัด CR/LF ออกจากค่าที่จะไปอยู่ใน header (subject/from) — กัน header injection ชั้นสอง."""
    return value.replace("\r", " ").replace("\n", " ").strip()


def _build_message(to: str, subject: str, body: str, sender: str | None) -> EmailMessage:
    msg = EmailMessage()
    if sender:
        msg["From"] = _clean_header(sender)
    msg["To"] = _clean_header(to)
    msg["Subject"] = _clean_header(subject)
    msg.set_content(body)
    return msg


def _send_smtp(to: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        raise EmailConfigError("ยังไม่ได้ตั้งค่า SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "1025"))
    sender = os.getenv("SMTP_FROM", "recruit@talentmatch.local")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    use_starttls = _env_bool("SMTP_STARTTLS")

    msg = _build_message(to, subject, body, sender)
    with smtplib.SMTP(host, port, timeout=_HTTP_TIMEOUT) as smtp:
        if use_starttls:
            smtp.starttls()
        # auth เฉพาะเมื่อมี credential (MailHog ไม่ต้อง, Gmail ต้อง)
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def _google_error(exc: urllib.error.HTTPError) -> str:
    """ข้อความ error สั้น ๆ จาก body ของ Google — token endpoint ให้ {"error": "invalid_grant"},
    Gmail API ให้ {"error": {"status": ..., "message": ...}} · ไม่มี token อยู่ในทั้งสองแบบ."""
    try:
        data = json.loads(exc.read().decode("utf-8", "replace"))
    except (ValueError, OSError):
        return ""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        return f"{err.get('status', '')} {str(err.get('message', ''))[:200]}".strip()
    return ""


def _gmail_access_token() -> str:
    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise EmailConfigError(
            "EMAIL_TRANSPORT=gmail_api แต่ยังตั้ง GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / "
            "GMAIL_REFRESH_TOKEN ไม่ครบ — " + _RESETUP_HINT
        )
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(GMAIL_TOKEN_URL, data=data), timeout=_HTTP_TIMEOUT
        ) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        err = _google_error(exc)
        # from None: ไม่พ่วง HTTPError ต้นทางไปกับ traceback ใน log
        if err in ("invalid_grant", "invalid_client", "unauthorized_client"):
            raise EmailConfigError(f"Google ปฏิเสธสิทธิ์ส่งอีเมล ({err}) — {_RESETUP_HINT}") from None
        raise GmailApiError(f"ขอ access token จาก Google ไม่สำเร็จ: HTTP {exc.code} {err}".strip()) from None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise GmailApiError("Google ไม่ส่ง access token กลับมา")
    return token


def _send_gmail_api(to: str, subject: str, body: str) -> None:
    token = _gmail_access_token()
    # From: Gmail ใช้ที่อยู่ของบัญชีที่ให้สิทธิ์เสมอ (หรือ alias ที่ยืนยันแล้ว) — ใส่ไว้ให้ชื่อตรงกับ SMTP เดิม
    msg = _build_message(to, subject, body, os.getenv("SMTP_FROM"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    req = urllib.request.Request(
        GMAIL_SEND_URL,
        data=json.dumps({"raw": raw}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT):
            pass
    except urllib.error.HTTPError as exc:
        raise GmailApiError(f"Gmail API ส่งไม่สำเร็จ: HTTP {exc.code} {_google_error(exc)}".strip()) from None


def send_email(to: str, subject: str, body: str) -> None:
    """ส่งอีเมล 1 ฉบับ. โยน EmailConfigError ถ้าตั้งค่าไม่ครบ/สิทธิ์ใช้ไม่ได้, หรือ error อื่นถ้าส่งล้ม."""
    transport = os.getenv("EMAIL_TRANSPORT", "smtp").strip().lower() or "smtp"
    if transport == "smtp":
        _send_smtp(to, subject, body)
    elif transport == "gmail_api":
        _send_gmail_api(to, subject, body)
    else:
        raise EmailConfigError(f"EMAIL_TRANSPORT ต้องเป็น smtp หรือ gmail_api (ได้ {transport!r})")

    log.info("ส่งอีเมลถึง %s สำเร็จ ผ่าน %s (subject=%r)", to, transport, _clean_header(subject))
