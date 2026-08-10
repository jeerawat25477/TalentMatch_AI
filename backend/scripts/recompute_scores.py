"""คำนวณ fit_score / gap_analysis ของผู้สมัครเดิมใหม่ด้วย matcher ที่แก้บั๊กแล้ว.

**ไม่เรียก LLM เลย** — อ่าน jobs.parsed_criteria + candidates.parsed_resume ที่บันทึกไว้แล้ว
มาคำนวณใหม่อย่างเดียว จึงไม่กินโควตา Gemini

รัน (ดูผลก่อน ไม่แก้ DB):
    docker compose exec backend python scripts/recompute_scores.py
รันจริง:
    docker compose exec backend python scripts/recompute_scores.py --apply
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Json  # noqa: E402

from app.agents.bands import band as score_band  # noqa: E402
from app.agents.skills import is_skill, split_matched  # noqa: E402
from app.database import close_pool, get_conn  # noqa: E402

QUERY = """
    SELECT e.candidate_id, c.full_name, j.title AS job_title,
           e.fit_score AS old_score, j.parsed_criteria, c.parsed_resume,
           e.interview_plan IS NOT NULL AS has_plan,
           e.email_draft   IS NOT NULL AS has_email
    FROM evaluations e
    JOIN candidates c ON c.id = e.candidate_id
    JOIN jobs j       ON j.id = e.job_id
    WHERE j.parsed_criteria IS NOT NULL AND c.parsed_resume IS NOT NULL
    ORDER BY j.title, e.fit_score DESC
"""


LABELS = {"pass": "ผ่าน (auto)", "review": "รอ HR", "fail": "ไม่ผ่าน"}


def band(score: int | None) -> str:
    """ชื่อแบนด์ที่อ่านง่าย — เส้นแบ่งมาจาก app/agents/bands.py ที่เดียว."""
    return "ไม่มีคะแนน" if score is None else LABELS[score_band(score)]


def recompute(criteria: dict, resume: dict) -> tuple[int, dict]:
    owned = {s for s in (resume.get("skills") or []) if s and s.strip()}
    m_req, x_req = split_matched(criteria.get("required_skills") or [], owned)
    m_pref, x_pref = split_matched(criteria.get("preferred_skills") or [], owned)

    n_req, n_pref = len(m_req) + len(x_req), len(m_pref) + len(x_pref)
    score = round(
        60 * (len(m_req) / n_req if n_req else 1.0)
        + 40 * (len(m_pref) / n_pref if n_pref else 1.0)
    )
    return score, {
        "matched_required": m_req,
        "missing_required": x_req,
        "matched_preferred": m_pref,
        "missing_preferred": x_pref,
    }


def clean_criteria(apply: bool) -> None:
    """ลบคำที่ไม่ใช่ทักษะออกจาก jobs.parsed_criteria ที่บันทึกไว้แล้ว.

    matcher กรองตอนคำนวณอยู่แล้ว แต่หน้า dashboard แสดง parsed_criteria ดิบ ๆ
    ทำให้ยังเห็นชิป "product owners" ทั้งที่ไม่ถูกนับ — ล้างที่ข้อมูลให้ตรงกันทั้งสองที่
    (JD ใหม่ไม่มีปัญหานี้แล้วเพราะแก้ prompt ของ jd_analyzer ไปด้วย)
    """
    with get_conn() as conn:
        jobs = conn.execute(
            "SELECT id, title, parsed_criteria FROM jobs WHERE parsed_criteria IS NOT NULL"
        ).fetchall()

    dirty = []
    for j in jobs:
        crit = dict(j["parsed_criteria"])
        removed = []
        for key in ("required_skills", "preferred_skills"):
            original = crit.get(key) or []
            kept = [s for s in original if is_skill(s)]
            if len(kept) != len(original):
                removed += [s for s in original if not is_skill(s)]
                crit[key] = kept
        if removed:
            dirty.append((j["id"], j["title"], crit, removed))

    if not dirty:
        return

    print("\nคำที่ไม่ใช่ทักษะใน parsed_criteria:")
    for _, title, _, removed in dirty:
        print(f"   {title}: {', '.join(removed)}")

    if apply:
        with get_conn() as conn:
            for jid, _, crit, _ in dirty:
                conn.execute(
                    "UPDATE jobs SET parsed_criteria = %s WHERE id = %s", (Json(crit), jid)
                )
            conn.commit()
        print(f"ล้างแล้ว {len(dirty)} ตำแหน่ง")


def main(apply: bool) -> None:
    clean_criteria(apply)

    with get_conn() as conn:
        rows = conn.execute(QUERY).fetchall()

    changed, crossed = [], []
    print(f"{'ตำแหน่ง':<34}{'ผู้สมัคร':<26}{'เดิม':>6}{'ใหม่':>7}  แบนด์")
    print("-" * 96)

    for r in rows:
        new_score, gaps = recompute(r["parsed_criteria"], r["parsed_resume"])
        old_score = r["old_score"]
        if new_score == old_score:
            continue

        changed.append((r["candidate_id"], new_score, gaps))
        old_band, new_band = band(old_score), band(new_score)
        flag = "  ← ข้ามแบนด์" if old_band != new_band else ""
        print(
            f"{r['job_title'][:32]:<34}{r['full_name'][:24]:<26}"
            f"{old_score if old_score is not None else '-':>6}{new_score:>7}"
            f"  {old_band} → {new_band}{flag}"
        )
        if old_band != new_band and (r["has_plan"] or r["has_email"]):
            crossed.append((r["full_name"], old_band, new_band))

    print("-" * 96)
    print(f"คะแนนเปลี่ยน {len(changed)} จาก {len(rows)} คน")

    if not apply:
        print("\n(dry-run — ยังไม่แก้ DB) รันซ้ำด้วย --apply เพื่อบันทึก")
        return

    with get_conn() as conn:
        for cid, score, gaps in changed:
            conn.execute(
                "UPDATE evaluations SET fit_score = %s, gap_analysis = %s WHERE candidate_id = %s",
                (score, Json(gaps), cid),
            )
        conn.commit()
    print(f"บันทึกแล้ว {len(changed)} แถว")

    if crossed:
        # ไม่ลบ/ไม่สร้างใหม่ให้เงียบ ๆ — การสร้างใหม่ต้องเรียก LLM ซึ่งกินโควตา
        print("\n⚠️  คนเหล่านี้ข้ามแบนด์ แต่ยังมีคำถามสัมภาษณ์/อีเมลที่สร้างจากคะแนนเดิมค้างอยู่:")
        for name, ob, nb in crossed:
            print(f"   - {name}: {ob} → {nb}")
        print("   ถ้าต้องการให้ตรงกับคะแนนใหม่ ต้องอัปโหลด resume ใหม่เพื่อรันกราฟอีกรอบ (กินโควตา Gemini)")


if __name__ == "__main__":
    try:
        main(apply="--apply" in sys.argv)
    finally:
        close_pool()
