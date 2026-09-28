"""เติมผลตรวจอคติของประกาศ (jobs.jd_audit) ให้ตำแหน่งที่สร้างก่อนมีคอลัมน์นี้.

ตั้งแต่ 2026-09-28 ตัวตรวจอคติทำครั้งเดียวตอนสร้างตำแหน่ง แล้วผู้สมัครทุกคนอ่านผลเดียวกัน
ตำแหน่งเก่ายังไม่มีผลนี้ — ถ้าไม่เติม โหนด bias_auditor จะคำนวณด้วยกฎตายตัวใหม่ทุกผู้สมัคร
(ไม่เสียเงิน ผลก็เหมือนกัน แต่ไม่มีส่วนของ AI) สคริปต์นี้เก็บผลไว้ครั้งเดียว

- ดีฟอลต์ **กฎตายตัวอย่างเดียว ไม่เรียก LLM** ฟรี
- `--with-llm` ให้ AI ตรวจด้วย = **1 chat call ต่อตำแหน่ง** ถามเจ้าของงบก่อนรันเสมอ
- ข้ามตำแหน่งที่มี jd_audit อยู่แล้ว · ไม่แตะผลประเมินของผู้สมัครเดิม (มีผลกับคนที่วิเคราะห์ต่อจากนี้)

รัน (ดูผลก่อน ไม่แก้ DB):
    docker compose exec backend python scripts/backfill_jd_audit.py
รันจริง:
    docker compose exec backend python scripts/backfill_jd_audit.py --apply
    docker compose exec backend python scripts/backfill_jd_audit.py --apply --with-llm
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Json  # noqa: E402

from app.agents.nodes.bias_auditor import audit_jd  # noqa: E402
from app.database import close_pool, get_conn  # noqa: E402
from app.routers.jobs import _job_audit  # noqa: E402


def plan(rows: list[dict], with_llm: bool, llm=audit_jd) -> list[tuple[str, str, dict]]:
    """(job_id, title, jd_audit) ของตำแหน่งที่ยังไม่มีผลตรวจ — แยกออกมาเพื่อทดสอบได้โดยไม่ต่อ DB."""
    out = []
    for r in rows:
        if r.get("jd_audit"):
            continue
        criteria = r.get("parsed_criteria") or {}
        result = None
        if with_llm:
            try:
                result = llm(
                    r["raw_text"],
                    criteria.get("required_skills") or [],
                    criteria.get("preferred_skills") or [],
                    criteria.get("education") or "",
                    criteria.get("min_experience_years") or 0,
                )
            except Exception as exc:  # noqa: BLE001 — ตำแหน่งหนึ่งล้มไม่ควรหยุดทั้งชุด
                print(f"  ! AI ตรวจ '{r['title']}' ไม่สำเร็จ ใช้กฎอย่างเดียว: {exc}")
        out.append((str(r["id"]), r["title"], _job_audit(r["raw_text"], criteria, result)))
    return out


def main() -> None:
    apply = "--apply" in sys.argv
    with_llm = "--with-llm" in sys.argv
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, raw_text, parsed_criteria, jd_audit FROM jobs ORDER BY created_at"
        ).fetchall()
        todo = plan(rows, with_llm)
        print(f"ตำแหน่งทั้งหมด {len(rows)} · ยังไม่มีผลตรวจ {len(todo)}"
              + (" · ใช้ AI ตรวจด้วย" if with_llm else " · กฎตายตัวอย่างเดียว"))
        for job_id, title, audit in todo:
            mark = "⚠" if audit["status"] == "flagged" else "✓"
            print(f"  {mark} {title[:40]:42} {', '.join(audit['jd_criteria']) or '-'}")
            if apply:
                conn.execute("UPDATE jobs SET jd_audit = %s WHERE id = %s", (Json(audit), job_id))
        if apply:
            conn.commit()
            print(f"บันทึกแล้ว {len(todo)} ตำแหน่ง")
        else:
            print("(ยังไม่ได้บันทึก — ใส่ --apply เพื่อบันทึกจริง)")
    close_pool()


if __name__ == "__main__":
    main()
