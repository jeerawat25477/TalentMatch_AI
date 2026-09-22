"""ซ่อมข้อความเก่าที่มีรหัสพิเศษของฟอนต์ไทย (U+F700–F71A) ค้างอยู่ในฐานข้อมูล.

ผู้สมัครที่อัปโหลดก่อน pdf_extractor แปลงรหัสพวกนี้ มีข้อความอย่าง `คอมพิวเตอร` + U+F70E
ติดอยู่ในเรซูเม่ ชื่อ และสิ่งที่ AI เขียนต่อจากนั้น (ร่างอีเมล ฯลฯ) — สคริปต์นี้แปลงด้วยตาราง
เดียวกับ app/utils/pdf_extractor.py::THAI_PUA_MAP

**ไม่เรียก LLM เลย** — แก้ข้อความในฐานข้อมูลตรง ๆ
ไล่ทุกคอลัมน์ข้อความ/JSON ในแอป (ไม่ระบุชื่อคอลัมน์ตายตัว) จะได้ไม่พลาดคอลัมน์ที่เพิ่มทีหลัง

ข้อจำกัด:
- ไม่แตะตาราง checkpoint ของ LangGraph (เก็บเป็นไบนารี) — ถ้า HR ตัดสินคนที่ซ่อมแล้วใหม่
  กราฟจะทำต่อจาก state เดิม ร่างอีเมลที่ได้อาจมีรหัสเดิมติดมาอีก
- resume_embeddings.content ถูกแก้ แต่เวกเตอร์ยังคำนวณจากข้อความเดิม (ผลค้นหาต่างกันน้อยมาก)

รัน (ดูผลก่อน ไม่แก้ DB):
    docker compose exec backend python scripts/fix_thai_pua.py
รันจริง:
    docker compose exec backend python scripts/fix_thai_pua.py --apply
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import close_pool, get_conn  # noqa: E402
from app.utils.pdf_extractor import THAI_PUA_MAP  # noqa: E402

PATTERN = "[-]"
FROM_CHARS = "".join(chr(k) for k in THAI_PUA_MAP)
TO_CHARS = "".join(THAI_PUA_MAP.values())

COLUMNS_QUERY = """
    SELECT table_name, column_name, data_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND data_type IN ('text', 'character varying', 'jsonb')
       AND table_name NOT LIKE 'checkpoint%%'
     ORDER BY table_name, column_name
"""


def repair(conn, apply: bool) -> dict[str, int]:
    """นับ (และถ้า apply ก็แก้) แถวที่มีรหัสพิเศษ ต่อคอลัมน์ — คืน {"ตาราง.คอลัมน์": จำนวนแถว}.

    ไม่ commit ให้ ผู้เรียกคุมทรานแซกชันเอง (เทสจะได้ rollback ได้)
    jsonb แปลงผ่าน text แล้วกลับเป็น jsonb — รหัสพวกนี้เป็นตัวอักษรธรรมดาใน JSON
    แทนที่ 1:1 จึงไม่ทำให้โครงสร้าง JSON เสีย
    """
    found: dict[str, int] = {}
    for col in conn.execute(COLUMNS_QUERY).fetchall():
        table, name, kind = col["table_name"], col["column_name"], col["data_type"]
        where = f'"{name}"::text ~ %s'
        n = conn.execute(
            f'SELECT count(*) AS n FROM "{table}" WHERE {where}', (PATTERN,)
        ).fetchone()["n"]
        if not n:
            continue
        found[f"{table}.{name}"] = n
        if apply:
            fixed = f'translate("{name}"::text, %s, %s)'
            if kind == "jsonb":
                fixed += "::jsonb"
            conn.execute(
                f'UPDATE "{table}" SET "{name}" = {fixed} WHERE {where}',
                (FROM_CHARS, TO_CHARS, PATTERN),
            )
    return found


def main() -> None:
    apply = "--apply" in sys.argv
    with get_conn() as conn:
        found = repair(conn, apply)
        if apply:
            conn.commit()
    if not found:
        print("ไม่พบรหัสพิเศษของฟอนต์ไทยในฐานข้อมูล")
    for key, n in found.items():
        print(f"{key}: {n} แถว")
    if found:
        print("แก้แล้ว" if apply else "ยังไม่ได้แก้ — รันด้วย --apply เพื่อแก้จริง")
    close_pool()


if __name__ == "__main__":
    main()
