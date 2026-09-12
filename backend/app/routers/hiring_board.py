"""เราเตอร์กระดานติดตามผู้สมัคร — เลเยอร์ติดตามที่อ่านผลของกราฟอย่างเดียว.

**ไม่แตะกราฟเลย**: ไม่ import graph/runner/nodes ไม่เรียก LLM ไม่เขียนอะไรกลับเข้า
state ของกราฟ · อ่านผลที่กราฟทิ้งไว้ใน evaluations/hr_decisions แล้วเก็บ "ขั้นตอน
ที่ HR ดำเนินไปถึง" ไว้ในตาราง hiring_stage ของตัวเอง

ด้วยเหตุนี้จึง **ไม่เช็ค runner.active_candidates()** ต่างจากการตัดสินหรือการลบ —
การ์ดขยับระหว่างที่กราฟกำลังรันอยู่ไม่กระทบอะไรทั้งสิ้น การบล็อกไว้จะกลายเป็นการห้าม
HR กดโดยไม่มีเหตุผลที่อธิบายได้
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.database import get_conn
from app.hiring_board import has_screening_conflict, is_board_eligible
from app.schemas import BoardItem, StageUpdate

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT เหมือนทุก router อื่น — ทุก path ต้องล็อกอินก่อน
router = APIRouter(
    prefix="/api/v1", tags=["hiring-board"], dependencies=[Depends(get_current_user)]
)


@router.get("/jobs/{job_id}/board", response_model=list[BoardItem])
def get_board(job_id: str) -> list[BoardItem]:
    """การ์ดทั้งหมดบนกระดานของตำแหน่งงานนี้ เรียงตามคะแนนมาก -> น้อย.

    ⚠️ **อ่านอย่างเดียว ห้าม INSERT แถว hiring_stage ที่นี่** คนที่ยังไม่เคยถูกย้ายขั้น
    คืน stage='invited' แบบคำนวณ แถวจริงเกิดตอน PATCH ครั้งแรกเท่านั้น
    ถ้าสร้างแถวตอน GET (write-on-read) moved_at จะกลายเป็น "เวลาที่ HR เปิดหน้า"
    แทนที่จะเป็นเวลาที่ย้ายขั้นจริง แล้วคอลัมน์นั้นก็ไม่เหลือความหมายอะไร

    การกรองว่าใครขึ้นกระดานทำใน Python ผ่าน is_board_eligible ไม่ใช่ใน WHERE —
    ถ้ากรองใน SQL ต้องเขียน `fit_score > 70` ลงไป ซึ่งคือการสำเนาเส้นแบ่งจาก
    agents/bands.py เพิ่มอีกที่หนึ่ง (บทเรียนเดิม: เลข 50/70 เคยกระจาย 6 ที่)
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id AS candidate_id, c.full_name,
                   e.fit_score, e.confidence, e.email_sent_at,
                   hd.decision AS hr_decision,
                   hs.stage AS stage_row, hs.moved_at,
                   emp.id AS employee_id, io.result AS interview_result
              FROM candidates c
              LEFT JOIN evaluations e   ON e.candidate_id = c.id
              LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
              LEFT JOIN hiring_stage hs ON hs.candidate_id = c.id
              LEFT JOIN employees emp   ON emp.candidate_id = c.id
              LEFT JOIN interview_outcome io ON io.candidate_id = c.id
             WHERE c.job_id = %s
             ORDER BY e.fit_score DESC NULLS LAST, c.created_at ASC
            """,
            (job_id,),
        ).fetchall()

    board: list[BoardItem] = []
    for r in rows:
        has_row = r["stage_row"] is not None
        if not is_board_eligible(has_row, r["hr_decision"], r["fit_score"]):
            continue
        board.append(
            BoardItem(
                candidate_id=r["candidate_id"],
                full_name=r["full_name"],
                fit_score=r["fit_score"],
                confidence=r["confidence"],
                # "รับเข้าแล้ว" มาจากการมีระเบียนพนักงาน ไม่ใช่ค่าในคอลัมน์ stage —
                # จึงทับค่าเดิมเสมอ ไม่มีทางที่สองแหล่งจะขัดกัน
                stage="hired" if r["employee_id"] else (r["stage_row"] or "invited"),
                employee_id=r["employee_id"],
                screening_conflict=has_screening_conflict(
                    has_row, r["hr_decision"], r["fit_score"]
                ),
                moved_at=r["moved_at"],
                email_sent_at=r["email_sent_at"],
                interview_result=r["interview_result"],
            )
        )
    return board


@router.patch("/candidates/{candidate_id}/stage", response_model=BoardItem)
def update_stage(candidate_id: str, payload: StageUpdate) -> BoardItem:
    """ย้ายการ์ดไปขั้นอื่น — สร้างแถวให้อัตโนมัติถ้ายังไม่มี.

    ลำดับด่าน: 404 ไม่พบผู้สมัคร -> 400 ขอย้ายเป็น 'hired' -> 409 ถูกจ้างไปแล้ว
    400 มาก่อน 409 เพราะเป็นเรื่องของค่าที่ส่งมาผิดตั้งแต่ต้น และข้อความของมันชี้ทางออก
    ที่ถูกต้องให้อยู่แล้ว ส่วน 409 เป็นเรื่องสถานะเฉพาะของคนคนนั้น
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT c.id, c.full_name, e.fit_score, e.confidence, e.email_sent_at,
                   hd.decision AS hr_decision, emp.id AS employee_id,
                   -- ⚠️ ต้องมีที่นี่ด้วย ไม่ใช่แค่ใน get_board แม้หน้ากระดานตอนนี้จะทิ้ง
                   -- response ของ PATCH แล้ว revalidate เอาก็ตาม: ทั้งสองเส้นทางประกาศ
                   -- response_model เดียวกันคือ BoardItem ถ้าอันหนึ่งคืนฟิลด์ไม่ครบ
                   -- ก็เป็นกับดักรอผู้เรียกรายต่อไปที่เชื่อสัญญาแล้วเอาไปวาดการ์ดตรง ๆ
                   io.result AS interview_result
              FROM candidates c
              LEFT JOIN evaluations e   ON e.candidate_id = c.id
              LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
              LEFT JOIN employees emp   ON emp.candidate_id = c.id
              LEFT JOIN interview_outcome io ON io.candidate_id = c.id
             WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")

        if payload.stage == "hired":
            # "รับเข้าแล้ว" ไม่ใช่ขั้นบนกระดาน แต่เป็นการสร้างระเบียนพนักงานถาวร
            # ซึ่งต้องกรอกตำแหน่ง/เงินเดือน/วันเริ่มงาน จึงมีเอนด์พอยต์ของตัวเอง
            raise HTTPException(
                status_code=400,
                detail=(
                    "ย้ายขั้นเป็น 'รับเข้าแล้ว' ที่นี่ไม่ได้ — "
                    "ใช้ปุ่มรับเข้าเป็นพนักงาน (POST /api/v1/candidates/{id}/hire) แทน"
                ),
            )
        if row["employee_id"] is not None:
            # ย้ายคนที่จ้างไปแล้วกลับไปขั้นก่อนหน้าไม่สมเหตุสมผล — ถ้าจะแก้ต้องไปจัดการ
            # ที่ระเบียนพนักงาน (เช่น เปลี่ยนสถานะเป็น terminated)
            raise HTTPException(
                status_code=409,
                detail="ผู้สมัครรายนี้ถูกรับเข้าเป็นพนักงานแล้ว — แก้ไขได้ที่ระเบียนพนักงาน",
            )

        stage_row = conn.execute(
            """
            INSERT INTO hiring_stage (candidate_id, stage, note)
            VALUES (%s, %s, %s)
            ON CONFLICT (candidate_id) DO UPDATE
               SET stage = EXCLUDED.stage,
                   note = EXCLUDED.note,
                   moved_at = timezone('utc'::text, now())
            RETURNING stage, moved_at
            """,
            (candidate_id, payload.stage, payload.note),
        ).fetchone()
        conn.commit()

    log.info("ย้ายผู้สมัคร %s ไปขั้น %s", candidate_id, payload.stage)
    return BoardItem(
        candidate_id=row["id"],
        full_name=row["full_name"],
        fit_score=row["fit_score"],
        confidence=row["confidence"],
        stage=stage_row["stage"],
        employee_id=None,  # ผ่านด่าน 409 มาแล้ว จึงไม่มีทางเป็นพนักงาน
        # มีแถวแน่นอนแล้ว ณ จุดนี้ (เพิ่ง upsert) จึงส่ง has_stage_row=True
        screening_conflict=has_screening_conflict(
            True, row["hr_decision"], row["fit_score"]
        ),
        moved_at=stage_row["moved_at"],
        email_sent_at=row["email_sent_at"],
        interview_result=row["interview_result"],
    )
