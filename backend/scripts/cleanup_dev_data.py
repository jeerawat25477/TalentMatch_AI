"""เก็บกวาดข้อมูลทดสอบยุคแรกที่ค้างใน DB (ดู memory-bank/02_progress.md หัวข้อ "ค้างอยู่").

ตรวจ 3 อย่าง — **ไม่เรียก LLM เลย** จึงไม่กินโควตา Gemini:

1. job ที่ ``parsed_criteria IS NULL`` แต่มี evaluation ค้าง (คะแนนที่คำนวณจาก JD ที่แกะไม่สำเร็จ)
2. evaluation ที่ ``email_draft`` ถูก stub ทับ (``subject='s'``, ``body='b'``)
3. orphan checkpoint ของ LangGraph — thread ที่ไม่มี candidate เป็นเจ้าของแล้ว

ข้อ 1 และ 3 ลบด้วย ``--apply``; ข้อ 2 แยกออกมาเป็น ``--clear-stub-drafts`` ต่างหาก
เพราะแตะ audit trail จึงไม่ควรพ่วงไปกับ ``--apply`` โดยไม่ตั้งใจ

รัน (ดูผลก่อน ไม่แก้ DB):
    docker compose exec -T backend python scripts/cleanup_dev_data.py
รันจริง:
    docker compose exec -T backend python scripts/cleanup_dev_data.py --apply

⚠️ สำรอง DB ก่อนเสมอ:
    docker compose exec -T db pg_dump -U talentmatch -d talentmatch -F c -f /tmp/backup.dump
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import close_pool, get_checkpointer, get_conn  # noqa: E402
from app.routers.jobs import _deletion_blocker  # noqa: E402

# ตาราง checkpoint ของ LangGraph ที่มีคอลัมน์ thread_id (checkpoint_migrations ไม่มี)
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")

# job ที่แกะ JD ไม่สำเร็จ แต่ยังมี evaluation ค้าง + ตัวเลขที่ใช้ตัดสินว่าลบได้ไหม
NULL_CRITERIA_JOBS = """
    SELECT j.id, j.title, j.status, j.created_at,
           COUNT(c.id)                                   AS candidates,
           COUNT(e.id)                                   AS evaluations,
           COUNT(*) FILTER (WHERE e.email_sent_at IS NOT NULL) AS sent,
           COUNT(emp.id)                                 AS employees
      FROM jobs j
      LEFT JOIN candidates  c   ON c.job_id = j.id
      LEFT JOIN evaluations e   ON e.candidate_id = c.id
      LEFT JOIN employees   emp ON emp.candidate_id = c.id
     WHERE j.parsed_criteria IS NULL
     GROUP BY j.id, j.title, j.status, j.created_at
    HAVING COUNT(e.id) > 0
     ORDER BY j.created_at
"""

STUB_DRAFTS = """
    SELECT e.id, e.candidate_id, c.full_name, j.title AS job_title,
           e.fit_score, e.email_sent_at,
           e.email_draft->>'kind'    AS kind,
           e.email_draft->>'subject' AS subject,
           e.email_draft->>'body'    AS body
      FROM evaluations e
      JOIN candidates c ON c.id = e.candidate_id
      JOIN jobs j       ON j.id = e.job_id
     WHERE e.email_draft->>'subject' = 's' AND e.email_draft->>'body' = 'b'
     ORDER BY j.title, c.full_name
"""


def orphan_threads(conn) -> list[str]:
    """thread_id ที่ไม่มีแถวใน candidates แล้ว (thread_id = str(candidate_id))."""
    union = " UNION ".join(f"SELECT thread_id FROM {t}" for t in CHECKPOINT_TABLES)
    rows = conn.execute(
        f"""
        SELECT DISTINCT t.thread_id
          FROM ({union}) t
         WHERE NOT EXISTS (
                   SELECT 1 FROM candidates c WHERE c.id::text = t.thread_id
               )
         ORDER BY t.thread_id
        """
    ).fetchall()
    return [r["thread_id"] for r in rows]


def thread_row_counts(conn, thread_ids: list[str]) -> dict[str, int]:
    """จำนวนแถว checkpoint ของ thread ที่สนใจ แยกตามตาราง — ใช้ยืนยันผลก่อน/หลังลบ."""
    if not thread_ids:
        return {t: 0 for t in CHECKPOINT_TABLES}
    return {
        t: conn.execute(
            f"SELECT COUNT(*) AS n FROM {t} WHERE thread_id = ANY(%s)", (thread_ids,)
        ).fetchone()["n"]
        for t in CHECKPOINT_TABLES
    }


def report_null_criteria_jobs(rows) -> list[dict]:
    """พิมพ์รายการ job ที่จะลบ และคืนเฉพาะตัวที่ผ่านการ์ดทุกข้อ."""
    print("\n[1] job ที่ parsed_criteria เป็น NULL แต่มี evaluation ค้าง")
    if not rows:
        print("    — ไม่พบ")
        return []

    deletable = []
    for r in rows:
        # ใช้การ์ดตัวเดียวกับ DELETE /api/v1/jobs/{id} เพื่อไม่ให้สคริปต์หลบกฎที่ API บังคับไว้
        blocker = _deletion_blocker(r["sent"], 0, r["employees"])
        mark = "ลบได้" if blocker is None else "ข้าม"
        print(
            f"    [{mark}] {r['title'][:40]:<42} {str(r['id'])[:8]}…  "
            f"ผู้สมัคร {r['candidates']} · evaluation {r['evaluations']} · "
            f"ส่งอีเมลแล้ว {r['sent']} · พนักงาน {r['employees']}"
        )
        if blocker:
            print(f"           ↳ {blocker}")
        else:
            deletable.append(r)
    return deletable


def report_stub_drafts(rows) -> None:
    print("\n[2] evaluation ที่ email_draft ถูก stub ทับ (subject='s', body='b')")
    if not rows:
        print("    — ไม่พบ")
        return
    for r in rows:
        sent = (
            f" ⚠️ เคยส่งอีเมลแล้ว {r['email_sent_at']:%Y-%m-%d %H:%M}"
            if r["email_sent_at"]
            else ""
        )
        print(
            f"    {r['full_name'][:24]:<26} {r['job_title'][:28]:<30} "
            f"คะแนน {r['fit_score']} · kind={r['kind']}{sent}"
        )
    print(f"    รวม {len(rows)} แถว — ต้องใช้ --clear-stub-drafts ถึงจะล้าง (ตั้งเป็น NULL)")


def report_orphans(conn, threads: list[str]) -> None:
    print("\n[3] orphan checkpoint (thread ที่ไม่มี candidate เจ้าของแล้ว)")
    if not threads:
        print("    — ไม่พบ")
        return
    counts = thread_row_counts(conn, threads)
    for tid in threads:
        print(f"    {tid}")
    total = sum(counts.values())
    detail = " · ".join(f"{t}={n}" for t, n in counts.items())
    print(f"    รวม {len(threads)} thread / {total} แถว ({detail})")


def delete_jobs(rows) -> None:
    """ลบ job + cascade แล้วค่อยล้าง checkpoint — ลำดับเดียวกับ jobs.py::delete_job."""
    for r in rows:
        with get_conn() as conn:
            cids = [
                str(x["id"])
                for x in conn.execute(
                    "SELECT id FROM candidates WHERE job_id = %s", (r["id"],)
                ).fetchall()
            ]
            conn.execute("DELETE FROM jobs WHERE id = %s", (r["id"],))
            conn.commit()

        # หลัง commit เสมอ: ถ้าขั้นนี้ล้ม ก็เหลือแค่ orphan ที่ไม่มีใครอ้างถึงแล้ว
        cleared = 0
        for cid in cids:
            try:
                get_checkpointer().delete_thread(cid)
                cleared += 1
            except Exception as exc:  # noqa: BLE001 — orphan ไม่กระทบการทำงาน
                print(f"    ⚠️ ลบ checkpoint ของ {cid} ไม่สำเร็จ: {exc}")
        print(f"    ลบ '{r['title']}' แล้ว (ผู้สมัคร {len(cids)} คน, checkpoint {cleared} thread)")


def delete_orphans(threads: list[str]) -> None:
    """ลบผ่าน PostgresSaver.delete_thread เท่านั้น — ห้าม DELETE ตรงในตาราง checkpoint."""
    for tid in threads:
        try:
            get_checkpointer().delete_thread(tid)
            print(f"    ลบ thread {tid} แล้ว")
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠️ ลบ thread {tid} ไม่สำเร็จ: {exc}")


def clear_stub_drafts(rows) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE evaluations SET email_draft = NULL WHERE id = ANY(%s)",
            ([r["id"] for r in rows],),
        )
        conn.commit()
    print(f"    ล้าง email_draft แล้ว {len(rows)} แถว")


def main(apply: bool, clear_stubs: bool) -> None:
    with get_conn() as conn:
        jobs = conn.execute(NULL_CRITERIA_JOBS).fetchall()
        stubs = conn.execute(STUB_DRAFTS).fetchall()
        threads = orphan_threads(conn)

    deletable = report_null_criteria_jobs(jobs)
    report_stub_drafts(stubs)
    with get_conn() as conn:
        report_orphans(conn, threads)

    if not apply and not clear_stubs:
        print("\n(dry-run — ยังไม่แก้ DB) รันซ้ำด้วย --apply เพื่อลบข้อ 1 และ 3")
        return

    # ทะเบียน active_candidates เป็น set ในหน่วยความจำของโปรเซส backend สคริปต์นี้เป็นคนละ
    # โปรเซสจึงมองไม่เห็น — ต้องมั่นใจเองว่าไม่มีการอัปโหลด/reprocess ค้างอยู่ตอนรัน --apply
    print("\n⚠️ ตรวจให้แน่ใจว่าไม่มีการอัปโหลดเรซูเม่/วิเคราะห์ใหม่กำลังรันอยู่")

    if apply:
        print("\nกำลังลบ [1] job ที่ parsed_criteria เป็น NULL…")
        delete_jobs(deletable)

        # อ่านซ้ำหลังลบ job — cascade อาจทำให้เกิด orphan เพิ่มที่ delete_thread พลาดไป
        with get_conn() as conn:
            remaining = orphan_threads(conn)
        print("\nกำลังลบ [3] orphan checkpoint…")
        if remaining:
            delete_orphans(remaining)
        else:
            print("    — ไม่เหลือ orphan")

        with get_conn() as conn:
            left = orphan_threads(conn)
            counts = thread_row_counts(conn, left)
        print(f"    ตรวจซ้ำ: เหลือ orphan {len(left)} thread / {sum(counts.values())} แถว")

    if clear_stubs and stubs:
        print("\nกำลังล้าง [2] email_draft ที่เป็น stub…")
        clear_stub_drafts(stubs)


if __name__ == "__main__":
    try:
        main(apply="--apply" in sys.argv, clear_stubs="--clear-stub-drafts" in sys.argv)
    finally:
        close_pool()
