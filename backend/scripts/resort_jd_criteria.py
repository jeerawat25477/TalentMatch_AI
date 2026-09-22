"""จัดฝั่งเกณฑ์ทักษะของตำแหน่งเดิมใหม่ จากป้ายที่ jd_analyzer ติดไว้ (jobs.jd_extraction).

ใช้เมื่อกติกาใน jd_analyzer.to_requirement เปลี่ยน — **ไม่เรียก LLM เลย** ไม่ต้องให้ AI อ่าน
ประกาศใหม่ เพราะป้ายดิบถูกเก็บไว้ตั้งแต่ตอนสร้างตำแหน่ง แล้วคำนวณคะแนนผู้สมัครเดิมใหม่ด้วย
criteria_edit.rescore_job ตัวเดียวกับตอน HR กดแก้เกณฑ์ (คนที่แบนด์เปลี่ยนขึ้นป้าย "ตรวจอีกครั้ง")

ข้ามตำแหน่งที่:
- HR แก้เกณฑ์เองแล้ว (criteria_edited_at ไม่ว่าง) — ห้ามทับงานของคน
- ไม่มี jd_extraction (สร้างก่อนมีคอลัมน์นี้)
- มีผู้สมัครกำลังวิเคราะห์หรือรอคิว — กราฟจะเขียนคะแนนของเกณฑ์เก่าทับ

รัน (ดูผลก่อน ไม่แก้ DB):
    docker compose exec backend python scripts/resort_jd_criteria.py
รันจริง:
    docker compose exec backend python scripts/resort_jd_criteria.py --apply
เฉพาะบางตำแหน่ง:
    docker compose exec backend python scripts/resort_jd_criteria.py --apply --job <uuid>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Json  # noqa: E402

from app.agents.models import JDExtraction  # noqa: E402
from app.agents.nodes.jd_analyzer import to_requirement  # noqa: E402
from app.criteria_edit import rescore_job  # noqa: E402
from app.database import close_pool, get_conn  # noqa: E402
from app.routers.jobs import _busy_candidates  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    only = sys.argv[sys.argv.index("--job") + 1] if "--job" in sys.argv else None
    changed = 0
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, title, raw_text, jd_extraction, parsed_criteria, criteria_edited_at
                 FROM jobs WHERE jd_extraction IS NOT NULL ORDER BY created_at"""
        ).fetchall()
        for r in rows:
            jid = str(r["id"])
            if only and jid != only:
                continue
            new = to_requirement(JDExtraction(**r["jd_extraction"]), r["raw_text"])
            cur = r["parsed_criteria"] or {}
            if (cur.get("required_skills"), cur.get("preferred_skills")) == (
                new.required_skills, new.preferred_skills
            ):
                continue
            label = f"{jid[:8]} {r['title']}"
            if r["criteria_edited_at"] is not None:
                print(f"ข้าม {label} — HR แก้เกณฑ์เองแล้ว")
                continue
            if _busy_candidates(conn, jid):
                print(f"ข้าม {label} — มีผู้สมัครกำลังวิเคราะห์หรือรอคิว")
                continue
            changed += 1
            print(f"== {label}")
            print(f"   ต้องมี  เดิม {cur.get('required_skills')}")
            print(f"          ใหม่ {new.required_skills}")
            print(f"   อยากได้ เดิม {cur.get('preferred_skills')}")
            print(f"          ใหม่ {new.preferred_skills}")
            impact = rescore_job(conn, jid, new.required_skills, new.preferred_skills, apply=apply)
            for i in impact:
                print(f"   ผู้สมัคร {i['full_name']}: {i['old_score']} → {i['new_score']}")
            if apply:
                updated = dict(cur)
                updated["required_skills"] = new.required_skills
                updated["preferred_skills"] = new.preferred_skills
                conn.execute(
                    "UPDATE jobs SET parsed_criteria = %s WHERE id = %s", (Json(updated), jid)
                )
        if apply:
            conn.commit()
    if not changed:
        print("ไม่มีตำแหน่งที่ต้องจัดฝั่งใหม่")
    else:
        print("แก้แล้ว" if apply else "ยังไม่ได้แก้ — รันด้วย --apply เพื่อแก้จริง")
    close_pool()


if __name__ == "__main__":
    main()
