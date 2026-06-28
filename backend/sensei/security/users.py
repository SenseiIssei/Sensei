"""User authentication system for public Sensei chat.

Supports registration, login, and JWT-based session tokens.
User data is stored in a simple JSON file (easily swapable for a database).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)

USERS_FILE = Path(os.environ.get("SENSEI_USERS_FILE", ".sensei_users.json"))
JWT_SECRET = os.environ.get("SENSEI_JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = int(os.environ.get("SENSEI_JWT_EXPIRY_HOURS", "168"))  # 7 days


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=64)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: float


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    actual = _hash_password(password, salt)
    return secrets.compare_digest(actual, expected_hash)


def _load_users() -> dict[str, dict]:
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_users(users: dict[str, dict]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _create_token(user_id: str, email: str, role: str = "user") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
        "iat": int(time.time()),
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = _b64_encode(payload_json)
    sig = hmac.new(JWT_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def _b64_encode(data: str) -> str:
    import base64
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def _b64_decode(data: str) -> str:
    import base64
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode()).decode()


def verify_token(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(JWT_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(_b64_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def register_user(email: str, password: str, name: str) -> tuple[Optional[TokenResponse], Optional[str]]:
    users = _load_users()
    email_lower = email.lower()
    if email_lower in users:
        return None, "An account with this email already exists"

    user_id = secrets.token_hex(16)
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)

    from sensei.config import settings

    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    role = "admin" if email_lower in admins else "user"

    users[email_lower] = {
        "id": user_id,
        "email": email_lower,
        "name": name,
        "role": role,
        "salt": salt,
        "password_hash": password_hash,
        "created_at": time.time(),
    }
    _save_users(users)

    logger.info("New user registered: %s (%s) [%s]", name, email_lower, role)
    token = _create_token(user_id, email_lower, role)
    user_out = UserOut(id=user_id, email=email_lower, name=name, created_at=users[email_lower]["created_at"])
    return TokenResponse(access_token=token, user=user_out), None


def login_user(email: str, password: str) -> tuple[Optional[TokenResponse], Optional[str]]:
    users = _load_users()
    email_lower = email.lower()
    user = users.get(email_lower)
    if not user:
        return None, "Invalid email or password"

    if not _verify_password(password, user["salt"], user["password_hash"]):
        return None, "Invalid email or password"

    token = _create_token(user["id"], email_lower, user.get("role", "user"))
    user_out = UserOut(id=user["id"], email=email_lower, name=user["name"], created_at=user["created_at"])
    logger.info("User logged in: %s", email_lower)
    return TokenResponse(access_token=token, user=user_out), None


def provision_sso_user(email: str, name: str = "") -> TokenResponse:
    """Just-in-time provision (or sync) an SSO user and issue a Sensei token."""
    users = _load_users()
    email_lower = email.lower()

    from sensei.config import settings

    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    role = "admin" if email_lower in admins else "user"

    user = users.get(email_lower)
    if not user:
        user = {
            "id": secrets.token_hex(16),
            "email": email_lower,
            "name": name or email_lower,
            "role": role,
            "salt": "",
            "password_hash": "",  # SSO users have no local password
            "sso": True,
            "created_at": time.time(),
        }
        users[email_lower] = user
        _save_users(users)
        logger.info("Provisioned SSO user: %s [%s]", email_lower, role)
    elif user.get("role") != role:  # keep role in sync with the admin list
        user["role"] = role
        _save_users(users)

    token = _create_token(user["id"], email_lower, user["role"])
    user_out = UserOut(id=user["id"], email=email_lower, name=user["name"], created_at=user["created_at"])
    return TokenResponse(access_token=token, user=user_out)


def get_user_from_token(token: str) -> Optional[dict]:
    payload = verify_token(token)
    if not payload:
        return None
    users = _load_users()
    email = payload.get("email", "")
    user = users.get(email)
    if not user:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "created_at": user["created_at"],
    }
