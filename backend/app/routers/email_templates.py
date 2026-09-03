"""เทมเพลตอีเมลที่ HR บันทึกไว้ใช้ซ้ำ (CRUD ล้วน).

ชั้นอำนวยความสะดวกทับของเดิม — **ไม่แตะเส้นทางการส่งอีเมล**: การส่งจริงยังผ่าน
POST /api/v1/candidates/{id}/email/send + app/email_sender.py เหมือนเดิมทุกประการ
เทมเพลตแค่เติมช่อง subject/body ให้ HR แล้ว HR ยังต้องอ่าน แก้ได้ และกดยืนยันเองเสมอ
(ดู CLAUDE.md "Email send is synchronous and HR-gated")
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.database import get_conn
from app.schemas import (
    EmailKind,
    EmailTemplateDeleteOut,
    EmailTemplateIn,
    EmailTemplateOut,
)

_COLS = "id, name, kind, subject_template, body_template, created_at"

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT เหมือนทุก router อื่น — ทุก path ต้องล็อกอินก่อน
router = APIRouter(
    prefix="/api/v1/email-templates",
    tags=["email-templates"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[EmailTemplateOut])
def list_templates(
    kind: EmailKind | None = Query(None, description="กรองตามชนิดอีเมลที่กำลังร่างอยู่"),
) -> list[EmailTemplateOut]:
    """รายการเทมเพลตทั้งหมด — ส่ง ?kind= มาเพื่อเอาเฉพาะที่ตรงสถานการณ์."""
    sql = f"SELECT {_COLS} FROM email_templates"
    params: tuple = ()
    if kind:
        sql += " WHERE kind = %s"
        params = (kind,)
    sql += " ORDER BY created_at DESC"

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [EmailTemplateOut(**r) for r in rows]


@router.post("", response_model=EmailTemplateOut, status_code=201)
def create_template(payload: EmailTemplateIn) -> EmailTemplateOut:
    """บันทึกร่างที่ HR แก้ไว้เป็นเทมเพลตใหม่."""
    with get_conn() as conn:
        row = conn.execute(
            f"""INSERT INTO email_templates (name, kind, subject_template, body_template)
                VALUES (%s, %s, %s, %s) RETURNING {_COLS}""",
            (
                payload.name.strip(),
                payload.kind,
                payload.subject_template,
                payload.body_template,
            ),
        ).fetchone()
        conn.commit()
    return EmailTemplateOut(**row)


@router.delete("/{template_id}", response_model=EmailTemplateDeleteOut)
def delete_template(template_id: str) -> EmailTemplateDeleteOut:
    """ลบเทมเพลตถาวร — ไม่กระทบอีเมลที่ส่งไปแล้ว (เทมเพลตถูกคัดลอกเป็นข้อความตอนใช้).

    คืน JSON body ไม่ใช่ 204 ให้ตรงกับ DELETE ตัวอื่นในโปรเจกต์ (jobs/candidates)
    เพราะ frontend/lib/api.ts::request เรียก res.json() เสมอ 204 จะทำให้พัง
    """
    with get_conn() as conn:
        row = conn.execute(
            "DELETE FROM email_templates WHERE id = %s RETURNING id", (template_id,)
        ).fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบเทมเพลตนี้")
    return EmailTemplateDeleteOut(id=row["id"])
