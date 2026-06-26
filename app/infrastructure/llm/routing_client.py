from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from loguru import logger

from app.core.config import settings
from app.core.exceptions import LLMError
from app.domain.agent.repository import ILLMClient
from app.infrastructure.platform_store import PlatformStore


@dataclass
class ModelHealth:
    failures: int = 0
    open_until: float = 0.0
    half_open_in_flight: bool = False


class RoutingLLMClient(ILLMClient):
    """Model fallback with first-packet probing and an in-process circuit breaker."""

    def __init__(
        self,
        delegate: ILLMClient,
        platform_store: PlatformStore | None = None,
    ):
        self.delegate = delegate
        self.platform_store = platform_store
        self._health: dict[str, ModelHealth] = {}
        self._lock = asyncio.Lock()

    async def stream_chat(
        self,
        messages: list,
        model: str = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        candidates = self._model_candidates(model)
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
            await self._mark_failure(candidate, error)
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

    def _model_candidates(self, requested_model: str | None) -> list[str]:
        configured = []
        if self.platform_store:
            try:
                configured = [
                    item["model_name"]
                    for item in self.platform_store.list_model_configs(enabled_only=True)
                ]
            except Exception as exc:
                logger.warning("Failed to read model configs: {}", exc)

        candidates = []
        if requested_model:
            candidates.append(requested_model)
        candidates.extend(configured)
        candidates.extend(settings.model_candidates)
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    async def _mark_success(self, model: str) -> None:
        async with self._lock:
            self._health[model] = ModelHealth()
        if self.platform_store:
            self.platform_store.record_model_health(
                model_name=model,
                state="healthy",
                failures=0,
                open_until=None,
                success=True,
            )

    async def _mark_failure(self, model: str, error: Exception | None = None) -> None:
        state = "degraded"
        failures = 0
        open_until = None
        async with self._lock:
            health = self._health.setdefault(model, ModelHealth())
            was_half_open = health.half_open_in_flight
            if was_half_open:
                health.failures = 0
                health.half_open_in_flight = False
                health.open_until = (
                    time.monotonic() + settings.LLM_CIRCUIT_OPEN_SECONDS
                )
                state = "open"
                failures = health.failures
                open_until = time.time() + settings.LLM_CIRCUIT_OPEN_SECONDS
            else:
                health.failures += 1
                health.half_open_in_flight = False
                failures = health.failures
                if health.failures >= settings.LLM_FAILURE_THRESHOLD:
                    health.failures = 0
                    health.open_until = (
                        time.monotonic() + settings.LLM_CIRCUIT_OPEN_SECONDS
                    )
                    state = "open"
                    open_until = time.time() + settings.LLM_CIRCUIT_OPEN_SECONDS

        if self.platform_store:
            self.platform_store.record_model_health(
                model_name=model,
                state=state,
                failures=failures,
                open_until=open_until,
                last_error=str(error) if error else None,
                success=False,
            )
