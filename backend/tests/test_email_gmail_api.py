"""ส่งอีเมลผ่าน Gmail API (EMAIL_TRANSPORT=gmail_api) + สคริปต์ตั้งค่าครั้งเดียว.

ไม่ต่อเน็ตจริง: แทน urllib.request.urlopen ด้วยตัวจำลองที่จดคำขอไว้ แล้วตอบแบบ Google
"""
import base64
import io
import json
import logging
import urllib.error
import urllib.parse
from email import message_from_bytes
from email.policy import default as default_policy

import pytest

from app import email_sender
from app.email_sender import EmailConfigError, GmailApiError, send_email
from scripts import gmail_oauth_setup as setup

SECRET = "GOCSPX-super-secret"
REFRESH = "1//refresh-token-value"
ACCESS = "ya29.access-token-value"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url: str, code: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(json.dumps(body).encode()))


@pytest.fixture
def gmail_env(monkeypatch):
    monkeypatch.setenv("EMAIL_TRANSPORT", "gmail_api")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", REFRESH)
    monkeypatch.setenv("SMTP_FROM", "talentmatch.hr101@gmail.com")
    # กันพลาดไปต่อ SMTP จริงของ dev
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *a, **k: pytest.fail("ไม่ควรใช้ SMTP"))


@pytest.fixture
def google(monkeypatch):
    """ตัวจำลอง Google: token endpoint + send endpoint — ตั้ง .token_error / .send_error เพื่อจำลอง error."""
    class Google:
        calls: list = []
        token_error = None
        send_error = None

    g = Google()
    g.calls = []

    def fake_urlopen(req, timeout=None):
        assert timeout, "ต้องมี timeout ทุกคำขอ"
        g.calls.append(req)
        if req.full_url == email_sender.GMAIL_TOKEN_URL:
            if g.token_error:
                raise _http_error(req.full_url, *g.token_error)
            return FakeResp(json.dumps({"access_token": ACCESS, "expires_in": 3599}).encode())
        if req.full_url == email_sender.GMAIL_SEND_URL:
            if g.send_error:
                raise _http_error(req.full_url, *g.send_error)
            return FakeResp(b'{"id": "x"}')
        pytest.fail(f"URL ที่ไม่คาดไว้: {req.full_url}")

    monkeypatch.setattr(email_sender.urllib.request, "urlopen", fake_urlopen)
    return g


def _sent_message(g):
    send = g.calls[-1]
    raw = json.loads(send.data)["raw"]
    return send, message_from_bytes(base64.urlsafe_b64decode(raw), policy=default_policy)


class TestGmailApiSend:
    def test_sends_thai_message_with_bearer_token(self, gmail_env, google):
        send_email(to="me@example.com", subject="แจ้งผลการพิจารณา", body="เรียน คุณณัฐพงษ์\nขอบคุณครับ")

        token_req, (send_req, msg) = google.calls[0], _sent_message(google)
        form = urllib.parse.parse_qs(token_req.data.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == [REFRESH]
        assert send_req.get_header("Authorization") == f"Bearer {ACCESS}"
        assert msg["To"] == "me@example.com"
        assert msg["From"] == "talentmatch.hr101@gmail.com"
        assert msg["Subject"] == "แจ้งผลการพิจารณา"
        assert msg.get_content() == "เรียน คุณณัฐพงษ์\nขอบคุณครับ\n"

    def test_header_injection_stripped(self, gmail_env, google):
        send_email(to="me@example.com\r\nBcc: victim@example.com", subject="hi\nBcc: x@y.z", body="b")
        _, msg = _sent_message(google)
        assert msg["Bcc"] is None
        assert "\n" not in msg["Subject"] and "\n" not in msg["To"]

    def test_fresh_token_each_send(self, gmail_env, google):
        send_email(to="a@example.com", subject="s", body="b")
        send_email(to="b@example.com", subject="s", body="b")
        urls = [c.full_url for c in google.calls]
        assert urls.count(email_sender.GMAIL_TOKEN_URL) == 2

    @pytest.mark.parametrize("missing", ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"])
    def test_missing_config_is_config_error(self, gmail_env, google, monkeypatch, missing):
        monkeypatch.delenv(missing)
        with pytest.raises(EmailConfigError):
            send_email(to="a@example.com", subject="s", body="b")
        assert google.calls == []

    @pytest.mark.parametrize("err", ["invalid_grant", "invalid_client", "unauthorized_client"])
    def test_revoked_or_bad_client_is_config_error(self, gmail_env, google, err):
        google.token_error = (400, {"error": err, "error_description": "Token has been expired or revoked."})
        with pytest.raises(EmailConfigError, match="gmail_oauth_setup"):
            send_email(to="a@example.com", subject="s", body="b")
        assert len(google.calls) == 1  # ไม่ไปเรียก send ต่อ

    def test_google_server_error_on_send_is_send_error(self, gmail_env, google):
        google.send_error = (500, {"error": {"status": "INTERNAL", "message": "backend error"}})
        with pytest.raises(GmailApiError, match="HTTP 500 INTERNAL"):
            send_email(to="a@example.com", subject="s", body="b")

    def test_token_server_error_is_send_error(self, gmail_env, google):
        google.token_error = (503, {"error": "temporarily_unavailable"})
        with pytest.raises(GmailApiError):
            send_email(to="a@example.com", subject="s", body="b")

    def test_no_secrets_in_logs_or_errors(self, gmail_env, google, caplog):
        caplog.set_level(logging.DEBUG)
        send_email(to="a@example.com", subject="s", body="b")
        google.send_error = (403, {"error": {"status": "PERMISSION_DENIED", "message": "nope"}})
        with pytest.raises(GmailApiError) as ei:
            send_email(to="a@example.com", subject="s", body="b")
        text = caplog.text + str(ei.value)
        for secret in (SECRET, REFRESH, ACCESS):
            assert secret not in text
        assert ei.value.__cause__ is None and ei.value.__suppress_context__


class TestTransportSelection:
    def test_default_is_smtp(self, monkeypatch):
        monkeypatch.delenv("EMAIL_TRANSPORT", raising=False)
        monkeypatch.setenv("SMTP_HOST", "mailhog")
        # dev container มีค่า Gmail จริงใน env — ตรึงให้เป็นแบบ MailHog
        monkeypatch.setenv("SMTP_STARTTLS", "false")
        monkeypatch.delenv("SMTP_USER", raising=False)
        sent = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                sent.append(host)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def send_message(self, msg):
                sent.append(msg["To"])

        monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(email_sender.urllib.request, "urlopen", lambda *a, **k: pytest.fail("ไม่ควรใช้ Gmail API"))
        send_email(to="a@example.com", subject="s", body="b")
        assert sent == ["mailhog", "a@example.com"]

    def test_unknown_transport_is_config_error(self, monkeypatch):
        monkeypatch.setenv("EMAIL_TRANSPORT", "carrier-pigeon")
        with pytest.raises(EmailConfigError):
            send_email(to="a@example.com", subject="s", body="b")


class TestSetupScript:
    def test_auth_url_asks_send_only_offline_with_pkce(self):
        verifier, challenge = setup.pkce_pair()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(setup.build_auth_url("cid", challenge, "st")).query)
        assert q["scope"] == ["https://www.googleapis.com/auth/gmail.send"]
        assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
        assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == [challenge]
        assert verifier not in setup.build_auth_url("cid", challenge, "st")

    def test_parse_redirect(self):
        url = "http://127.0.0.1:8765/?state=st&code=4/abc&scope=x"
        assert setup.parse_redirect(url, "st") == "4/abc"
        with pytest.raises(ValueError, match="state"):
            setup.parse_redirect(url, "other")
        with pytest.raises(ValueError, match="access_denied"):
            setup.parse_redirect("http://127.0.0.1:8765/?error=access_denied&state=st", "st")
        with pytest.raises(ValueError, match="code"):
            setup.parse_redirect("http://127.0.0.1:8765/?state=st", "st")

    def test_update_env_keeps_other_lines_and_replaces_owned(self):
        before = "GOOGLE_API_KEY=k\nEMAIL_TRANSPORT=smtp\nSMTP_HOST=smtp.gmail.com\nGMAIL_REFRESH_TOKEN=old\n\n"
        values = {"EMAIL_TRANSPORT": "gmail_api", "GMAIL_CLIENT_ID": "c", "GMAIL_CLIENT_SECRET": "s",
                  "GMAIL_REFRESH_TOKEN": "new"}
        after = setup.update_env_text(before, values)
        lines = after.splitlines()
        assert "GOOGLE_API_KEY=k" in lines and "SMTP_HOST=smtp.gmail.com" in lines
        assert lines.count("EMAIL_TRANSPORT=gmail_api") == 1 and "EMAIL_TRANSPORT=smtp" not in lines
        assert "GMAIL_REFRESH_TOKEN=new" in lines and "GMAIL_REFRESH_TOKEN=old" not in lines
        # รันซ้ำได้ ไม่งอกก้อนซ้ำ
        assert setup.update_env_text(after, values).count("GMAIL_CLIENT_ID=") == 1

    def test_write_env_atomic_private(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("A=1\n")
        setup.write_env(p, "A=2\n")
        assert p.read_text() == "A=2\n"
        assert [f.name for f in tmp_path.iterdir()] == [".env"]  # ไม่ทิ้งไฟล์ชั่วคราว/สำรอง
