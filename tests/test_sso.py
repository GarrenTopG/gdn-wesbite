import base64
import os
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from authlib.jose import JsonWebToken
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlmodel import select

from app.models.entities import ExternalIdentity, RecordHistory, User
from app.routers.sso import (
    InvalidSsoResponse,
    _decode_identity_token,
    _pkce_challenge,
    validate_sso_configuration,
)
from tests.support import DatabaseTestCase


SSO_ENVIRONMENT = {
    "SSO_BASE_URL": "https://aurorah-web-hub.onrender.com",
    "SSO_GOOGLE_CLIENT_ID": "google-client",
    "SSO_GOOGLE_CLIENT_SECRET": "google-secret",
    "SSO_MICROSOFT_CLIENT_ID": "microsoft-client",
    "SSO_MICROSOFT_CLIENT_SECRET": "microsoft-secret",
}


def identity_claims(provider: str, subject: str = "provider-subject"):
    claims = {
        "sub": subject,
        "email": "sso-user@example.org",
        "name": "SSO User",
        "nonce": "test-nonce",
    }
    if provider == "google":
        claims["email_verified"] = True
        claims["iss"] = "https://accounts.google.com"
    else:
        claims["iss"] = "https://login.microsoftonline.com/"
        claims["iss"] += "11111111-2222-3333-4444-555555555555/v2.0"
        claims["tid"] = "11111111-2222-3333-4444-555555555555"
    return claims


class SharedSsoTests(DatabaseTestCase):
    def begin_website_sso(self, *, next_path="/news"):
        response = self.client.get(
            "/account/sso/google",
            params={"next_path": next_path},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        authorization = urlsplit(response.headers["location"])
        parameters = parse_qs(authorization.query)
        self.assertEqual(parameters["client_id"], ["google-client"])
        self.assertEqual(
            parameters["redirect_uri"],
            ["https://aurorah-web-hub.onrender.com/auth/sso/callback/google"],
        )
        return parameters["state"][0]

    def complete_callback(self, state: str, provider="google"):
        with patch(
            "app.routers.sso._exchange_and_validate",
            return_value=identity_claims(provider),
        ):
            return self.client.get(
                f"/auth/sso/callback/{provider}",
                params={"state": state, "code": "provider-code"},
                follow_redirects=False,
            )

    def test_website_oidc_creates_public_session_and_uses_safe_next_path(self):
        with patch.dict(os.environ, SSO_ENVIRONMENT):
            state = self.begin_website_sso()
            response = self.complete_callback(state)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/news")
        self.assertIn("user_session", response.cookies)
        self.assertEqual(response.headers["cache-control"], "no-store")
        with self.database_session() as session:
            user = session.exec(
                select(User).where(User.email == "sso-user@example.org")
            ).one()
            identity = session.exec(select(ExternalIdentity)).one()
            self.assertEqual(user.role.value, "user")
            self.assertEqual(identity.provider, "google")
            self.assertEqual(identity.subject, "provider-subject")

    def test_website_oidc_rejects_login_csrf_and_unsafe_redirect(self):
        with patch.dict(os.environ, SSO_ENVIRONMENT):
            state = self.begin_website_sso(next_path="//evil.example")
            self.client.cookies.set("sso_state_google", "different-state")
            invalid = self.complete_callback(state)
            self.assertEqual(invalid.headers["location"], "/account/login?sso_error=1")
            self.assertEqual(self.client.get("/account/login").status_code, 200)
            self.client.cookies.clear()
            state = self.begin_website_sso(next_path="//evil.example")
            response = self.complete_callback(state)

        self.assertEqual(response.headers["location"], "/")

    def test_existing_email_is_not_automatically_linked(self):
        with self.database_session() as session:
            session.add(
                User(
                    full_name="Existing User",
                    email="sso-user@example.org",
                    hashed_password="not-used",
                )
            )
            session.commit()

        with patch.dict(os.environ, SSO_ENVIRONMENT):
            state = self.begin_website_sso()
            response = self.complete_callback(state)

        self.assertEqual(response.headers["location"], "/account/login?sso_error=1")
        self.assertNotIn("user_session", response.cookies)
        with self.database_session() as session:
            self.assertEqual(session.exec(select(ExternalIdentity)).all(), [])

    def test_historical_firebase_google_account_is_upgraded_by_verified_oidc(self):
        with self.database_session() as session:
            user = User(
                full_name="Legacy Google User",
                email="sso-user@example.org",
                hashed_password="random-legacy-password-hash",
            )
            session.add(user)
            session.flush()
            session.add(
                RecordHistory(
                    record_type="user",
                    record_id=user.id,
                    action="mobile_account_registered_google",
                )
            )
            session.commit()

        with patch.dict(os.environ, SSO_ENVIRONMENT):
            state = self.begin_website_sso()
            response = self.complete_callback(state)

        self.assertEqual(response.status_code, 303)
        self.assertIn("user_session", response.cookies)
        with self.database_session() as session:
            identity = session.exec(select(ExternalIdentity)).one()
            self.assertEqual(identity.subject, "provider-subject")

    def test_existing_user_can_explicitly_link_provider(self):
        with self.database_session() as session:
            user = User(
                full_name="Existing User",
                email="existing@example.org",
                hashed_password="not-used",
            )
            session.add(user)
            session.commit()
            user_id = user.id
        self.authenticate_public(user)

        with patch.dict(os.environ, SSO_ENVIRONMENT):
            blocked = self.client.post(
                "/account/sso/link/google", follow_redirects=False
            )
            self.assertEqual(blocked.status_code, 403)
            self.client.get("/account/login")
            start = self.client.post(
                "/account/sso/link/google",
                data={"csrf_token": self.client.cookies.get("csrf_token", "")},
                follow_redirects=False,
            )
            state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
            claims = identity_claims("google", "linked-subject")
            claims["email"] = "different-provider-email@example.org"
            with patch("app.routers.sso._exchange_and_validate", return_value=claims):
                response = self.client.get(
                    "/auth/sso/callback/google",
                    params={"state": state, "code": "provider-code"},
                    follow_redirects=False,
                )

        self.assertEqual(response.headers["location"], "/")
        with self.database_session() as session:
            identity = session.exec(select(ExternalIdentity)).one()
            self.assertEqual(identity.user_id, user_id)

    def test_mobile_code_exchange_requires_pkce_and_is_single_use(self):
        verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()
        challenge = _pkce_challenge(verifier)
        with patch.dict(os.environ, SSO_ENVIRONMENT):
            start = self.client.get(
                "/api/auth/sso/google/start",
                params={"challenge": challenge},
                follow_redirects=False,
            )
            self.assertEqual(start.status_code, 303, start.text)
            state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
            callback = self.complete_callback(state)

            handoff = urlsplit(callback.headers["location"])
            self.assertEqual(handoff.scheme, "https")
            self.assertEqual(handoff.netloc, "aurorah-web-hub.onrender.com")
            self.assertEqual(handoff.path, "/mobile-auth/callback")
            code = parse_qs(handoff.query)["code"][0]
            wrong_verifier = "A" * 43
            if _pkce_challenge(wrong_verifier) == challenge:
                wrong_verifier = "B" * 43
            rejected = self.client.post(
                "/api/auth/sso/exchange",
                json={"code": code, "codeVerifier": wrong_verifier},
            )
            self.assertEqual(rejected.status_code, 401)

            exchanged = self.client.post(
                "/api/auth/sso/exchange",
                json={"code": code, "codeVerifier": verifier},
            )
            self.assertEqual(exchanged.status_code, 200, exchanged.text)
            self.assertTrue(exchanged.json()["token"])
            replay = self.client.post(
                "/api/auth/sso/exchange",
                json={"code": code, "codeVerifier": verifier},
            )

        self.assertEqual(replay.status_code, 401)

    def test_mobile_provider_options_only_include_complete_providers(self):
        with patch.dict(os.environ, SSO_ENVIRONMENT):
            response = self.client.get("/api/auth/sso/providers")
        self.assertEqual(response.json(), {"providers": ["google", "microsoft"]})

    def test_microsoft_oidc_creates_an_external_identity(self):
        with patch.dict(os.environ, SSO_ENVIRONMENT):
            start = self.client.get("/account/sso/microsoft", follow_redirects=False)
            state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
            response = self.complete_callback(state, provider="microsoft")

        self.assertEqual(response.status_code, 303)
        with self.database_session() as session:
            identity = session.exec(select(ExternalIdentity)).one()
            self.assertEqual(identity.provider, "microsoft")

    def test_partial_provider_configuration_fails_explicitly(self):
        with patch.dict(
            os.environ,
            {
                "SSO_GOOGLE_CLIENT_ID": "google-client",
                "SSO_GOOGLE_CLIENT_SECRET": "",
                "SSO_BASE_URL": "https://aurorah-web-hub.onrender.com",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "incompletely configured"):
                validate_sso_configuration()

    def test_provider_authorization_starts_are_rate_limited(self):
        with patch.dict(os.environ, SSO_ENVIRONMENT):
            responses = [
                self.client.get("/account/sso/google", follow_redirects=False)
                for _ in range(21)
            ]
        self.assertTrue(all(response.status_code == 303 for response in responses[:20]))
        self.assertEqual(responses[20].status_code, 429)

    def test_oidc_token_signature_audience_nonce_and_expiry_are_validated(self):
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        def encode_integer(value: int) -> str:
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        public_numbers = private_key.public_key().public_numbers()
        jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "sso-test",
                    "use": "sig",
                    "alg": "RS256",
                    "n": encode_integer(public_numbers.n),
                    "e": encode_integer(public_numbers.e),
                }
            ]
        }
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "google-client",
            "sub": "signed-subject",
            "nonce": "expected-nonce",
            "iat": now,
            "exp": now + 300,
            "email": "signed@example.org",
            "email_verified": True,
        }
        token = (
            JsonWebToken(["RS256"])
            .encode(
                {"alg": "RS256", "kid": "sso-test"},
                claims,
                private_key,
            )
            .decode("ascii")
        )

        class KeyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return jwks

        with patch("app.routers.sso.requests.get", return_value=KeyResponse()):
            valid = _decode_identity_token(
                "google", token, "expected-nonce", "google-client"
            )
            self.assertEqual(valid["sub"], "signed-subject")
            with self.assertRaises(InvalidSsoResponse):
                _decode_identity_token("google", token, "wrong-nonce", "google-client")
            with self.assertRaises(InvalidSsoResponse):
                _decode_identity_token(
                    "google", token, "expected-nonce", "other-client"
                )

            expired_claims = {**claims, "exp": now - 120}
            expired_token = (
                JsonWebToken(["RS256"])
                .encode(
                    {"alg": "RS256", "kid": "sso-test"},
                    expired_claims,
                    private_key,
                )
                .decode("ascii")
            )
            with self.assertRaises(InvalidSsoResponse):
                _decode_identity_token(
                    "google", expired_token, "expected-nonce", "google-client"
                )
