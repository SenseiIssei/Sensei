"""Webhook API — an authenticated, single-purpose entry point for external
platforms (Slack slash commands, Zapier, Discord/Telegram bots, ...).

POST /api/webhook with header ``X-Sensei-Webhook-Token: <token>`` and a JSON body
``{"message": "...", "model": "...", "conversation_id": "..."}``. Runs the full
compressed-chat flow and returns the assistant reply + tokens saved. Disabled
unless both ``SENSEI_WEBHOOK_ENABLED`` and ``SENSEI_WEBHOOK_TOKEN`` are set, so
you can expose just this endpoint without opening the rest of the API.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from sensei.audit import get_audit_log
from sensei.config import settings
from sensei.routers.chat import ChatRequest, ChatResponse
from sensei.routers.chat import chat as _chat_handler

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("")
async def webhook(
    payload: ChatRequest,
    x_sensei_webhook_token: str = Header(default=""),
) -> ChatResponse:
    if not settings.webhook_enabled or not settings.webhook_token:
        raise HTTPException(status_code=404, detail="Webhook is disabled.")
    if x_sensei_webhook_token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    get_audit_log().record("webhook.request", model=payload.model)
    return await _chat_handler(payload)
