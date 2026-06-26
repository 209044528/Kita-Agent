from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentStreamEvent:
    event: str
    content: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        payload = dict(self.data)
        if self.content is not None:
            payload["content"] = self.content
        return payload
