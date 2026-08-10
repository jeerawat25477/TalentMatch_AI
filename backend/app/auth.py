"""ระบบยืนยันตัวตน: hash รหัสผ่าน (bcrypt) + JWT + dependency กัน endpoint.

security review (memory-bank/04_security.md) ชี้ว่าไม่มี auth คือความเสี่ยงสูงสุด —
ไฟล์นี้ปิดช่องนั้น ทุก endpoint (ยกเว้น /health, /auth/login) ต้องมี Bearer token ที่ถูกต้อง

หมายเหตุ: JWT_SECRET ต้องตั้งใน env — ถ้าไม่มีจะโยน error ตอนเรียกใช้ ไม่ยอมรันต่อ
เพราะ secret ดีฟอลต์ที่ hardcode ไว้ = ใครก็ปลอม token ได้
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_conn

log = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "12"))

# rate-limit login กัน brute force (in-memory) — โปรดักชันจริงควรใช้ Redis (ระบุใน 04_security.md)
_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "5"))
_WINDOW_SEC = int(os.getenv("LOGIN_FAIL_WINDOW_SEC", "300"))
_fails: dict[str, list[float]] = {}

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("ต้องตั้งค่า JWT_SECRET ใน env ก่อน (ไม่มีค่าดีฟอลต์เพื่อความปลอดภัย)")
    return secret


# ---------- รหัสผ่าน ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------
def create_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> str:
    """คืน username จาก token — โยน jwt error ถ้า token ปลอม/หมดอายุ."""
    payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    username = payload.get("sub")
    if not username:
        raise jwt.InvalidTokenError("token ไม่มี subject")
    return username


# ---------- rate-limit ----------
def _client_key(request: Request, username: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{username}"


def check_login_allowed(request: Request, username: str) -> None:
    """โยน 429 ถ้า (IP+username) นี้ล็อกอินผิดถี่เกินเพดานในหน้าต่างเวลา."""
    key = _client_key(request, username)
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < _WINDOW_SEC]
    _fails[key] = recent
    if len(recent) >= _MAX_FAILS:
        raise HTTPException(status_code=429, detail="ลองล็อกอินผิดถี่เกินไป กรุณารอสักครู่")


def record_login_failure(request: Request, username: str) -> None:
    _fails.setdefault(_client_key(request, username), []).append(time.time())


def clear_login_failures(request: Request, username: str) -> None:
    _fails.pop(_client_key(request, username), None)


# ---------- dependency กัน endpoint ----------
def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """ตรวจ Bearer token → คืน username. โยน 401 ถ้าไม่มี/ผิด/ผู้ใช้ถูกลบไปแล้ว."""
    if creds is None:
        raise HTTPException(status_code=401, detail="ต้องเข้าสู่ระบบก่อน")
    try:
        username = decode_token(creds.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="โทเคนไม่ถูกต้อง") from exc

    with get_conn() as conn:
        user = conn.execute(
            "SELECT username FROM users WHERE username = %s", (username,)
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="ไม่พบผู้ใช้นี้แล้ว")
    return username


# ---------- seed admin ----------
def seed_admin() -> None:
    """สร้างผู้ใช้แรกจาก env (idempotent) — เรียกใน init_db()."""
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        log.warning("ไม่ได้ตั้ง ADMIN_USERNAME/ADMIN_PASSWORD — ข้ามการสร้างผู้ใช้เริ่มต้น")
        return
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (username, password_hash) VALUES (%s, %s)
               ON CONFLICT (username) DO NOTHING""",
            (username, hash_password(password)),
        )
        conn.commit()
    log.info("ตรวจสอบผู้ใช้เริ่มต้น %r แล้ว (สร้างถ้ายังไม่มี)", username)
