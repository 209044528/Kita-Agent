import redis
from typing import List, Optional
from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import IAgentRepository
from app.core.config import settings


class RedisAgentRepository(IAgentRepository):
    def __init__(self):
        # 初始化 Redis 客户端
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.ttl = settings.SESSION_TTL

    def _get_key(self, session_id: str, user_id: str = "anonymous") -> str:
        return f"kita:agent:session:{user_id}:{session_id}"

    def get(self, session_id: str, user_id: str = "anonymous") -> Optional[AgentEntity]:
        """从 Redis 获取 Agent 实体"""
        data = self.client.get(self._get_key(session_id, user_id))
        if not data and user_id == "anonymous":
            data = self.client.get(f"kita:agent:session:{session_id}")
        if data and data.strip():
            agent = AgentEntity.model_validate_json(data)
            if agent.owner_user_id != user_id:
                return None
            return agent
        return None

    def save(self, agent: AgentEntity, user_id: str = "anonymous") -> None:
        """保存 Agent 实体到 Redis，并刷新过期时间"""
        # 序列化为 JSON 字符串
        data = agent.model_dump_json()
        session_id = agent.session_id

        # 使用 setex 设置键值对的同时设置过期时间
        self.client.setex(
            name=self._get_key(session_id, user_id),
            time=self.ttl,
            value=data
        )

    def delete(self, session_id: str, user_id: str = "anonymous") -> None:
        """手动清理会话"""
        self.client.delete(self._get_key(session_id, user_id))

    def list_sessions(self, user_id: str = "anonymous") -> List[str]:
        """获取所有会话 ID 列表"""
        keys = self.client.scan_iter(f"kita:agent:session:{user_id}:*")
        return [k.split(":")[-1] for k in keys]

    def save_prompt(
        self, session_id: str, prompt: str, user_id: str = "anonymous"
    ) -> None:
        """保存自定义提示词到 Redis，默认 24 小时 (86400秒) 过期"""
        self.client.setex(
            name=f"kita:prompt:{user_id}:{session_id}",
            time=86400,  # 24小时
            value=prompt
        )

    def get_prompt(self, session_id: str, user_id: str = "anonymous") -> Optional[str]:
        """从 Redis 获取该会话的自定义提示词"""
        return self.client.get(f"kita:prompt:{user_id}:{session_id}")
