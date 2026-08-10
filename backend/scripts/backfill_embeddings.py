"""สร้างเวกเตอร์ให้ resume ที่มีอยู่แล้วใน DB (ครั้งเดียวหลังเปิดใช้เลเยอร์ vector).

เรียกเฉพาะ embedding API — **ไม่แตะ chat model** จึงไม่กินโควตา generateContent
ที่ใช้ให้คะแนน/ร่างอีเมล

รัน:
    docker compose exec backend python scripts/backfill_embeddings.py
    docker compose exec backend python scripts/backfill_embeddings.py --all   # ทำซ้ำทุกคน
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import close_pool, get_conn  # noqa: E402
from app.vectors import index_candidate  # noqa: E402

PENDING = """
    SELECT c.id, c.full_name, c.raw_resume_text
    FROM candidates c
    LEFT JOIN resume_embeddings re ON re.candidate_id = c.id
    WHERE c.raw_resume_text IS NOT NULL AND c.raw_resume_text <> ''
      AND (re.candidate_id IS NULL OR %s)
    ORDER BY c.created_at
"""


def main(redo_all: bool) -> None:
    with get_conn() as conn:
        rows = conn.execute(PENDING, (redo_all,)).fetchall()

    if not rows:
        print("ไม่มีผู้สมัครที่ต้อง index (ใช้ --all เพื่อบังคับทำใหม่ทั้งหมด)")
        return

    print(f"กำลัง index {len(rows)} คน…")
    ok = 0
    for r in rows:
        try:
            index_candidate(str(r["id"]), r["raw_resume_text"])
            ok += 1
            print(f"  ✓ {r['full_name']}")
        except Exception as exc:  # noqa: BLE001 — คนที่เหลือต้องไปต่อได้
            print(f"  ✗ {r['full_name']}: {exc}")
    print(f"สำเร็จ {ok}/{len(rows)}")


if __name__ == "__main__":
    try:
        main(redo_all="--all" in sys.argv)
    finally:
        close_pool()
