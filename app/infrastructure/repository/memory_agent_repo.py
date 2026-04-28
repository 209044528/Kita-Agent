from typing import Dict, Optional
from app.domain.agent.entity import AgentEntity

class MemoryAgentRepository:
    """
    内存版仓储实现
    """
    _storage: Dict[str, AgentEntity] = {}

    def get_by_id(self, session_id: str) -> Optional[AgentEntity]:
        return self._storage.get(session_id)

    def save(self, agent: AgentEntity):
        self._storage[agent.session_id] = agent