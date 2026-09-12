"""เราเตอร์บันทึกผลสัมภาษณ์จริง — ทางเข้าเดียวที่มนุษย์เป็นคนกรอกล้วน ๆ.

กราฟร่างคำถามให้ HR ไว้ใน `evaluations.interview_plan` แล้วหน้าที่ของมันจบตรงนั้น
ไฟล์นี้เก็บสิ่งที่เกิดขึ้น **หลังจาก** คนไปนั่งสัมภาษณ์กันมาจริง ๆ ซึ่งเป็นข้อมูลชุดเดียว
ที่บอกได้ว่าคะแนนของ AI แม่นแค่ไหน — วัตถุดิบของเฟส 5 calibration

**ไม่ import อะไรจาก agents/ เลย ไม่เรียก LLM แม้แต่ครั้งเดียว** เหมือน hiring_board.py

❗ **ห้ามเขียน hr_decisions จากที่นี่เด็ดขาด** สองอย่างนี้ตอบคนละคำถาม:
`hr_decisions.decision` = "ให้ผ่านไปสัมภาษณ์ไหม" ซึ่ง agents/graph.py::route_candidates
อ่านไปเลือกเส้นทางของกราฟ · `interview_outcome.result` = "สัมภาษณ์แล้วเป็นยังไง"
ถ้าเอาอันหลังไปเขียนทับอันแรก กราฟจะถูกปลุกให้ตัดสินใหม่โดยไม่มีใครสั่ง แล้วตัดสินจาก
ข้อมูลที่มันไม่เคยเห็น — ผู้สมัครที่สัมภาษณ์ไม่ผ่านจะถูกร่างอีเมลปฏิเสธส่งออกเองเงียบ ๆ
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Json

from app.auth import get_current_user
from app.database import get_conn
from app.schemas import InterviewOutcome, InterviewOutcomeUpsert

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT เหมือนทุก router อื่น
router = APIRouter(
    prefix="/api/v1", tags=["interview-outcome"], dependencies=[Depends(get_current_user)]
)

# ขั้นที่ถือว่า "ยังมาไม่ถึงการสัมภาษณ์" จึงเลื่อนขึ้นมาได้เมื่อมีผลสัมภาษณ์เข้ามา
_ADVANCE_FROM = ("invited", "scheduled")


def _next_stage_after_outcome(current: Optional[str]) -> Optional[str]:
    """ขั้นใหม่ที่ควรย้ายไป หรือ None ถ้าไม่ต้องแตะ hiring_stage เลย.

    ฟังก์ชันบริสุทธิ์ตามแพตเทิร์นเดียวกับ hiring_board.is_board_eligible และ
    candidates._is_stalled — ทดสอบทุกกิ่งได้โดยไม่ต้องมีฐานข้อมูล

    กฎคือ **เลื่อนขึ้นได้อย่างเดียว ห้ามย้อน**:
    - ไม่มีแถว / invited / scheduled -> 'interviewed' (HR ทำงานเดียวได้สองอย่าง
      ไม่ต้องกลับไปลากการ์ดซ้ำอีกรอบ)
    - interviewed -> None ไม่ต้องเขียนซ้ำให้ moved_at ขยับเปล่า ๆ
    - offer -> None การบันทึกผลย้อนหลังต้องไม่ดึงคนที่ยื่นข้อเสนอไปแล้วกลับมา
    - declined -> None อยู่นอกบันได ถ้าลากกลับมาเท่ากับปลุกการ์ดที่ HR จงใจพักไว้
    """
    return "interviewed" if current is None or current in _ADVANCE_FROM else None


@router.put(
    "/candidates/{candidate_id}/interview-outcome", response_model=InterviewOutcome
)
def upsert_interview_outcome(
    candidate_id: str, payload: InterviewOutcomeUpsert
) -> InterviewOutcome:
    """บันทึก (หรือแก้ไข) ผลสัมภาษณ์ของผู้สมัครหนึ่งคน — หนึ่งคนหนึ่งผล.

    เป็น PUT ไม่ใช่ POST เพราะ upsert: ยิงซ้ำด้วยเนื้อเดียวกันได้ผลเท่าเดิมเสมอ
    (candidate_id เป็น PRIMARY KEY แบบเดียวกับ hr_decisions/employees/hiring_stage)

    **ไม่บล็อกคนที่ถูกจ้างไปแล้ว** ต่างจาก PATCH /stage ที่ตอบ 409 — บันทึกประวัติ
    ย้อนหลังควรทำได้ และกฎห้ามย้อนขั้นด้านบนกันไม่ให้การ์ดของเขาถูกดึงกลับอยู่แล้ว
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT c.id, hs.stage
              FROM candidates c
              LEFT JOIN hiring_stage hs ON hs.candidate_id = c.id
             WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")

        saved = conn.execute(
            """
            INSERT INTO interview_outcome
                   (candidate_id, result, question_scores, overall_note, interviewed_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (candidate_id) DO UPDATE
               SET result = EXCLUDED.result,
                   question_scores = EXCLUDED.question_scores,
                   overall_note = EXCLUDED.overall_note,
                   interviewed_at = EXCLUDED.interviewed_at,
                   updated_at = timezone('utc'::text, now())
            RETURNING result, question_scores, overall_note, interviewed_at,
                      created_at, updated_at
            """,
            (
                candidate_id,
                payload.result,
                Json([q.model_dump() for q in payload.question_scores]),
                payload.overall_note,
                payload.interviewed_at,
            ),
        ).fetchone()

        next_stage = _next_stage_after_outcome(row["stage"])
        if next_stage is not None:
            # อยู่ในทรานแซกชันเดียวกับการบันทึกผล — ถ้าอันใดอันหนึ่งล้ม ต้องไม่เหลือ
            # สภาพครึ่ง ๆ ที่การ์ดย้ายแล้วแต่ไม่มีผล หรือมีผลแต่การ์ดยังค้างที่เดิม
            conn.execute(
                """
                INSERT INTO hiring_stage (candidate_id, stage)
                VALUES (%s, %s)
                ON CONFLICT (candidate_id) DO UPDATE
                   SET stage = EXCLUDED.stage,
                       moved_at = timezone('utc'::text, now())
                """,
                (candidate_id, next_stage),
            )
        conn.commit()

    log.info(
        "บันทึกผลสัมภาษณ์ %s = %s (ขั้น: %s)",
        candidate_id,
        payload.result,
        next_stage or f"คงเดิมที่ {row['stage']}",
    )
    return InterviewOutcome(**saved)
