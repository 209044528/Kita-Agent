from __future__ import annotations

import json
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from app.infrastructure.platform_store import PlatformStore


class ObservabilityService:
    """Local-first tracing and metrics with optional OpenTelemetry spans."""

    def __init__(
        self,
        trace_path: str = "logs/agent_traces.jsonl",
        bad_case_path: str = "logs/bad_cases.jsonl",
        platform_store: PlatformStore | None = None,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.trace_path = Path(trace_path)
        self.bad_case_path = Path(bad_case_path)
        self.platform_store = platform_store
        self._lock = threading.Lock()
        self._tool_calls = defaultdict(int)
        self._tool_errors = defaultdict(int)
        self._tool_duration_ms = defaultdict(float)
        self._rag_requests = 0
        self._rag_hits = 0
        if enabled:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.bad_case_path.parent.mkdir(parents=True, exist_ok=True)

    def start_trace(
        self, session_id: str, user_input: str, model_name: str | None
    ) -> str:
        trace_id = uuid.uuid4().hex
        self.record_event(
            trace_id=trace_id,
            session_id=session_id,
            event_type="agent_started",
            payload={"user_input": user_input, "model": model_name},
        )
        return trace_id

    def finish_trace(
        self,
        trace_id: str | None,
        session_id: str,
        answer: str,
        step: int,
        success: bool,
    ) -> None:
        self.record_event(
            trace_id=trace_id,
            session_id=session_id,
            event_type="agent_finished",
            step=step,
            success=success,
            payload={"answer": answer},
        )

    def record_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        duration_ms: float,
        success: bool,
        session_id: str | None,
        trace_id: str | None,
        step: int | None,
    ) -> None:
        with self._lock:
            self._tool_calls[tool_name] += 1
            self._tool_duration_ms[tool_name] += duration_ms
            if not success:
                self._tool_errors[tool_name] += 1
            if tool_name == "knowledge_search":
                self._rag_requests += 1
                if success and result.strip() and "未找到相关知识" not in result:
                    self._rag_hits += 1
        self.record_event(
            trace_id=trace_id,
            session_id=session_id,
            event_type="tool_call",
            step=step,
            duration_ms=round(duration_ms, 3),
            success=success,
            payload={
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
            },
        )
        if not success:
            self.record_bad_case(
                category="tool_execution_failure",
                session_id=session_id,
                trace_id=trace_id,
                input_text=json.dumps(arguments, ensure_ascii=False),
                detail=result,
            )

    def record_event(
        self,
        *,
        trace_id: str | None,
        session_id: str | None,
        event_type: str,
        payload: dict[str, Any] | None = None,
        step: int | None = None,
        duration_ms: float | None = None,
        success: bool | None = None,
    ) -> None:
        if not self.enabled:
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "session_id": session_id,
            "event_type": event_type,
            "step": step,
            "duration_ms": duration_ms,
            "success": success,
            "payload": payload or {},
        }
        self._append_jsonl(self.trace_path, event)
        if self.platform_store:
            self.platform_store.insert_trace_event(event)

    def record_bad_case(
        self,
        *,
        category: str,
        session_id: str | None,
        trace_id: str | None,
        input_text: str,
        detail: str,
        model_output: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        case = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "session_id": session_id,
            "trace_id": trace_id,
            "input": input_text,
            "detail": detail,
            "model_output": model_output,
        }
        self._append_jsonl(self.bad_case_path, case)
        if self.platform_store:
            self.platform_store.insert_bad_case(case)

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            tools = {}
            for name, count in self._tool_calls.items():
                tools[name] = {
                    "calls": count,
                    "errors": self._tool_errors[name],
                    "average_duration_ms": round(
                        self._tool_duration_ms[name] / count, 3
                    ),
                }
            return {
                "tools": tools,
                "rag": {
                    "requests": self._rag_requests,
                    "hits": self._rag_hits,
                    "hit_rate": (
                        round(self._rag_hits / self._rag_requests, 4)
                        if self._rag_requests
                        else 0.0
                    ),
                },
            }

    def read_traces(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not self.trace_path.exists():
            return []
        lines = self.trace_path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines[-max(limit * 3, limit) :] if line]
        if session_id:
            events = [event for event in events if event.get("session_id") == session_id]
        return events[-limit:]

    def read_trace_events(
        self, session_id: str | None = None, trace_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if self.platform_store:
            return self.platform_store.read_trace_events(
                session_id=session_id, trace_id=trace_id, limit=limit
            )
        if trace_id:
            return [
                event
                for event in self.read_traces(session_id=session_id, limit=limit * 3)
                if event.get("trace_id") == trace_id
            ][-limit:]
        return self.read_traces(session_id=session_id, limit=limit)

    def read_bad_cases(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.platform_store:
            return self.platform_store.read_bad_cases(limit=limit)
        if not self.bad_case_path.exists():
            return []
        lines = self.bad_case_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line]

    def trace_summary(self) -> dict[str, Any]:
        if self.platform_store:
            return self.platform_store.trace_summary()
        events = self.read_traces(limit=10000)
        by_type: dict[str, int] = defaultdict(int)
        for event in events:
            by_type[event.get("event_type", "unknown")] += 1
        return {
            "trace_events": len(events),
            "bad_cases": len(self.read_bad_cases(limit=10000)),
            "events_by_type": [
                {"event_type": key, "count": value}
                for key, value in sorted(by_type.items(), key=lambda item: item[1], reverse=True)
            ],
        }

    def _append_jsonl(self, path: Path, value: dict[str, Any]) -> None:
        try:
            line = json.dumps(value, ensure_ascii=False, default=str)
            with self._lock:
                with path.open("a", encoding="utf-8") as file:
                    file.write(line + "\n")
        except OSError as exc:
            logger.warning("Failed to persist observability event: {}", exc)
