"""จัดการบัญชีผู้ใช้จากเครื่อง (ยังไม่มีหน้าจัดการผู้ใช้บนเว็บ — มีแค่ผู้ดูแลที่สร้างบัญชี).

รันในคอนเทนเนอร์ backend (ต้องมี -it ไว้กรอกรหัสแบบไม่โชว์บนจอ):

    docker compose -f docker-compose.prod.yml exec -it backend python scripts/manage_users.py list
    ... add teacher               # บัญชีทดลอง (demo) — ดีฟอลต์
    ... add somchai --role admin  # ผู้ดูแลอีกคน
    ... passwd teacher            # เปลี่ยนรหัส
    ... role teacher admin        # เปลี่ยนสิทธิ์
    ... remove teacher            # ปิดบัญชี — token ที่ล็อกอินค้างไว้ใช้ไม่ได้ทันที

demo = ทำได้เหมือน HR ยกเว้นลบ ส่งอีเมลจริง และตั้งค่าระบบ (app/auth.py::require_admin)
ไม่ยอมลบหรือลดสิทธิ์ admin คนสุดท้าย — ไม่งั้นไม่มีใครเข้าไปตั้งค่าได้อีก
"""
import argparse
import getpass
import re
import sys

from app.auth import ROLES, hash_password
from app.database import get_conn

MIN_PASSWORD = 10
USERNAME_RE = re.compile(r"[A-Za-z0-9._-]{3,50}")


def check_username(name: str) -> str | None:
    """คืนข้อความ error หรือ None — ฟังก์ชันบริสุทธิ์ เทสต์ได้."""
    if not USERNAME_RE.fullmatch(name):
        return "ชื่อผู้ใช้ใช้ได้แค่ a-z A-Z 0-9 . _ - ยาว 3–50 ตัว"
    return None


def check_password(pw: str, again: str) -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD} ตัว"
    if pw != again:
        return "รหัสผ่านสองครั้งไม่ตรงกัน"
    return None


def leaves_no_admin(admins: list[str], username: str, new_role: str | None) -> bool:
    """การลบ (new_role=None) หรือเปลี่ยน role ครั้งนี้ทำให้ไม่เหลือ admin เลยไหม."""
    if username not in admins or new_role == "admin":
        return False
    return len(admins) <= 1


def _ask_password() -> str:
    pw = getpass.getpass("รหัสผ่าน (ไม่แสดงบนจอ): ")
    err = check_password(pw, getpass.getpass("พิมพ์อีกครั้ง: "))
    if err:
        sys.exit(err)
    return pw


def _admins(conn) -> list[str]:
    return [r["username"] for r in conn.execute("SELECT username FROM users WHERE role = 'admin'")]


def main() -> None:
    ap = argparse.ArgumentParser(description="จัดการบัญชีผู้ใช้")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("add")
    p.add_argument("username")
    p.add_argument("--role", choices=ROLES, default="demo")
    sub.add_parser("passwd").add_argument("username")
    p = sub.add_parser("role")
    p.add_argument("username")
    p.add_argument("new_role", choices=ROLES)
    sub.add_parser("remove").add_argument("username")
    args = ap.parse_args()

    with get_conn() as conn:
        if args.cmd == "list":
            for r in conn.execute("SELECT username, role, created_at FROM users ORDER BY created_at"):
                print(f"{r['username']:<20} {r['role']:<6} สร้างเมื่อ {r['created_at']:%Y-%m-%d}")
            return

        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = %s", (args.username,)
        ).fetchone() is not None

        if args.cmd == "add":
            if err := check_username(args.username):
                sys.exit(err)
            if exists:
                sys.exit(f"มีผู้ใช้ {args.username} อยู่แล้ว — เปลี่ยนรหัสใช้ passwd")
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (args.username, hash_password(_ask_password()), args.role),
            )
            conn.commit()
            print(f"✅ สร้าง {args.username} ({args.role}) แล้ว")
            return

        if not exists:
            sys.exit(f"ไม่พบผู้ใช้ {args.username}")

        if args.cmd == "passwd":
            conn.execute(
                "UPDATE users SET password_hash = %s WHERE username = %s",
                (hash_password(_ask_password()), args.username),
            )
            conn.commit()
            print(f"✅ เปลี่ยนรหัส {args.username} แล้ว")
        elif args.cmd == "role":
            if leaves_no_admin(_admins(conn), args.username, args.new_role):
                sys.exit("ลดสิทธิ์ admin คนสุดท้ายไม่ได้ — เพิ่ม admin อีกคนก่อน")
            conn.execute("UPDATE users SET role = %s WHERE username = %s", (args.new_role, args.username))
            conn.commit()
            print(f"✅ {args.username} เป็น {args.new_role} แล้ว (มีผลทันที ไม่ต้องล็อกอินใหม่)")
        elif args.cmd == "remove":
            if leaves_no_admin(_admins(conn), args.username, None):
                sys.exit("ลบ admin คนสุดท้ายไม่ได้")
            conn.execute("DELETE FROM users WHERE username = %s", (args.username,))
            conn.commit()
            print(f"✅ ปิดบัญชี {args.username} แล้ว (ที่ล็อกอินค้างอยู่จะโดนออกทันที)")


if __name__ == "__main__":
    main()
