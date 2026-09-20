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
from app.hiring_board import board_stage, has_screening_conflict, is_board_eligible
from app.schemas import BoardItem, FunnelStage, StageUpdate

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT เหมือนทุก router อื่น — ทุก path ต้องล็อกอินก่อน
router = APIRouter(
    prefix="/api/v1", tags=["hiring-board"], dependencies=[Depends(get_current_user)]
)


def _schedule_patch(payload: StageUpdate) -> dict:
    """แยกว่าฟิลด์นัดสัมภาษณ์ตัวไหน "ถูกส่งมา" — ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมี DB.

    partial update ต้องแยกสามกรณีออกจากกัน:
      - ไม่ส่งฟิลด์มาเลย   → คงค่าเดิม (การลากการ์ดย้ายขั้นต้องไม่ลบวันนัดทิ้ง)
      - ส่ง null มาตรง ๆ   → ล้างค่า (ยกเลิกนัด)
      - ส่งค่ามา            → เขียนค่าใหม่
    None ตัวเดียวแยกสองกรณีแรกไม่ได้ จึงดูจาก model_fields_set ของ Pydantic
    · ใช้ COALESCE แทนไม่ได้ เพราะจะล้างวันนัดที่กรอกผิดไม่ได้เลย

    สถานที่ที่เป็นช่องว่างล้วนนับเป็นการล้างค่า ไม่ใช่เก็บสตริงว่างไว้โชว์เป็นบรรทัดเปล่า
    """
    sent = payload.model_fields_set
    location = payload.location
    if location is not None and not location.strip():
        location = None
    return {
        "set_scheduled_at": "scheduled_at" in sent,
        "scheduled_at": payload.scheduled_at,
        "set_location": "location" in sent,
        "location": location.strip() if location else None,
    }


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
                   hs.stage AS stage_row, hs.moved_at, hs.scheduled_at, hs.location,
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
        # "รับเข้าแล้ว" มาจากการมีระเบียนพนักงาน ไม่ใช่ค่าในคอลัมน์ stage —
        # board_stage ทับค่าเดิมเสมอ ไม่มีทางที่สองแหล่งจะขัดกัน
        stage = board_stage(
            r["stage_row"], r["employee_id"] is not None, r["hr_decision"], r["fit_score"]
        )
        # ⚠️ คงพฤติกรรมเดิม: ไม่เข้าเกณฑ์ = ไม่ขึ้นกระดาน แม้จะมีระเบียนพนักงาน
        if not is_board_eligible(has_row, r["hr_decision"], r["fit_score"]) or stage is None:
            continue
        board.append(
            BoardItem(
                candidate_id=r["candidate_id"],
                full_name=r["full_name"],
                fit_score=r["fit_score"],
                confidence=r["confidence"],
                stage=stage,
                employee_id=r["employee_id"],
                screening_conflict=has_screening_conflict(
                    has_row, r["hr_decision"], r["fit_score"]
                ),
                moved_at=r["moved_at"],
                email_sent_at=r["email_sent_at"],
                interview_result=r["interview_result"],
                scheduled_at=r["scheduled_at"],
                location=r["location"],
            )
        )
    return board


# ป้ายของแต่ละขั้นใน funnel เรียงจากปากกรวยลงล่าง — ลำดับนี้คือลำดับใน response
_FUNNEL_LABELS = [
    "สมัครทั้งหมด",
    "ผ่าน AI คัดกรอง",
    "เชิญแล้ว/นัดสัมภาษณ์",
    "สัมภาษณ์แล้ว",
    "รับเข้าแล้ว",
]
# ขั้นที่แปลว่า "ถูกเชิญ/นัดแล้ว" และ "สัมภาษณ์ไปแล้ว" ตามค่าในคอลัมน์ hiring_stage.stage
# ('declined' ไม่อยู่ในทั้งสองชุด — ผู้สมัครปฏิเสธก่อนถึงขั้นนั้น)
_INVITED_STAGES = {"scheduled", "interviewed", "offer"}
_INTERVIEWED_STAGES = {"interviewed", "offer"}


def _funnel_flags(
    stage_row: str | None,
    has_employee: bool,
    hr_decision: str | None,
    fit_score: int | None,
    has_outcome: bool,
) -> list[bool]:
    """ผู้สมัครหนึ่งคนถูกนับในขั้นไหนบ้าง — ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมี DB.

    คืนลิสต์ยาวเท่า _FUNNEL_LABELS · **ต้องเป็นเซตซ้อนกัน**: คนที่รับเข้าแล้วต้องถูกนับ
    ในทุกขั้นก่อนหน้าด้วย ไม่ใช่แยกกัน ไม่งั้นกรวยจะกว้างขึ้นตอนปลายซึ่งอ่านไม่รู้เรื่อง

    จึงคำนวณ **จากขั้นล่างขึ้นบน** (ขั้นบน = ขั้นล่าง or เงื่อนไขของตัวเอง) ไม่ใช่ไล่จาก
    บนลงล่างแล้ว and ทับ — ถ้า and ทับ คนที่ถูกรับเข้าเป็นพนักงานโดยไม่เคยมีแถว
    hiring_stage และคะแนนไม่ถึงเกณฑ์ จะหายไปจากทุกขั้นเงียบ ๆ (hire ไม่สร้างแถวขั้น)

    "ผ่าน AI คัดกรอง" เรียก is_board_eligible ตัวเดียวกับกระดาน ไม่ใช่เกณฑ์ชุดใหม่ —
    ตัวเลขจึงตรงกับจำนวนการ์ดบนกระดาน ยกเว้นกรณีเดียว: คนที่ถูกรับเข้าเป็นพนักงานแล้ว
    แต่ภายหลังมีคำตัดสิน "ไม่ผ่าน" กระดานซ่อนการ์ดนั้น ส่วน funnel ยังนับ เพราะขั้น
    "รับเข้าแล้ว" ต้องซ้อนอยู่ในทุกขั้นก่อนหน้าเสมอ
    """
    hired = has_employee
    interviewed = hired or stage_row in _INTERVIEWED_STAGES or has_outcome
    invited = interviewed or stage_row in _INVITED_STAGES
    screened = invited or is_board_eligible(
        stage_row is not None, hr_decision, fit_score
    )
    return [True, screened, invited, interviewed, hired]


@router.get("/jobs/{job_id}/funnel", response_model=list[FunnelStage])
def get_funnel(job_id: str) -> list[FunnelStage]:
    """สรุปจำนวนผู้สมัครของตำแหน่งนี้ในแต่ละขั้น — อ่านอย่างเดียว ไม่เขียนอะไรทั้งสิ้น.

    ใช้ข้อมูลชุดเดียวกับ GET /jobs/{id}/board แล้วนับใน Python ด้วย _funnel_flags
    ด้วยเหตุผลเดียวกับ get_board: เกณฑ์ "ใครผ่านคัดกรอง" ต้องมาจาก is_board_eligible
    ที่เดียว ถ้าเขียนเป็น WHERE fit_score > 70 ใน SQL ก็คือสำเนาเส้นแบ่งของ bands.py
    เพิ่มอีกที่ แล้ววันหนึ่ง funnel กับกระดานจะบอกคนละเลขโดยไม่มีใครรู้

    "รับเข้าแล้ว" นับจาก employees ที่ผูกกับผู้สมัครของตำแหน่งนี้ (employees.job_id
    ถูกเซ็ตจาก candidates.job_id ตอน hire อยู่แล้ว จึงเป็นชุดเดียวกัน)
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT hs.stage AS stage_row, hd.decision AS hr_decision, e.fit_score,
                   emp.id AS employee_id, io.candidate_id AS outcome_id
              FROM candidates c
              LEFT JOIN evaluations e   ON e.candidate_id = c.id
              LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
              LEFT JOIN hiring_stage hs ON hs.candidate_id = c.id
              LEFT JOIN employees emp   ON emp.candidate_id = c.id
              LEFT JOIN interview_outcome io ON io.candidate_id = c.id
             WHERE c.job_id = %s
            """,
            (job_id,),
        ).fetchall()

    counts = [0] * len(_FUNNEL_LABELS)
    for r in rows:
        flags = _funnel_flags(
            r["stage_row"],
            r["employee_id"] is not None,
            r["hr_decision"],
            r["fit_score"],
            r["outcome_id"] is not None,
        )
        for i, on in enumerate(flags):
            counts[i] += 1 if on else 0
    return [FunnelStage(label=label, count=n) for label, n in zip(_FUNNEL_LABELS, counts)]


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
            INSERT INTO hiring_stage (candidate_id, stage, note, scheduled_at, location)
            VALUES (%(cid)s, %(stage)s, %(note)s, %(scheduled_at)s, %(location)s)
            ON CONFLICT (candidate_id) DO UPDATE
               SET stage = EXCLUDED.stage,
                   note = EXCLUDED.note,
                   -- ขยับเฉพาะเมื่อย้ายขั้นจริง: บันทึกวันนัดโดยไม่ย้ายขั้นต้องไม่ทำให้
                   -- moved_at กลายเป็น "เวลาที่กรอกวันนัด" ซึ่งไม่ใช่ความหมายของคอลัมน์นี้
                   moved_at = CASE
                       WHEN hiring_stage.stage IS DISTINCT FROM EXCLUDED.stage
                       THEN timezone('utc'::text, now())
                       ELSE hiring_stage.moved_at
                   END,
                   scheduled_at = CASE WHEN %(set_scheduled_at)s
                       THEN EXCLUDED.scheduled_at ELSE hiring_stage.scheduled_at END,
                   location = CASE WHEN %(set_location)s
                       THEN EXCLUDED.location ELSE hiring_stage.location END
            RETURNING stage, moved_at, scheduled_at, location
            """,
            {
                "cid": candidate_id,
                "stage": payload.stage,
                "note": payload.note,
                **_schedule_patch(payload),
            },
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
        scheduled_at=stage_row["scheduled_at"],
        location=stage_row["location"],
    )
