"""ตรวจถ้อยคำที่อาจเป็นการเลือกปฏิบัติในอีเมลก่อน HR กดส่ง — กฎ + endpoint ส่ง.

ไม่เรียก LLM และ**ไม่ส่งอีเมลจริง** (send_email ถูกแทนด้วยตัวจด)
"""
import pytest
from fastapi.testclient import TestClient

from app.agents.bias_rules import find_biased_message_phrases
from app.auth import get_current_user
from app.database import get_conn
from app.main import app


def _phrases(text: str) -> list[str]:
    return [h.phrase for h in find_biased_message_phrases(text)]


# ── กฎ ──


@pytest.mark.parametrize(
    "text, phrase",
    [
        ("เสียใจด้วย เนื่องจากอายุของท่านเกินกว่าที่ตำแหน่งกำหนด", "เนื่องจากอายุ"),
        ("ตำแหน่งนี้ต้องการผู้ที่อายุไม่เกิน 30 ปี", "อายุไม่เกิน 30 ปี"),  # กฎของประกาศใช้ด้วย
        ("อายุของคุณมากเกินไปสำหรับทีมนี้", "อายุของคุณ"),
        ("เพราะท่านเป็นผู้หญิง งานนี้จึงไม่เหมาะ", "เพราะท่านเป็นผู้หญิง"),
        ("ขอสอบถามว่าท่านแต่งงานแล้วหรือยัง", "แต่งงานแล้วหรือยัง"),
        ("มีแผนจะมีลูกในช่วงนี้ไหมคะ", "มีลูก"),
        ("ขณะนี้ตั้งครรภ์อยู่หรือไม่", "ตั้งครรภ์"),
        ("กรุณาแจ้งศาสนาของท่านมาด้วย", "ศาสนาของท่าน"),
        ("ส่วนสูงของท่านไม่ตรงตามที่กำหนด", "ส่วนสูงของท่าน"),
        ("รับเฉพาะผู้ชาย", "รับเฉพาะผู้ชาย"),
    ],
)
def test_จับถ้อยคำที่เลือกปฏิบัติ(text, phrase):
    assert phrase in _phrases(text)


@pytest.mark.parametrize(
    "text",
    [
        # สวัสดิการในอีเมลเชิญ — ไม่ใช่อคติ
        "สวัสดิการ: ประกันสุขภาพครอบคลุมครอบครัว ลาคลอด 98 วัน",
        "บริษัทมีบรรยากาศแบบครอบครัว",
        "ต้องการประสบการณ์ 3 ปีขึ้นไป · อายุงานไม่ต่ำกว่า 2 ปี",
        "เราเป็นองค์กรที่ไม่เลือกปฏิบัติ ไม่จำกัดเพศ อายุ ศาสนา",
        "ขอเชิญคุณมาสัมภาษณ์ตำแหน่ง Senior Developer (อายุงาน 5 ปี)",
        "",
    ],
)
def test_ไม่เตือนผิด(text):
    assert _phrases(text) == []


def test_เทมเพลตปฏิเสธตั้งต้นของระบบไม่ถูกเตือน():
    """ถ้าเทมเพลตของระบบเองถูกเตือน HR จะเจอหน้าต่างเตือนทุกครั้งที่ส่ง แล้วเลิกอ่านคำเตือน
    ข้อความตรงกับ frontend/lib/email-draft.ts::DEFAULT_REJECTION"""
    body = "\n".join([
        "เรียน คุณสมใจ ทดสอบ", "",
        "ขอขอบคุณที่สละเวลามาร่วมสัมภาษณ์ในตำแหน่ง Backend Developer กับเรา", "",
        "หลังจากพิจารณาอย่างรอบคอบแล้ว เราเสียใจที่ต้องแจ้งว่าในครั้งนี้เรายังไม่สามารถ"
        "ดำเนินการต่อกับใบสมัครของท่านได้", "",
        "ขอขอบคุณที่ให้ความสนใจร่วมงานกับเรา และขอให้ท่านประสบความสำเร็จในเส้นทางการทำงาน", "",
        "ขอแสดงความนับถือ", "ฝ่ายทรัพยากรบุคคล",
    ])
    assert _phrases("ผลการพิจารณาใบสมัครตำแหน่ง Backend Developer\n" + body) == []


def test_ร่างอีเมลของ_ai_ในฐานข้อมูลไม่ถูกเตือน():
    """ร่างจริงทุกฉบับที่ AI เคยเขียน — ต้องไม่มีเตือนผิด."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT email_draft FROM evaluations WHERE email_draft IS NOT NULL"
        ).fetchall()
    flagged = [
        (r["email_draft"].get("subject"), _phrases(
            f"{r['email_draft'].get('subject', '')}\n{r['email_draft'].get('body', '')}"
        ))
        for r in rows
    ]
    assert [f for f in flagged if f[1]] == []


def test_ถ้อยคำยกจากต้นฉบับตรงตัว():
    text = "เรียนคุณสมใจ เนื่องจากอายุของท่าน และท่านแต่งงานแล้ว"
    assert all(p in text for p in _phrases(text))


# ── endpoint ส่งอีเมล ──

URL = "/api/v1/candidates/{}/email/send"
OK = {"to": "cand@example.com", "subject": "เชิญสัมภาษณ์", "body": "ขอเชิญคุณมาสัมภาษณ์"}
BAD = {**OK, "body": "เสียใจด้วย เนื่องจากอายุของท่านเกินกำหนด"}


@pytest.fixture
def sent(monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr("app.routers.hr.send_email", lambda **kw: out.append(kw))
    return out


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: "hr-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def candidate():
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสอีเมลอคติ (ลบได้)", "Python"),
        ).fetchone()
        cid = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job["id"], "ผู้สมัครเทสอีเมล"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO evaluations (job_id, candidate_id, fit_score) VALUES (%s, %s, 40)",
            (job["id"], cid),
        )
        conn.commit()
    yield str(cid)
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


def _sent_count(cid: str) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COALESCE(email_send_count, 0) AS n FROM evaluations WHERE candidate_id = %s", (cid,)
        ).fetchone()["n"]


def test_ต้องล็อกอิน(candidate, sent):
    assert TestClient(app).post(URL.format(candidate), json=OK).status_code == 401
    assert sent == []


def test_อีเมลปกติส่งได้ทันที(client, candidate, sent):
    res = client.post(URL.format(candidate), json=OK)
    assert res.status_code == 200 and len(sent) == 1


def test_เจอถ้อยคำแล้วไม่ยืนยัน_409_และไม่มีอีเมลออก(client, candidate, sent):
    res = client.post(URL.format(candidate), json=BAD)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "bias_warning"
    assert [p["phrase"] for p in detail["phrases"]] == ["เนื่องจากอายุ"]
    assert sent == [] and _sent_count(candidate) == 0


def test_ยืนยันแล้วส่งได้(client, candidate, sent):
    res = client.post(URL.format(candidate), json={**BAD, "acknowledged_bias_warning": True})
    assert res.status_code == 200 and len(sent) == 1 and _sent_count(candidate) == 1


def test_ตรวจหัวข้ออีเมลด้วย(client, candidate, sent):
    res = client.post(URL.format(candidate), json={**OK, "subject": "สอบถามศาสนาของท่าน"})
    assert res.status_code == 409 and sent == []
