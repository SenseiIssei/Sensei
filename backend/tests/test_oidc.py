from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

import sensei.security.oidc as oidc
import sensei.security.users as users
from sensei.config import settings
from sensei.main import app
from sensei.security.oidc import OIDCError, verify_id_token

_ISSUER = "https://idp.test"
_CLIENT = "sensei-client"
_KID = "test-key-1"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _int_b64url(n: int) -> str:
    return _b64url(n.to_bytes((n.bit_length() + 7) // 8, "big"))


@pytest.fixture
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(pub) -> dict:
    nums = pub.public_numbers()
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": _KID,
            "n": _int_b64url(nums.n), "e": _int_b64url(nums.e)}


def _make_token(priv, claims: dict, kid: str = _KID) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    h = _b64url(json.dumps(header).encode())
    p = _b64url(json.dumps(claims).encode())
    sig = priv.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{_b64url(sig)}"


@pytest.fixture
def oidc_env(monkeypatch, keypair):
    monkeypatch.setattr(settings, "oidc_enabled", True)
    monkeypatch.setattr(settings, "oidc_issuer", _ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", _CLIENT)
    monkeypatch.setattr(settings, "oidc_audience", "")
    monkeypatch.setattr(oidc, "get_jwks", lambda force=False: [_jwk(keypair.public_key())])
    return keypair


def _claims(**over):
    base = {"iss": _ISSUER, "aud": _CLIENT, "exp": int(time.time()) + 600,
            "email": "alice@corp.test", "name": "Alice"}
    base.update(over)
    return base


def test_verify_valid_token(oidc_env):
    token = _make_token(oidc_env, _claims())
    claims = verify_id_token(token)
    assert claims["email"] == "alice@corp.test"


def test_rejects_tampered_signature(oidc_env):
    token = _make_token(oidc_env, _claims())
    head, payload, sig = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(payload + "==").decode())
    forged["email"] = "attacker@evil.test"
    tampered = f"{head}.{_b64url(json.dumps(forged).encode())}.{sig}"
    with pytest.raises(OIDCError):
        verify_id_token(tampered)


def test_rejects_wrong_issuer_and_expired(oidc_env):
    with pytest.raises(OIDCError):
        verify_id_token(_make_token(oidc_env, _claims(iss="https://evil.test")))
    with pytest.raises(OIDCError):
        verify_id_token(_make_token(oidc_env, _claims(exp=int(time.time()) - 10)))


def test_disabled_raises(monkeypatch, keypair):
    monkeypatch.setattr(settings, "oidc_enabled", False)
    with pytest.raises(OIDCError):
        verify_id_token(_make_token(keypair, _claims()))


def test_oidc_exchange_endpoint(oidc_env, monkeypatch, tmp_path):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    token = _make_token(oidc_env, _claims())
    client = TestClient(app)
    resp = client.post("/api/auth/oidc", json={"id_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "alice@corp.test"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@corp.test"


def test_oidc_exchange_disabled_404(monkeypatch):
    monkeypatch.setattr(settings, "oidc_enabled", False)
    client = TestClient(app)
    resp = client.post("/api/auth/oidc", json={"id_token": "x.y.z"})
    assert resp.status_code == 404
