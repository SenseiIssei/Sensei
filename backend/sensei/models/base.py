from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncIterator, Literal

from pydantic import BaseModel, Field


class Role(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ChatMessage(BaseModel):
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class UsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    compressed_prompt_tokens: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 1.0


class ChatCompletion(BaseModel):
    id: str
    model: str
    content: str
    role: Role = Role.assistant
    usage: UsageStats = Field(default_factory=UsageStats)
    created: float = Field(default_factory=time.time)
    finish_reason: str = "stop"


class ModelStatus(str, Enum):
    available = "available"
    unavailable = "unavailable"
    loading = "loading"
    unknown = "unknown"


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: Literal["local", "api"]
    backend: str
    context_window: int
    status: ModelStatus = ModelStatus.unknown
    description: str = ""
    quantization: str | None = None


class ModelProvider(ABC):
    """Abstract base for model providers (local and API)."""

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> ChatCompletion | AsyncIterator[str]:
        """Generate a chat completion (or stream tokens if stream=True)."""
        ...

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens."""
        ...

    @abstractmethod
    async def get_info(self) -> ModelInfo:
        """Return model metadata and status."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this provider is ready to serve requests."""
        ...
