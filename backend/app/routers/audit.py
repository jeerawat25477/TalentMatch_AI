"""หน้าประวัติการใช้งาน — admin เท่านั้น (บัญชีทดลองไม่ควรเห็นว่าคนอื่นทำอะไร).

ชื่อผู้สมัคร/ตำแหน่ง/พนักงาน/เทมเพลต ดึงสดจากตารางจริงตอนเปิดดู ไม่ได้เก็บใน audit_log
ของที่ถูกลบไปแล้วจึงขึ้นเป็น "(ลบแล้ว)" — ประวัติไม่เหลือข้อมูลตัวตน
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.audit import ACTION_LABELS, purge_expired
from app.auth import get_current_user, require_admin
from app.database import get_conn
from app.schemas import AuditEntry, AuditOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"], dependencies=[Depends(get_current_user)])

_TARGET_SQL = {
    "candidate": "SELECT c.full_name AS label, c.job_id::text AS job_id FROM candidates c WHERE c.id = %s",
    "job": "SELECT title AS label, id::text AS job_id FROM jobs WHERE id = %s",
    "employee": "SELECT full_name AS label, NULL AS job_id FROM employees WHERE id = %s",
    "template": "SELECT name AS label, NULL AS job_id FROM email_templates WHERE id = %s",
}


@router.get("", response_model=AuditOut, dependencies=[Depends(require_admin)])
def list_audit(
    username: Optional[str] = None,
    action: Optional[str] = None,
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(200, ge=1, le=1000),
) -> AuditOut:
    """ประวัติใหม่สุดก่อน · กรองตามคน / การกระทำ / ช่วงวัน."""
    purge_expired()
    where = ["at >= timezone('utc'::text, now()) - make_interval(days => %s)"]
    args: list = [days]
    if username:
        where.append("username = %s")
        args.append(username)
    if action:
        where.append("action = %s")
        args.append(action)

    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, at, username, action, target_type, target_id::text AS target_id,
                       detail, outcome, status_code
                FROM audit_log WHERE {' AND '.join(where)}
                ORDER BY at DESC LIMIT %s""",
            (*args, limit),
        ).fetchall()
        users = [r["username"] for r in conn.execute("SELECT DISTINCT username FROM audit_log ORDER BY 1")]

        cache: dict[tuple[str, str], Optional[dict]] = {}
        items: list[AuditEntry] = []
        for r in rows:
            label = job_id = None
            deleted = False
            key = (r["target_type"], r["target_id"])
            if r["target_type"] in _TARGET_SQL and r["target_id"]:
                if key not in cache:
                    cache[key] = conn.execute(_TARGET_SQL[r["target_type"]], (r["target_id"],)).fetchone()
                hit = cache[key]
                if hit:
                    label, job_id = hit["label"], hit["job_id"]
                else:
                    deleted = True
            items.append(AuditEntry(
                id=r["id"], at=r["at"], username=r["username"], action=r["action"],
                label=ACTION_LABELS.get(r["action"], r["action"]),
                target_type=r["target_type"], target_id=r["target_id"], target_label=label,
                target_deleted=deleted, job_id=job_id, detail=r["detail"] or {},
                outcome=r["outcome"],
            ))

    return AuditOut(
        items=items,
        users=users,
        actions=[{"key": k, "label": v} for k, v in ACTION_LABELS.items()],
    )
