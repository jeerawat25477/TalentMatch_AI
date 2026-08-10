"""การเชื่อมต่อฐานข้อมูล (Supabase / PostgreSQL) และ LangGraph checkpointer.

- App tables: ใช้ psycopg connection pool (SELECT/INSERT/UPDATE ในเราเตอร์)
- Checkpointer (HITL): PostgresSaver จาก connection เดียวกัน คงอยู่ตลอดอายุแอป

ลำดับการเลือก connection string: DATABASE_URL (docker-compose/local) -> SUPABASE_DB_URL (prod)
"""
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_pool: Optional[ConnectionPool] = None
_checkpointer: Optional[PostgresSaver] = None
_checkpointer_conn: Optional[Connection] = None


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("ต้องตั้งค่า DATABASE_URL หรือ SUPABASE_DB_URL ใน .env ก่อน")
    return url


def get_pool() -> ConnectionPool:
    """คืน connection pool (สร้างครั้งแรกเมื่อถูกเรียก). แถวผลลัพธ์เป็น dict."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_db_url(),
            min_size=1,
            max_size=10,
            open=True,
            kwargs={"row_factory": dict_row},
        )
    return _pool


@contextmanager
def get_conn() -> Iterator[Connection]:
    """ยืม connection จาก pool มาใช้ในขอบเขต with (คืนอัตโนมัติเมื่อออก)."""
    with get_pool().connection() as conn:
        yield conn


def get_checkpointer() -> PostgresSaver:
    """คืน PostgresSaver สำหรับ compile กราฟ (ใช้ครั้งเดียวตอนสร้างกราฟ).

    ใช้ connection เฉพาะที่ autocommit และคงอยู่ตลอดอายุแอป — อย่าปิดระหว่างรัน
    เพราะกราฟที่ compile แล้วต้องอ่าน/เขียน checkpoint ผ่าน connection นี้ตลอด.
    """
    global _checkpointer, _checkpointer_conn
    if _checkpointer is None:
        _checkpointer_conn = Connection.connect(get_db_url(), autocommit=True)
        _checkpointer = PostgresSaver(_checkpointer_conn)
    return _checkpointer


def init_db() -> None:
    """สร้างตารางแอป (idempotent) + ตาราง checkpoint* ของ LangGraph + ผู้ใช้เริ่มต้น."""
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.execute(ddl)
        conn.commit()
    get_checkpointer().setup()
    # สร้างผู้ใช้ admin เริ่มต้นจาก env (idempotent) — import ที่นี่กัน circular import
    from app.auth import seed_admin

    seed_admin()


def close_pool() -> None:
    """ปิด pool และ connection ของ checkpointer ตอนแอปปิดตัว."""
    global _pool, _checkpointer, _checkpointer_conn
    if _pool is not None:
        _pool.close()
        _pool = None
    if _checkpointer_conn is not None:
        _checkpointer_conn.close()
        _checkpointer_conn = None
        _checkpointer = None
