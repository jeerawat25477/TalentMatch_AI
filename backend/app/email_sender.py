"""ส่งอีเมลผ่าน SMTP (เชิญสัมภาษณ์ / ปฏิเสธ).

Dev ใช้ MailHog (mailhog:1025, ไม่ต้อง auth) — โปรดักชัน override เป็น SMTP จริงผ่าน env
ทุกค่าอ่านจาก env ตอนส่งจริง (ไม่ cache) เพื่อให้เปลี่ยน .env แล้วมีผลโดยไม่ต้อง rebuild

หมายเหตุความปลอดภัย: ใช้ email.message.EmailMessage สร้างอีเมล ซึ่งกัน header injection
ให้ในตัว (จะไม่ยอมให้ค่า header มี CR/LF) และยัง sanitize subject อีกชั้นกันไว้แน่น
"""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


class EmailConfigError(RuntimeError):
    """ตั้งค่า SMTP ไม่ครบ — แยกจาก error ตอนส่งจริงเพื่อให้ router ตอบต่างกันได้."""


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _clean_header(value: str) -> str:
    """ตัด CR/LF ออกจากค่าที่จะไปอยู่ใน header (subject/from) — กัน header injection ชั้นสอง."""
    return value.replace("\r", " ").replace("\n", " ").strip()


def send_email(to: str, subject: str, body: str) -> None:
    """ส่งอีเมล 1 ฉบับ. โยน EmailConfigError ถ้าตั้งค่าไม่ครบ, หรือ smtplib error ถ้าส่งล้ม."""
    host = os.getenv("SMTP_HOST")
    if not host:
        raise EmailConfigError("ยังไม่ได้ตั้งค่า SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "1025"))
    sender = os.getenv("SMTP_FROM", "recruit@talentmatch.local")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    use_starttls = _env_bool("SMTP_STARTTLS")

    msg = EmailMessage()
    msg["From"] = _clean_header(sender)
    msg["To"] = _clean_header(to)
    msg["Subject"] = _clean_header(subject)
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_starttls:
            smtp.starttls()
        # auth เฉพาะเมื่อมี credential (MailHog ไม่ต้อง, Gmail ต้อง)
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)

    log.info("ส่งอีเมลถึง %s สำเร็จ (subject=%r)", to, _clean_header(subject))
