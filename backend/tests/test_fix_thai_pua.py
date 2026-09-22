"""สคริปต์ซ่อมรหัสพิเศษของฟอนต์ไทยในข้อมูลเก่า (scripts/fix_thai_pua.py) — ไม่ยิง LLM.

ทุกเคสรันในทรานแซกชันเดียวแล้ว rollback ข้อมูลจริงใน DB จึงไม่ถูกแก้
"""
import importlib.util
from pathlib import Path

from psycopg.types.json import Json

from app.database import get_conn

_spec = importlib.util.spec_from_file_location(
    "fix_thai_pua", Path(__file__).resolve().parent.parent / "scripts" / "fix_thai_pua.py"
)
fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix)


def _seed(conn):
    job = conn.execute(
        "INSERT INTO jobs (title, raw_text) VALUES ('เทสซ่อมตัวอักษร (ลบได้)', 'x') RETURNING id"
    ).fetchone()["id"]
    return conn.execute(
        """INSERT INTO candidates (job_id, full_name, raw_resume_text, parsed_resume)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (
            job,
            "ปรียานนท กรุตนิด",
            "คอมพิวเตอรธุรกิจ ผูอื่น",
            Json({"full_name": "ปรียานนท", "skills": ["Excel"], "years": 0}),
        ),
    ).fetchone()["id"]


def test_ดูผลอย่างเดียวไม่แก้ข้อมูล():
    with get_conn() as conn:
        cid = _seed(conn)
        found = fix.repair(conn, apply=False)
        assert found["candidates.full_name"] >= 1
        assert found["candidates.parsed_resume"] >= 1
        name = conn.execute("SELECT full_name FROM candidates WHERE id = %s", (cid,)).fetchone()
        assert name["full_name"] == "ปรียานนท กรุตนิด"
        conn.rollback()


def test_แก้แล้วได้ตัวไทยปกติ_และ_json_ยังเป็นโครงสร้างเดิม():
    with get_conn() as conn:
        cid = _seed(conn)
        fix.repair(conn, apply=True)
        row = conn.execute(
            "SELECT full_name, raw_resume_text, parsed_resume FROM candidates WHERE id = %s",
            (cid,),
        ).fetchone()
        assert row["full_name"] == "ปรียานนท์ กรุตนิด"
        assert row["raw_resume_text"] == "คอมพิวเตอร์ธุรกิจ ผู้อื่น"
        assert row["parsed_resume"] == {"full_name": "ปรียานนท์", "skills": ["Excel"], "years": 0}
        assert fix.repair(conn, apply=False) == {}  # ไม่เหลือที่ไหนแล้ว
        conn.rollback()
