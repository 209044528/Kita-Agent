from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import AgentCancelledError
from app.core.security import RequestIdentity


@dataclass
class AgentRunContext:
    task_id: str
    identity: RequestIdentity
    session_id: str
    knowledge_tag: str | None = None
    knowledge_dir: str | None = None
    task_manager: object | None = None

    async def check_cancelled(self) -> None:
        if self.task_manager and await self.task_manager.is_cancelled(self.task_id):
            raise AgentCancelledError()
