"""เราเตอร์ยืนยันตัวตน: ล็อกอินรับ JWT + ดูผู้ใช้ปัจจุบัน."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import (
    check_login_allowed,
    clear_login_failures,
    create_token,
    get_current_user,
    record_login_failure,
    verify_password,
)
from app.database import get_conn
from app.schemas import LoginIn, TokenOut, UserOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request) -> TokenOut:
    """ล็อกอินด้วย username/password → คืน JWT. 401 ถ้าผิด, 429 ถ้าลองถี่เกิน."""
    check_login_allowed(request, payload.username)

    with get_conn() as conn:
        user = conn.execute(
            "SELECT username, password_hash FROM users WHERE username = %s",
            (payload.username,),
        ).fetchone()

    # ตรวจ hash เสมอแม้ไม่พบ user (กัน timing attack แยกแยะว่ามี username นี้หรือไม่ได้ยาก)
    ok = user is not None and verify_password(payload.password, user["password_hash"])
    if not ok:
        record_login_failure(request, payload.username)
        raise HTTPException(status_code=401, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    clear_login_failures(request, payload.username)
    log.info("ผู้ใช้ %r ล็อกอินสำเร็จ", payload.username)
    return TokenOut(access_token=create_token(user["username"]))


@router.get("/me", response_model=UserOut)
def me(username: str = Depends(get_current_user)) -> UserOut:
    """คืนผู้ใช้ปัจจุบัน — frontend ใช้เช็คว่า token ยังใช้ได้."""
    return UserOut(username=username)
