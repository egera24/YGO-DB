"""Email verification registration flow."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token, hash_password
from ygo_app.database import get_db
from ygo_app.models import Base, PendingRegistration, User
from ygo_app.verification import hash_otp, issue_otp_for_pending


def _sqlite_engine(path: str):
    eng = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


class TestEmailVerification(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.sent_codes: list[tuple[str, str]] = []

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.send_patcher = patch(
            "ygo_app.api.routes.auth.send_verification_code",
            side_effect=self._record_send,
        )
        self.send_patcher.start()

    def tearDown(self):
        self.send_patcher.stop()
        app.dependency_overrides.clear()
        self.client.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _record_send(self, to: str, code: str) -> None:
        self.sent_codes.append((to, code))

    def _register(self, email: str = "new@test.example", password: str = "password123"):
        return self.client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )

    def test_register_returns_needs_verification_without_jwt(self):
        res = self._register()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["needs_verification"])
        self.assertEqual(data["email"], "new@test.example")
        self.assertNotIn("access_token", data)
        self.assertEqual(len(self.sent_codes), 1)
        self.assertEqual(self.sent_codes[0][0], "new@test.example")

        session = self.Session()
        try:
            self.assertIsNone(
                session.execute(
                    select(User).where(User.email == "new@test.example")
                ).scalar_one_or_none()
            )
            pending = session.execute(
                select(PendingRegistration).where(
                    PendingRegistration.email == "new@test.example"
                )
            ).scalar_one()
            self.assertIsNotNone(pending.hashed_password)
        finally:
            session.close()

    def test_verify_creates_user_and_returns_token(self):
        self._register()
        code = self.sent_codes[0][1]
        res = self.client.post(
            "/api/auth/verify-email",
            json={"email": "new@test.example", "code": code},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("access_token", res.json())

        session = self.Session()
        try:
            user = session.execute(
                select(User).where(User.email == "new@test.example")
            ).scalar_one()
            self.assertIsNotNone(user.email_verified_at)
            pending = session.execute(select(PendingRegistration)).scalars().all()
            self.assertEqual(pending, [])
        finally:
            session.close()

    def test_wrong_code_increments_attempts(self):
        self._register()
        res = self.client.post(
            "/api/auth/verify-email",
            json={"email": "new@test.example", "code": "000000"},
        )
        self.assertEqual(res.status_code, 400)

        session = self.Session()
        try:
            pending = session.execute(
                select(PendingRegistration).where(
                    PendingRegistration.email == "new@test.example"
                )
            ).scalar_one()
            self.assertEqual(pending.otp_attempts, 1)
        finally:
            session.close()

    def test_expired_code_rejected(self):
        self._register()
        session = self.Session()
        try:
            pending = session.execute(
                select(PendingRegistration).where(
                    PendingRegistration.email == "new@test.example"
                )
            ).scalar_one()
            pending.otp_expires_at = datetime.utcnow() - timedelta(minutes=1)
            session.commit()
        finally:
            session.close()

        code = self.sent_codes[0][1]
        res = self.client.post(
            "/api/auth/verify-email",
            json={"email": "new@test.example", "code": code},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired", res.json()["detail"].lower())

    def test_resend_invalidates_old_code(self):
        self._register()
        old_code = self.sent_codes[0][1]
        res = self.client.post(
            "/api/auth/resend-code",
            json={"email": "new@test.example"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self.sent_codes), 2)

        res_old = self.client.post(
            "/api/auth/verify-email",
            json={"email": "new@test.example", "code": old_code},
        )
        self.assertEqual(res_old.status_code, 400)

        new_code = self.sent_codes[1][1]
        res_new = self.client.post(
            "/api/auth/verify-email",
            json={"email": "new@test.example", "code": new_code},
        )
        self.assertEqual(res_new.status_code, 200)

    def test_login_pending_registration_returns_email_not_verified(self):
        self._register()
        res = self.client.post(
            "/api/auth/login",
            json={"email": "new@test.example", "password": "password123"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"]["code"], "email_not_verified")

    def test_existing_verified_user_can_login(self):
        session = self.Session()
        try:
            password = "password123"
            user = User(
                email="existing@test.example",
                hashed_password=hash_password(password),
                email_verified_at=datetime.utcnow(),
            )
            session.add(user)
            session.commit()
        finally:
            session.close()

        res = self.client.post(
            "/api/auth/login",
            json={"email": "existing@test.example", "password": password},
        )
        self.assertEqual(res.status_code, 200)

    def test_register_duplicate_verified_email(self):
        session = self.Session()
        try:
            session.add(
                User(
                    email="taken@test.example",
                    hashed_password=hash_password("password123"),
                    email_verified_at=datetime.utcnow(),
                )
            )
            session.commit()
        finally:
            session.close()

        res = self._register("taken@test.example")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already registered", res.json()["detail"].lower())

    def test_rate_limit_register_by_ip(self):
        for i in range(5):
            res = self._register(f"user{i}@test.example")
            self.assertEqual(res.status_code, 200, res.text)
        res = self._register("blocked@test.example")
        self.assertEqual(res.status_code, 429)

    def test_issue_otp_sets_hash(self):
        session = self.Session()
        try:
            pending = PendingRegistration(
                email="otp@test.example",
                hashed_password="x",
                otp_hash="",
                otp_expires_at=datetime.utcnow(),
            )
            code = issue_otp_for_pending(pending)
            self.assertEqual(len(code), 6)
            self.assertEqual(pending.otp_hash, hash_otp(code))
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
