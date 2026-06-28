"""OIDC SSO — verify an OpenID Connect ID token and map it to a Sensei session.

Token-exchange flow: the frontend completes the OIDC dance with the IdP (Google,
Okta, Entra, Keycloak, …) and POSTs the resulting ID token to ``/api/auth/oidc``.
Here we validate it (RS256 signature against the issuer's JWKS, plus iss/aud/exp)
and provision a Sensei user just-in-time. Off by default. RSA verification uses
the ``cryptography`` library already in the dependency set — no JWT lib needed.
"""
from __future__ import annotations

import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sensei.config import settings


class OIDCError(Exception):
    """Raised when an ID token fails validation."""


def _b64url_bytes(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _json_b64(data: str) -> dict:
    return json.loads(_b64url_bytes(data).decode("utf-8"))


def _b64url_to_int(val: str) -> int:
    return int.from_bytes(_b64url_bytes(val), "big")


_jwks_cache: dict = {"keys": None, "ts": 0.0}
_JWKS_TTL = 3600.0


def _discover_jwks_uri() -> str:
    if settings.oidc_jwks_uri:
        return settings.oidc_jwks_uri
    if not settings.oidc_issuer:
        raise OIDCError("OIDC issuer not configured")
    url = settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=10.0) as client:
        return client.get(url).json()["jwks_uri"]


def get_jwks(force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _jwks_cache["keys"] is not None and now - _jwks_cache["ts"] < _JWKS_TTL:
        return _jwks_cache["keys"]
    with httpx.Client(timeout=10.0) as client:
        keys = client.get(_discover_jwks_uri()).json()["keys"]
    _jwks_cache.update(keys=keys, ts=now)
    return keys


def _verify_rs256(signing_input: bytes, signature: bytes, jwk: dict) -> bool:
    pub = rsa.RSAPublicNumbers(_b64url_to_int(jwk["e"]), _b64url_to_int(jwk["n"])).public_key()
    try:
        pub.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:  # noqa: BLE001
        return False


def verify_id_token(token: str) -> dict:
    """Validate an OIDC ID token and return its claims, or raise OIDCError."""
    if not settings.oidc_enabled:
        raise OIDCError("OIDC is disabled")
    parts = token.split(".")
    if len(parts) != 3:
        raise OIDCError("malformed token")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = _json_b64(header_b64)
    except Exception as e:  # noqa: BLE001
        raise OIDCError("bad header") from e
    if header.get("alg") != "RS256":
        raise OIDCError(f"unsupported alg: {header.get('alg')}")

    kid = header.get("kid")
    keys = get_jwks()
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if jwk is None:  # possible key rotation — refresh once
        jwk = next((k for k in get_jwks(force=True) if k.get("kid") == kid), None)
    if jwk is None:
        raise OIDCError("signing key not found")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    if not _verify_rs256(signing_input, _b64url_bytes(sig_b64), jwk):
        raise OIDCError("signature verification failed")

    claims = _json_b64(payload_b64)
    if settings.oidc_issuer and claims.get("iss") != settings.oidc_issuer:
        raise OIDCError("issuer mismatch")
    expected_aud = settings.oidc_audience or settings.oidc_client_id
    if expected_aud:
        aud = claims.get("aud")
        audset = {aud} if isinstance(aud, str) else set(aud or [])
        if expected_aud not in audset:
            raise OIDCError("audience mismatch")
    if float(claims.get("exp", 0)) < time.time():
        raise OIDCError("token expired")
    if not claims.get("email"):
        raise OIDCError("ID token has no email claim")
    return claims
