"""แตกถ้อยคำอคติที่ถูกรวมเป็นก้อนเดียวใน jobs.jd_audit ให้เป็นทีละเรื่อง — **ไม่เรียก LLM**.

เดิม merge_criteria เก็บข้อของ LLM เมื่อทับกับกฎ แล้ว LLM รวม "เพศหญิง อายุไม่เกิน 35 ปี"
เป็นข้อเดียว HR ที่ยืนยันว่า "จำเป็นกับงานนี้" จึงยืนยันทั้งเพศและอายุในครั้งเดียวโดยไม่ตั้งใจ
(เจอจากการลองจริง 2026-09-28) ตรรกะใหม่ใช้ถ้อยคำของกฎเป็นหน่วยหลัก สคริปต์นี้ใช้ตรรกะเดียวกัน
กับตำแหน่งที่สร้างไปแล้ว: เอาถ้อยคำที่เก็บไว้เป็น "ข้อของ LLM" + กฎที่คำนวณใหม่จากประกาศ

**การยืนยันเดิมของถ้อยคำที่ถูกแตกจะไม่มีผลอีก** — ไม่เดาแทนว่าเหตุผลที่ HR พิมพ์ไว้หมายถึงเรื่องไหน
บันทึกเดิมยังอยู่ใน bias_acknowledgements (bias_view มองข้ามถ้อยคำที่ไม่อยู่ในผลตรวจแล้ว)
HR ต้องยืนยันใหม่แยกข้อที่หน้าตำแหน่ง

รัน (ดูผลก่อน ไม่แก้ DB):
    docker compose exec backend python scripts/resplit_jd_criteria.py
รันจริง:
    docker compose exec backend python scripts/resplit_jd_criteria.py --apply
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Json  # noqa: E402

from app.agents.bias_rules import find_biased_phrases, merge_criteria  # noqa: E402
from app.database import close_pool, get_conn  # noqa: E402

_WARN = "⚠ เกณฑ์ใน JD ที่อาจมีอคติ (ไม่ได้ถูกใช้คิดคะแนน — ควรแก้ประกาศ): "


def resplit(audit: dict | None, raw_text: str) -> dict | None:
    """ผลตรวจฉบับที่แตกถ้อยคำแล้ว — None = ไม่ต้องเปลี่ยน (ฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต่อ DB)."""
    if not audit:
        return None
    old = list(audit.get("jd_criteria") or [])
    new = merge_criteria(old, find_biased_phrases(raw_text or ""), raw_text or "")
    if new == old:
        return None
    # บรรทัด ⚠ สร้างจากรายการ — ตัดของเดิมทิ้งแล้วต่อใหม่ ข้อความส่วนบน (คำอธิบาย) คงเดิม
    head = (audit.get("log") or "").split("\n⚠", 1)[0].rstrip()
    log = f"{head}\n{_WARN}{', '.join(new)}".strip() if new else head
    return {**audit, "jd_criteria": new, "log": log}


def main() -> None:
    apply = "--apply" in sys.argv
    changed = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, raw_text, jd_audit, bias_acknowledgements FROM jobs ORDER BY created_at"
        ).fetchall()
        for r in rows:
            fixed = resplit(r["jd_audit"], r["raw_text"])
            if fixed is None:
                continue
            changed += 1
            print(f"  {r['title'][:40]}")
            print(f"    เดิม: {r['jd_audit']['jd_criteria']}")
            print(f"    ใหม่: {fixed['jd_criteria']}")
            stale = [a["phrase"] for a in (r["bias_acknowledgements"] or [])
                     if a.get("phrase") not in fixed["jd_criteria"]]
            if stale:
                print(f"    ! การยืนยันที่จะไม่มีผลแล้ว (ต้องยืนยันใหม่แยกข้อ): {stale}")
            if apply:
                conn.execute("UPDATE jobs SET jd_audit = %s WHERE id = %s", (Json(fixed), r["id"]))
        if apply:
            conn.commit()
    print(f"ตำแหน่งที่ต้องแตกถ้อยคำ {changed} จาก {len(rows)}"
          + ("" if apply else " (ยังไม่ได้บันทึก — ใส่ --apply เพื่อบันทึกจริง)"))
    close_pool()


if __name__ == "__main__":
    main()
