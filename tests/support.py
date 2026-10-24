import hashlib
import hmac
import os
import secrets
import struct
import base64
import time
import unittest
from datetime import timedelta

os.environ["APP_SECRET_KEY"] = "test-app-secret-key-not-for-production-000000"
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["SQLITE_FILE_NAME"] = ":memory:"

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.entities import AuthSession, User
from app.security import STAFF_COOKIE_NAME, now_utc
from main import create_app


def totp_code(secret: str, timestamp: int | None = None) -> str:
    counter = (int(time.time()) if timestamp is None else timestamp) // 30
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = create_app(database_engine=self.engine, initialize_database=False)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def database_session(self):
        return Session(self.engine)

    def login_staff(self, email: str, password: str, *, path="/admin/login"):
        self.client.get("/account/login")
        challenge = self.client.post(
            path,
            data={
                "csrf_token": self.client.cookies.get("csrf_token", ""),
                "email": email,
                "password": password,
            },
            follow_redirects=False,
        )
        if challenge.headers.get("location") != "/admin/mfa":
            return challenge, None

        token = self.client.cookies[STAFF_COOKIE_NAME]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with Session(self.engine) as session:
            auth_session = session.exec(
                select(AuthSession).where(AuthSession.token_hash == token_hash)
            ).one()
            user = session.get(User, auth_session.user_id)
            secret = auth_session.mfa_setup_secret or user.mfa_secret

        verification = self.client.post(
            "/admin/mfa/verify",
            data={"code": totp_code(secret)},
            headers={"X-CSRF-Token": self.client.cookies.get("csrf_token", "")},
            follow_redirects=False,
        )
        return challenge, verification

    def authenticate_staff(self, user: User, *, expires_at=None) -> str:
        token = secrets.token_urlsafe(32)
        with Session(self.engine) as session:
            if user.id is None:
                session.add(user)
                session.flush()
                user_id = user.id
            else:
                user_id = user.id
            session.add(
                AuthSession(
                    token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    user_id=user_id,
                    expires_at=expires_at or now_utc() + timedelta(hours=12),
                    mfa_verified=True,
                )
            )
            session.commit()
        self.client.cookies.set(STAFF_COOKIE_NAME, token)
        return token

    def authenticate_public(self, user: User, *, expires_at=None) -> str:
        token = secrets.token_urlsafe(32)
        with Session(self.engine) as session:
            if user.id is None:
                session.add(user)
                session.flush()
                user_id = user.id
            else:
                user_id = user.id
            session.add(
                AuthSession(
                    token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    user_id=user_id,
                    expires_at=expires_at or now_utc() + timedelta(hours=12),
                    mfa_verified=True,
                )
            )
            session.commit()
        self.client.cookies.set("user_session", token)
        return token
