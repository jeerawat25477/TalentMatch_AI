"""พิมพ์ข้อมูลเริ่มต้น (JSON) ของผู้สมัครที่มีอยู่แล้ว เพื่อวางในช่อง Input ของ LangGraph Studio.

ดึงจาก DB ด้วยคิวรีเดียวกับ queue_worker แล้วสร้าง state ด้วย `runner.initial_state`
ตัวเดียวกับตอนรันจริง — สิ่งที่เห็นใน Studio จึงตรงกับที่ระบบทำกับผู้สมัครคนนั้น

ไม่เรียก LLM ไม่แก้ DB · ผลลัพธ์มีเนื้อหาเรซูเม่ (ข้อมูลส่วนบุคคล) อย่าแปะไว้ที่สาธารณะ

รัน:
    docker compose exec backend python scripts/studio_input.py <candidate_id>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.runner import initial_state  # noqa: E402
from app.database import close_pool, get_conn  # noqa: E402


def build(row: dict, candidate_id: str) -> dict:
    """แถวจาก DB → state ตั้งต้น (แยกออกมาเพื่อทดสอบได้โดยไม่ต่อ DB)."""
    return initial_state(
        candidate_id,
        raw_jd=row["raw_text"],
        analyzed_jd=row["parsed_criteria"],
        resume_text=row["raw_resume_text"] or "",
        jd_audit=row["jd_audit"],
    )


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("ใช้: python scripts/studio_input.py <candidate_id>", file=sys.stderr)
        return 2
    cid = argv[0]
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT c.raw_resume_text, j.raw_text, j.parsed_criteria, j.jd_audit
                     FROM candidates c
                     JOIN jobs j ON j.id = c.job_id
                    WHERE c.id::text = %s""",
                (cid,),
            ).fetchone()
    finally:
        close_pool()
    if row is None:
        print(f"ไม่พบผู้สมัคร {cid}", file=sys.stderr)
        return 1
    print(json.dumps(build(row, cid), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
