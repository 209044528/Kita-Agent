from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class StructuredAction(BaseModel):
    """One model action. `finish` is represented as a reserved tool name."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    thought: str | None = None
    format: Literal["json", "legacy"] = "json"

    @model_validator(mode="after")
    def validate_finish(self) -> "StructuredAction":
        if self.tool == "finish" and not isinstance(self.arguments.get("answer"), str):
            raise ValueError("finish requires arguments.answer")
        return self

    @property
    def is_finish(self) -> bool:
        return self.tool.lower() == "finish"

    @property
    def final_answer(self) -> str | None:
        return self.arguments.get("answer") if self.is_finish else None


class ToolCallParser:
    """Parse JSON actions first, retaining the old ReAct syntax as fallback."""

    _json_block = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

    def parse(self, text: str) -> StructuredAction:
        json_error: Exception | None = None
        for candidate in self._json_candidates(text):
            try:
                payload = json.loads(candidate)
                if "tool" in payload:
                    payload["tool"] = str(payload["tool"]).lower()
                    return StructuredAction.model_validate(payload)
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                json_error = exc

        legacy = self._parse_legacy(text)
        if legacy:
            return legacy
        detail = f": {json_error}" if json_error else ""
        raise ValueError(f"无法解析结构化工具调用{detail}")

    def _json_candidates(self, text: str) -> list[str]:
        candidates = self._json_block.findall(text)
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates.append(stripped)
        else:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start >= 0 and end > start:
                candidates.append(stripped[start : end + 1])
        return candidates

    def _parse_legacy(self, text: str) -> StructuredAction | None:
        finish = re.search(r"Action:\s*Finish\[(.*)\]", text, re.DOTALL | re.IGNORECASE)
        if finish:
            return StructuredAction(
                tool="finish",
                arguments={"answer": finish.group(1).strip()},
                format="legacy",
            )

        call = re.search(r"Action:\s*(\w+)\((.*)\)", text, re.DOTALL)
        if not call:
            return None
        arguments: dict[str, Any] = {}
        for name, value in re.findall(r'(\w+)\s*=\s*"((?:\\.|[^"])*)"', call.group(2)):
            arguments[name] = json.loads(f'"{value}"')
        return StructuredAction(
            tool=call.group(1),
            arguments=arguments,
            format="legacy",
        )
