"""เทสหน่วยของระบบ auth — hash รหัสผ่าน + JWT round-trip.

รัน: docker compose exec backend python -m pytest tests/test_auth.py -v
(ต้องมี JWT_SECRET ใน env — docker-compose ตั้งให้แล้ว)
"""
import time

import jwt
import pytest

from app import auth


class TestPassword:
    def test_hash_then_verify(self):
        h = auth.hash_password("s3cret!")
        assert h != "s3cret!"  # ต้องไม่เก็บ plaintext
        assert auth.verify_password("s3cret!", h) is True

    def test_wrong_password_fails(self):
        h = auth.hash_password("s3cret!")
        assert auth.verify_password("wrong", h) is False

    def test_garbage_hash_returns_false(self):
        # hash เสีย/ว่าง ต้องไม่โยน exception ออกมา
        assert auth.verify_password("x", "not-a-real-hash") is False


class TestToken:
    def test_roundtrip(self):
        token = auth.create_token("alice")
        assert auth.decode_token(token) == "alice"

    def test_tampered_token_rejected(self):
        token = auth.create_token("alice")
        with pytest.raises(jwt.InvalidTokenError):
            auth.decode_token(token + "x")

    def test_expired_token_rejected(self, monkeypatch):
        monkeypatch.setattr(auth, "JWT_EXPIRE_HOURS", 0)  # หมดอายุทันที
        token = auth.create_token("alice")
        time.sleep(1)
        with pytest.raises(jwt.ExpiredSignatureError):
            auth.decode_token(token)


class TestLoginRateLimit:
    def test_blocks_after_max_fails(self):
        class FakeClient:
            host = "10.0.0.9"

        class FakeReq:
            client = FakeClient()

        req = FakeReq()
        user = "victim-unique-xyz"
        auth.clear_login_failures(req, user)
        for _ in range(auth._MAX_FAILS):
            auth.check_login_allowed(req, user)  # ยังไม่บล็อก
            auth.record_login_failure(req, user)
        with pytest.raises(Exception):  # HTTPException 429
            auth.check_login_allowed(req, user)
        auth.clear_login_failures(req, user)  # cleanup
