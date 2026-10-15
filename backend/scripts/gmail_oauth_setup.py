"""ตั้งค่าส่งอีเมลผ่าน Gmail API ครั้งเดียว — ขอ refresh token แล้วเขียนลง backend/.env.

ใช้เมื่อผู้ให้เช่าเครื่องบล็อกพอร์ต SMTP ขาออก (DigitalOcean บล็อก 25/465/587 ของบัญชีใหม่)
แอปจึงส่งผ่าน HTTPS พอร์ต 443 แทน (`EMAIL_TRANSPORT=gmail_api`, ดู app/email_sender.py)

รันบนเครื่องที่ deploy (ไม่ต้องลงอะไรเพิ่ม ใช้แค่ไลบรารีมาตรฐาน):

    cd /root/TalentMatch_AI
    python3 backend/scripts/gmail_oauth_setup.py
    docker compose -f docker-compose.prod.yml up -d backend

ขั้นตอน: ถาม Client ID/Secret (OAuth client แบบ Desktop app) → พิมพ์ลิงก์ให้เปิดในเบราว์เซอร์
→ ล็อกอิน Google + กดอนุญาต → เบราว์เซอร์เด้งไปหน้า 127.0.0.1 ที่เปิดไม่ขึ้น (ปกติ) →
คัดลอก URL ทั้งเส้นจากช่องที่อยู่มาวาง → สคริปต์แลกเป็น refresh token แล้วเขียน .env เอง
ความลับไม่ถูกพิมพ์ออกจอ และไม่ต้องคัดลอกไปที่อื่น

ขอสิทธิ์แค่ gmail.send (ส่งได้ อ่านกล่องไม่ได้) · ใช้ PKCE + state กันรหัสถูกสวมรอย
⚠️ แอปใน Google Cloud ต้องเป็น "In production" — ถ้าค้างที่ Testing สิทธิ์หมดทุก 7 วัน
"""
import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
# Desktop app client อนุญาต loopback ทุกพอร์ตโดยไม่ต้องลงทะเบียน · ไม่มีอะไรรอรับจริง —
# เราแค่อ่าน ?code= จาก URL ที่ผู้ใช้คัดลอกมา (เครื่อง deploy ไม่มีเบราว์เซอร์)
REDIRECT_URI = "http://127.0.0.1:8765/"

# คีย์ที่สคริปต์นี้เป็นเจ้าของใน .env — บรรทัดอื่นทุกบรรทัดคงไว้ตามเดิม
OWNED_KEYS = ("EMAIL_TRANSPORT", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def build_auth_url(client_id: str, challenge: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        # offline + consent = ได้ refresh token ทุกครั้ง แม้เคยอนุญาตไปแล้ว
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })


def parse_redirect(pasted: str, state: str) -> str:
    """ดึง code จาก URL ที่ผู้ใช้วาง — ตรวจ state และ error ที่ Google ส่งกลับ."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(pasted.strip()).query)
    if "error" in query:
        raise ValueError(f"Google ตอบว่า {query['error'][0]} (กดไม่อนุญาต หรือบัญชีไม่อยู่ในรายชื่อผู้ทดสอบ)")
    if query.get("state", [""])[0] != state:
        raise ValueError("URL นี้ไม่ใช่ของรอบนี้ (state ไม่ตรง) — เปิดลิงก์ล่าสุดแล้วลองใหม่")
    code = query.get("code", [""])[0]
    if not code:
        raise ValueError("ไม่พบ code ใน URL — คัดลอกทั้งเส้นจากช่องที่อยู่ของเบราว์เซอร์")
    return code


def update_env_text(text: str, values: dict[str, str]) -> str:
    """แทนคีย์ใน OWNED_KEYS ด้วยค่าใหม่ (ลบของเดิมทุกบรรทัด กันซ้ำ) แล้วต่อท้ายเป็นก้อนเดียว."""
    kept = [
        line for line in text.splitlines()
        if line.split("=", 1)[0].strip() not in OWNED_KEYS
    ]
    while kept and not kept[-1].strip():
        kept.pop()
    block = ["", "# Gmail API (ตั้งโดย scripts/gmail_oauth_setup.py)"]
    block += [f"{k}={values[k]}" for k in OWNED_KEYS]
    return "\n".join(kept + block) + "\n"


def write_env(path: Path, text: str) -> None:
    """เขียนไฟล์ใหม่แล้วสลับเข้าที่ — ไฟล์ไม่ขาดครึ่งทาง และไม่ทิ้งไฟล์สำรองที่มีความลับไว้."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def exchange_code(client_id: str, client_secret: str, code: str, verifier: str) -> dict:
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode()).get("error", "")
        except ValueError:
            err = ""
        raise SystemExit(f"แลก code ไม่สำเร็จ: HTTP {exc.code} {err} — Client ID/Secret ผิด หรือ code หมดอายุ ลองใหม่") from None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", default="backend/.env", help="ไฟล์ .env ที่จะเขียน (ดีฟอลต์ backend/.env)")
    args = ap.parse_args()
    env_path = Path(args.env)
    if not env_path.is_file():
        sys.exit(f"ไม่พบ {env_path} — รันจากโฟลเดอร์โปรเจกต์ (cd /root/TalentMatch_AI) ก่อน")

    print("ตั้งค่าส่งอีเมลผ่าน Gmail API — ใช้ OAuth client แบบ Desktop app จาก Google Cloud\n")
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (ไม่แสดงบนจอ): ").strip()
    if not client_id.endswith(".apps.googleusercontent.com") or not client_secret:
        sys.exit("Client ID ต้องลงท้ายด้วย .apps.googleusercontent.com และต้องมี Client Secret")

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    print("\n1) เปิดลิงก์นี้ในเบราว์เซอร์ของคุณ แล้วล็อกอินด้วยบัญชี Gmail ที่จะใช้ส่ง:\n")
    print(build_auth_url(client_id, challenge, state))
    print(
        "\n2) ถ้าเจอ \"Google hasn't verified this app\" กด Advanced → Go to ... (unsafe) — เป็นแอปของคุณเอง"
        "\n3) กดอนุญาต แล้วเบราว์เซอร์จะไปหน้า 127.0.0.1 ที่เปิดไม่ขึ้น — ปกติ"
        "\n4) คัดลอก URL ทั้งเส้นจากช่องที่อยู่ มาวางด้านล่าง (ไม่แสดงบนจอ)\n"
    )
    try:
        code = parse_redirect(getpass.getpass("วาง URL แล้วกด Enter: "), state)
    except ValueError as exc:
        sys.exit(str(exc))

    tokens = exchange_code(client_id, client_secret, code, verifier)
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("Google ไม่ส่ง refresh token มา — ลบสิทธิ์เดิมที่ myaccount.google.com/permissions แล้วลองใหม่")
    if SCOPE not in tokens.get("scope", "").split():
        sys.exit("สิทธิ์ที่ได้ไม่มี gmail.send — ตอนกดอนุญาตต้องติ๊กช่อง \"ส่งอีเมลในนามคุณ\" ด้วย")

    write_env(env_path, update_env_text(env_path.read_text(encoding="utf-8"), {
        "EMAIL_TRANSPORT": "gmail_api",
        "GMAIL_CLIENT_ID": client_id,
        "GMAIL_CLIENT_SECRET": client_secret,
        "GMAIL_REFRESH_TOKEN": refresh,
    }))
    print(
        f"\n✅ เขียนลง {env_path} แล้ว (EMAIL_TRANSPORT=gmail_api)"
        "\nให้ backend อ่านค่าใหม่:  docker compose -f docker-compose.prod.yml up -d backend"
        "\nแล้วลองส่งอีเมลหาตัวเองจากหน้าเว็บ"
    )


if __name__ == "__main__":
    main()
