"""Auth API routes for public Sensei chat — registration, login, token verification."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from sensei.security.users import (
    UserLogin,
    UserRegister,
    TokenResponse,
    get_user_from_token,
    login_user,
    register_user,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=TokenResponse)
async def register(body: UserRegister) -> TokenResponse:
    token, error = register_user(body.email, body.password, body.name)
    if error:
        raise HTTPException(status_code=409, detail=error)
    return token


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: UserLogin) -> TokenResponse:
    token, error = login_user(body.email, body.password)
    if error:
        raise HTTPException(status_code=401, detail=error)
    return token


@router.get("/auth/me")
async def me(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization[7:]
    user = get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
