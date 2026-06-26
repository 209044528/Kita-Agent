from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from loguru import logger

from app.core.config import settings
from app.core.exceptions import LLMError
from app.domain.agent.repository import ILLMClient


@dataclass
class ModelHealth:
    failures: int = 0
    open_until: float = 0.0
    half_open_in_flight: bool = False


class RoutingLLMClient(ILLMClient):
    """Model fallback with first-packet probing and an in-process circuit breaker."""

    def __init__(self, delegate: ILLMClient):
        self.delegate = delegate
        self._health: dict[str, ModelHealth] = {}
        self._lock = asyncio.Lock()

    async def stream_chat(
        self,
        messages: list,
        model: str = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        candidates = (
            list(dict.fromkeys([model, *settings.model_candidates]))
            if model
            else settings.model_candidates
        )
        last_error: Exception | None = None

        for candidate in candidates:
            if not candidate or not await self._allow_call(candidate):
                continue
            stream = self.delegate.stream_chat(messages, model=candidate, **kwargs)
            try:
                first = await asyncio.wait_for(
                    anext(stream),
                    timeout=settings.LLM_FIRST_PACKET_TIMEOUT_SECONDS,
                )
                await self._mark_success(candidate)
                yield first
                async for chunk in stream:
                    yield chunk
                return
            except StopAsyncIteration:
                error = LLMError(
                    f"模型 {candidate} 未返回内容",
                    error_type="no_content",
                    retryable=True,
                    data={"model": candidate},
                )
            except asyncio.TimeoutError:
                error = LLMError(
                    f"模型 {candidate} 首包超时",
                    error_type="first_packet_timeout",
                    retryable=True,
                    data={"model": candidate},
                )
            except asyncio.CancelledError:
                await stream.aclose()
                raise
            except Exception as exc:
                error = exc if isinstance(exc, LLMError) else LLMError(
                    f"模型 {candidate} 调用失败: {exc}",
                    error_type="provider_error",
                    retryable=True,
                    data={"model": candidate},
                )

            await stream.aclose()
            await self._mark_failure(candidate)
            last_error = error
            logger.warning("模型失败，尝试降级: model={} error={}", candidate, error)
            if isinstance(error, LLMError) and not error.retryable:
                break

        if isinstance(last_error, LLMError):
            raise last_error
        raise LLMError("没有可用模型", error_type="no_available_model")

    async def _allow_call(self, model: str) -> bool:
        async with self._lock:
            health = self._health.setdefault(model, ModelHealth())
            now = time.monotonic()
            if health.open_until > now:
                return False
            if health.open_until:
                if health.half_open_in_flight:
                    return False
                health.half_open_in_flight = True
            return True

    async def _mark_success(self, model: str) -> None:
        async with self._lock:
            self._health[model] = ModelHealth()

    async def _mark_failure(self, model: str) -> None:
        async with self._lock:
            health = self._health.setdefault(model, ModelHealth())
            was_half_open = health.half_open_in_flight
            if was_half_open:
                health.failures = 0
                health.half_open_in_flight = False
                health.open_until = (
                    time.monotonic() + settings.LLM_CIRCUIT_OPEN_SECONDS
                )
                return
            health.failures += 1
            health.half_open_in_flight = False
            if health.failures >= settings.LLM_FAILURE_THRESHOLD:
                health.failures = 0
                health.open_until = (
                    time.monotonic() + settings.LLM_CIRCUIT_OPEN_SECONDS
                )
