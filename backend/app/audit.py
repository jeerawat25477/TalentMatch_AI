"""ประวัติการใช้งาน — จดว่าใครกดเปลี่ยนข้อมูลอะไร เมื่อไร สำเร็จไหม (ตาราง audit_log).

ทำไมเป็นตัวจดกลาง (middleware) ไม่ใช่ไล่ใส่ทีละ endpoint: endpoint เดิม 31 ตัวไม่ต้องแตะเลย
และ endpoint ใหม่ถูกจดเองอัตโนมัติ · tests/test_audit.py ไล่ทุก route ที่เปลี่ยนข้อมูล ถ้าไม่อยู่ใน
ACTIONS (ชื่อภาษาคน) หรือ SKIP (แค่ดู/พรีวิว) เทสต์จะพัง — ไม่มีทางลืมตั้งชื่อ

กติกาที่ห้ามทำพัง:
- **จดพลาดต้องไม่ทำงานหลักพัง** — ทุกอย่างใน try/except แบบเดียวกับตัวนับโควตา
- **ไม่เก็บข้อมูลส่วนตัว** — detail เก็บเฉพาะคีย์ใน DETAIL_KEYS (ไม่มี salary/note/body/subject)
  ชื่อผู้สมัครไม่ลงตาราง หน้าประวัติดึงชื่อสดตอนเปิดดู ผู้สมัครถูกลบแล้วจึงไม่เหลือตัวตน
- 401 (ไม่รู้ว่าใคร) ไม่จด · 403 จดเป็น denied — อยากเห็นว่าใครพยายามทำสิ่งที่ไม่มีสิทธิ์
- งานเบื้องหลัง (คิว AI, รับสมัครทางอีเมล) ไม่ผ่าน API จึงไม่ถูกจด — ที่จดคือคนที่กดเริ่มงานนั้น
"""
import json
import logging
import re
from typing import Any, Optional

from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.auth import decode_token
from app.database import get_conn

log = logging.getLogger(__name__)

RETENTION_DAYS = 365
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# (method, path template) → ชื่อการกระทำที่คนอ่าน · ต้องครบทุก route ที่เปลี่ยนข้อมูล (เทสต์บังคับ)
ACTIONS: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/jobs"): "สร้างตำแหน่งงาน",
    ("PUT", "/api/v1/jobs/{job_id}/criteria"): "แก้เกณฑ์ตำแหน่ง",
    ("POST", "/api/v1/jobs/{job_id}/criteria/reset"): "คืนเกณฑ์ตามที่ AI อ่าน",
    ("POST", "/api/v1/jobs/{job_id}/criteria/reanalyze"): "ให้ AI อ่านประกาศใหม่",
    ("PATCH", "/api/v1/jobs/{job_id}"): "เปลี่ยนสถานะตำแหน่ง",
    ("PUT", "/api/v1/jobs/{job_id}/bias-acknowledgements"): "ยืนยัน/ถอนเรื่องอคติ",
    ("DELETE", "/api/v1/jobs/{job_id}"): "ลบตำแหน่งงาน",
    ("POST", "/api/v1/jobs/{job_id}/resumes"): "อัปเรซูเม่",
    ("DELETE", "/api/v1/candidates/{candidate_id}"): "ลบผู้สมัคร",
    ("POST", "/api/v1/candidates/{candidate_id}/reprocess"): "สั่งวิเคราะห์ใหม่",
    ("POST", "/api/v1/candidates/{candidate_id}/resume"): "ทำต่อจากที่หยุด",
    ("POST", "/api/v1/candidates/bulk-decision"): "ตัดสินหลายคน",
    ("POST", "/api/v1/candidates/{candidate_id}/decision"): "ตัดสินผู้สมัคร",
    ("PUT", "/api/v1/candidates/{candidate_id}/email/draft"): "บันทึกร่างอีเมล",
    ("DELETE", "/api/v1/candidates/{candidate_id}/email/draft"): "กลับไปใช้ร่างของ AI",
    ("POST", "/api/v1/candidates/{candidate_id}/email/send"): "ส่งอีเมล",
    ("POST", "/api/v1/candidates/{candidate_id}/hire"): "รับเข้าทำงาน",
    ("PATCH", "/api/v1/employees/{employee_id}/status"): "เปลี่ยนสถานะพนักงาน",
    ("POST", "/api/v1/email-templates"): "บันทึกเทมเพลตอีเมล",
    ("DELETE", "/api/v1/email-templates/{template_id}"): "ลบเทมเพลตอีเมล",
    ("PATCH", "/api/v1/settings/email-intake"): "ตั้งค่ารับสมัครทางอีเมล",
    ("PATCH", "/api/v1/settings/screening-photos"): "ตั้งค่าแสดงรูปผู้สมัคร",
    ("PATCH", "/api/v1/candidates/{candidate_id}/stage"): "ย้ายขั้นบนกระดาน",
    ("PUT", "/api/v1/candidates/{candidate_id}/interview-outcome"): "บันทึกผลสัมภาษณ์",
    ("PUT", "/api/v1/candidates/{candidate_id}/offer"): "ยื่นข้อเสนองาน",
    ("POST", "/api/v1/candidates/{candidate_id}/offer/response"): "บันทึกคำตอบข้อเสนองาน",
}
LOGIN = "login"
ACTION_LABELS = {**{f"{m} {p}": label for (m, p), label in ACTIONS.items()}, LOGIN: "ล็อกอิน"}

# เขียนผ่าน POST แต่ไม่ได้เปลี่ยนข้อมูล (พรีวิว/ให้ AI อ่าน) — ไม่จด · login จดเองใน routers/auth.py
SKIP: set[tuple[str, str]] = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/jobs/analyze"),
    ("POST", "/api/v1/jobs/review-jd"),
    ("POST", "/api/v1/jobs/{job_id}/criteria/preview"),
    ("POST", "/api/v1/jobs/{job_id}/bias-acknowledgements/preview"),
}

# คีย์ใน body ที่ยอมเก็บ — สั้น ไม่ใช่ข้อมูลส่วนตัว (ยกเว้น to = ผู้รับอีเมล เก็บเป็นหลักฐาน
# แบบเดียวกับ evaluations.email_sent_to) · ห้ามเพิ่ม salary / note(s) / body / subject / decline_reason
DETAIL_KEYS = ("decision", "status", "stage", "result", "response", "enabled", "to", "kind", "name")
_COUNT_KEYS = ("candidate_ids",)  # list → เก็บแค่จำนวน

_TARGETS = (("candidate_id", "candidate"), ("job_id", "job"), ("employee_id", "employee"), ("template_id", "template"))
_UUID = re.compile(r"[0-9a-fA-F-]{36}")


def pick_detail(body: Any) -> dict:
    """เลือกเฉพาะคีย์ที่อนุญาตจาก JSON body — ฟังก์ชันบริสุทธิ์ เทสต์ได้."""
    if not isinstance(body, dict):
        return {}
    out: dict = {}
    for k in DETAIL_KEYS:
        v = body.get(k)
        if isinstance(v, (str, bool, int)) and not (isinstance(v, str) and len(v) > 255):
            out[k] = v
    for k in _COUNT_KEYS:
        if isinstance(body.get(k), list):
            out["count"] = len(body[k])
    return out


def outcome_of(status: int) -> Optional[str]:
    """None = ไม่จด (401 ไม่รู้ว่าใคร)."""
    if status == 401:
        return None
    if status == 403:
        return "denied"
    return "ok" if status < 400 else "error"


def target_of(path_params: dict) -> tuple[Optional[str], Optional[str]]:
    for key, kind in _TARGETS:
        v = path_params.get(key)
        if isinstance(v, str) and _UUID.fullmatch(v):
            return kind, v
    return None, None


def record(username: str, action: str, outcome: str, *, status_code: Optional[int] = None,
           target: tuple[Optional[str], Optional[str]] = (None, None), detail: Optional[dict] = None) -> None:
    """เขียน 1 แถว — พลาดได้แต่ห้ามโยน (งานหลักต้องสำเร็จต่อไป)."""
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO audit_log (username, action, target_type, target_id, detail, outcome, status_code)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (username, action, target[0], target[1], json.dumps(detail or {}, ensure_ascii=False),
                 outcome, status_code),
            )
            conn.commit()
    except Exception:  # noqa: BLE001
        log.exception("จดประวัติการใช้งานไม่สำเร็จ (%s %s) — งานหลักไม่กระทบ", username, action)


def purge_expired() -> int:
    """ลบแถวที่เก่ากว่า RETENTION_DAYS — เรียกตอนแอปเริ่มและตอนเปิดหน้าประวัติ."""
    try:
        with get_conn() as conn:
            n = conn.execute(
                "DELETE FROM audit_log WHERE at < timezone('utc'::text, now()) - make_interval(days => %s)",
                (RETENTION_DAYS,),
            ).rowcount
            conn.commit()
        return n
    except Exception:  # noqa: BLE001
        log.exception("ลบประวัติการใช้งานที่หมดอายุไม่สำเร็จ")
        return 0


def _api_routes(routes) -> list[APIRoute]:
    """FastAPI 0.14x เก็บ router ที่ include ไว้เป็น _IncludedRouter (มี original_router)."""
    out: list[APIRoute] = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):
            out += _api_routes(r.original_router.routes)
    return out


class AuditMiddleware(BaseHTTPMiddleware):
    """จดทุกคำขอที่เปลี่ยนข้อมูล หลังได้คำตอบแล้ว (รู้ผลว่าสำเร็จ/ถูกกัน)."""

    def __init__(self, app, routes_provider):
        super().__init__(app)
        self._routes_provider = routes_provider
        self._table: Optional[list[tuple[str, Any, str]]] = None

    def _match(self, method: str, path: str) -> tuple[Optional[str], dict]:
        if self._table is None:  # สร้างครั้งแรกที่ใช้ — ตอน add_middleware ยังไม่มี route ครบ
            self._table = [
                (m, r.path_regex, r.path) for r in _api_routes(self._routes_provider()) for m in r.methods
            ]
        for m, rx, template in self._table:
            if m == method:
                hit = rx.match(path)
                if hit:
                    return template, hit.groupdict()
        return None, {}

    async def dispatch(self, request: Request, call_next):
        method = request.method
        if method not in WRITE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)

        username = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                username = decode_token(auth[7:].strip())
            except Exception:  # noqa: BLE001 — token เสีย = endpoint ตอบ 401 เอง ไม่จด
                username = None

        detail: dict = {}
        if username and request.headers.get("content-type", "").startswith("application/json"):
            try:
                detail = pick_detail(json.loads(await request.body() or b"null"))
            except Exception:  # noqa: BLE001 — body เสีย endpoint ตอบ 422 เอง
                detail = {}

        response = await call_next(request)

        if username:
            template, params = self._match(method, request.url.path)
            outcome = outcome_of(response.status_code)
            if template and outcome and (method, template) not in SKIP:
                await run_in_threadpool(
                    record, username, f"{method} {template}", outcome,
                    status_code=response.status_code, target=target_of(params), detail=detail,
                )
        return response
