"""เราเตอร์ทะเบียนพนักงาน — ผู้สมัครที่ผ่านสัมภาษณ์แล้วถูกรับเข้าทำงาน.

รับเข้า (hire) ผูกกับผู้สมัคร 1 ต่อ 1 (candidate_id UNIQUE) แล้วเก็บสถานะการจ้าง
(ทดลองงาน/ประจำ/พ้นสภาพ/พักงาน) ตำแหน่ง แผนก เงินเดือน วันเริ่มงาน ฯลฯ เป็นข้อมูลถาวร
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation

from app.auth import get_current_user
from app.database import get_conn
from app.schemas import (
    EmployeeCreate,
    EmployeeDetail,
    EmployeeListItem,
    EmployeeStatus,
    EmployeeStatusUpdate,
)

log = logging.getLogger(__name__)

# คอลัมน์ที่คืนเป็น EmployeeDetail (join job_title จาก jobs) — รวมไว้ที่เดียว
_EMP_DETAIL_COLS = """
    e.id, e.candidate_id, e.job_id, e.full_name, e.email, e.position,
    e.department, e.status, e.salary, e.start_date, e.probation_end_date,
    e.hr_notes, e.hired_at, e.updated_at, j.title AS job_title
"""

router = APIRouter(
    prefix="/api/v1", tags=["employees"], dependencies=[Depends(get_current_user)]
)


@router.post("/candidates/{candidate_id}/hire", response_model=EmployeeDetail)
def hire_candidate(candidate_id: str, payload: EmployeeCreate) -> EmployeeDetail:
    """รับผู้สมัครเข้าเป็นพนักงาน — สร้างระเบียนถาวร (1 คนได้ครั้งเดียว).

    ดึงชื่อ/อีเมล/ตำแหน่งจากผู้สมัครมา snapshot; position ว่างได้ backend เติมด้วย job.title
    """
    with get_conn() as conn:
        cand = conn.execute(
            """
            SELECT c.full_name, c.email, c.job_id, j.title AS job_title
              FROM candidates c
              LEFT JOIN jobs j ON j.id = c.job_id
             WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
        if cand is None:
            raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")

        position = (payload.position or "").strip() or cand["job_title"] or "พนักงาน"
        try:
            row = conn.execute(
                f"""
                INSERT INTO employees (
                    candidate_id, job_id, full_name, email, position,
                    department, salary, start_date, probation_end_date, hr_notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    candidate_id,
                    cand["job_id"],
                    cand["full_name"],
                    cand["email"],
                    position,
                    payload.department,
                    payload.salary,
                    payload.start_date,
                    payload.probation_end_date,
                    payload.hr_notes,
                ),
            ).fetchone()
            conn.commit()
        except UniqueViolation as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409, detail="ผู้สมัครรายนี้ถูกรับเข้าเป็นพนักงานแล้ว"
            ) from exc

    return _get_detail(str(row["id"]))


@router.get("/employees", response_model=list[EmployeeListItem])
def list_employees(status: EmployeeStatus | None = None) -> list[EmployeeListItem]:
    """รายชื่อพนักงานทั้งหมด (กรองตามสถานะได้) เรียงตามวันที่รับเข้าใหม่สุดก่อน."""
    sql = """
        SELECT id, candidate_id, full_name, position, department,
               status, start_date, hired_at
          FROM employees
    """
    params: tuple = ()
    if status is not None:
        sql += " WHERE status = %s"
        params = (status,)
    sql += " ORDER BY hired_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [EmployeeListItem(**r) for r in rows]


@router.get("/employees/{employee_id}", response_model=EmployeeDetail)
def get_employee(employee_id: str) -> EmployeeDetail:
    return _get_detail(employee_id)


@router.patch("/employees/{employee_id}/status", response_model=EmployeeDetail)
def update_employee_status(
    employee_id: str, payload: EmployeeStatusUpdate
) -> EmployeeDetail:
    """เปลี่ยนสถานะพนักงาน (เช่น ทดลองงาน→ประจำ) — note จะต่อท้ายลง hr_notes พร้อมวันที่."""
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT id FROM employees WHERE id = %s", (employee_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")

        note = (payload.note or "").strip()
        if note:
            # ต่อท้ายบันทึกใหม่พร้อม timestamp โดยไม่ทับของเดิม
            conn.execute(
                """
                UPDATE employees
                   SET status = %s,
                       hr_notes = CASE
                           WHEN hr_notes IS NULL OR hr_notes = '' THEN %s
                           ELSE hr_notes || E'\n' || %s
                       END,
                       updated_at = timezone('utc'::text, now())
                 WHERE id = %s
                """,
                (
                    payload.status,
                    f"[{_today()}] {note}",
                    f"[{_today()}] {note}",
                    employee_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE employees
                   SET status = %s, updated_at = timezone('utc'::text, now())
                 WHERE id = %s
                """,
                (payload.status, employee_id),
            )
        conn.commit()

    return _get_detail(employee_id)


def _get_detail(employee_id: str) -> EmployeeDetail:
    """ดึงระเบียนพนักงานเต็ม (join job_title) — ใช้ร่วมกันหลาย endpoint."""
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT {_EMP_DETAIL_COLS}
              FROM employees e
              LEFT JOIN jobs j ON j.id = e.job_id
             WHERE e.id = %s
            """,
            (employee_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")
    return EmployeeDetail(**row)


def _today() -> str:
    from datetime import date

    return date.today().isoformat()
