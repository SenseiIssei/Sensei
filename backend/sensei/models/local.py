from __future__ import annotations

import logging
import os
import uuid
from typing import AsyncIterator

from sensei.config import settings
from sensei.models.base import (
    ChatCompletion,
    ChatMessage,
    ModelInfo,
    ModelProvider,
    ModelStatus,
    Role,
    UsageStats,
)

logger = logging.getLogger(__name__)


def _detect_gpu() -> bool:
    """Check if a GPU is available for local inference."""
    try:
        import torch

        return torch.cuda.is_available() or torch.backends.mps.is_available()
    except ImportError:
        pass

    # Check for nvidia-smi
    try:
        import subprocess

        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


class LocalModelProvider(ModelProvider):
    """Local model provider using llama.cpp or vLLM."""

    def __init__(
        self,
        model_path: str | None = None,
        backend: str | None = None,
        gpu_layers: int | None = None,
        context_size: int | None = None,
    ):
        self.model_path = model_path or settings.local_model_path
        self.backend = backend or settings.local_backend
        self.gpu_layers = gpu_layers if gpu_layers is not None else settings.local_gpu_layers
        self.context_size = context_size or settings.local_context_size
        self._llm = None
        self._loaded = False

    def _load_model(self):
        """Load the local model (llama.cpp or vLLM)."""
        if self._loaded:
            return

        if not self.model_path or not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Local model not found at {self.model_path}. "
                "Set SENSEI_LOCAL_MODEL_PATH to your GLM-5.2 GGUF/model path."
            )

        if self.backend == "vllm":
            try:
                from vllm import LLM as VLLM

                self._llm = VLLM(
                    model=self.model_path,
                    max_model_len=self.context_size,
                    trust_remote_code=True,
                )
            except ImportError:
                raise RuntimeError(
                    "vLLM not installed. Install with: pip install sensei[local]"
                )
        else:
            try:
                from llama_cpp import Llama

                self._llm = Llama(
                    model_path=self.model_path,
                    n_gpu_layers=self.gpu_layers,
                    n_ctx=self.context_size,
                    verbose=False,
                )
            except ImportError:
                raise RuntimeError(
                    "llama-cpp-python not installed. Install with: pip install sensei[local]"
                )

        self._loaded = True
        logger.info("Loaded local model: %s via %s", self.model_path, self.backend)

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict]:
        return [{"role": msg.role.value, "content": msg.content} for msg in messages]

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> ChatCompletion | AsyncIterator[str]:
        if stream:
            return self.stream_chat(messages, model, temperature, max_tokens)

        # Run in thread pool since llama.cpp/vLLM are synchronous
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._sync_chat, messages, temperature, max_tokens)
        return result

    def _sync_chat(
        self, messages: list[ChatMessage], temperature: float, max_tokens: int
    ) -> ChatCompletion:
        self._load_model()

        if self.backend == "vllm":
            from vllm import SamplingParams

            sampling = SamplingParams(temperature=temperature, max_tokens=max_tokens)
            formatted = self._format_messages(messages)
            output = self._llm.generate([formatted], sampling)
            text = output[0].outputs[0].text
            prompt_tokens = len(output[0].prompt_token_ids)
            completion_tokens = len(output[0].outputs[0].token_ids)
        else:
            result = self._llm.create_chat_completion(
                messages=self._format_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            text = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

        return ChatCompletion(
            id=str(uuid.uuid4()),
            model=os.path.basename(self.model_path),
            content=text,
            role=Role.assistant,
            usage=UsageStats(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        import asyncio

        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _sync_stream():
            try:
                self._load_model()
                if self.backend == "vllm":
                    # vLLM doesn't support true streaming per-token easily; fall back
                    result = self._sync_chat(messages, temperature, max_tokens)
                    asyncio.run_coroutine_threadsafe(
                        queue.put(result.content), asyncio.get_event_loop()
                    )
                else:
                    for chunk in self._llm.create_chat_completion(
                        messages=self._format_messages(messages),
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    ):
                        delta = chunk["choices"][0].get("delta", {})
                        if content := delta.get("content"):
                            asyncio.run_coroutine_threadsafe(
                                queue.put(content), asyncio.get_event_loop()
                            )
            except Exception as e:
                logger.error("Streaming error: %s", e)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), asyncio.get_event_loop())

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _sync_stream)

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    async def get_info(self) -> ModelInfo:
        available = await self.is_available()
        model_name = os.path.basename(self.model_path) if self.model_path else "unknown"
        return ModelInfo(
            id=f"local:{model_name}",
            name=f"GLM-5.2 Local ({self.backend})",
            provider="local",
            backend=self.backend,
            context_window=self.context_size,
            status=ModelStatus.available if available else ModelStatus.unavailable,
            description=f"Local GLM-5.2 via {self.backend}",
            quantization="GGUF" if self.backend == "llama.cpp" else None,
        )

    async def is_available(self) -> bool:
        if not self.model_path:
            return False
        if not os.path.exists(self.model_path):
            return False
        # Check if the backend library is available
        if self.backend == "vllm":
            try:
                import vllm  # noqa: F401

                return True
            except ImportError:
                return False
        else:
            try:
                import llama_cpp  # noqa: F401

                return True
            except ImportError:
                return False
