import redis
from app.domain.agent.entity import AgentEntity
from app.core.config import settings


class RedisAgentRepository:
    def __init__(self):
        # 初始化 Redis 客户端
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.ttl = settings.SESSION_TTL

    def _get_key(self, session_id: str) -> str:
        return f"kita:agent:session:{session_id}"

    def get(self, session_id: str) -> AgentEntity | None:
        """从 Redis 获取 Agent 实体"""
        data = self.client.get(self._get_key(session_id))
        if data and data.strip():
            # 利用 Pydantic 的能力直接从 JSON 重建实体
            return AgentEntity.model_validate_json(data)
        return None

    def save(self, agent: AgentEntity) -> None:
        """保存 Agent 实体到 Redis，并刷新过期时间"""
        # 序列化为 JSON 字符串
        data = agent.model_dump_json()
        session_id = agent.session_id

        # 使用 setex 设置键值对的同时设置过期时间
        self.client.setex(
            name=self._get_key(session_id),
            time=self.ttl,
            value=data
        )

    def delete(self, session_id: str) -> None:
        """可选：手动清理会话"""
        self.client.delete(self._get_key(session_id))

    def list_sessions(self) -> list[str]:
        """获取所有会话 ID 列表"""
        keys = self.client.keys("kita:agent:session:*")
        return [k.split(":")[-1] for k in keys]

    def save_prompt(self, session_id: str, prompt: str) -> None:
        """保存自定义提示词到 Redis，默认 24 小时 (86400秒) 过期"""
        self.client.setex(
            name=f"kita:prompt:{session_id}",
            time=86400,  # 24小时
            value=prompt
        )

    def get_prompt(self, session_id: str) -> str | None:
        """从 Redis 获取该会话的自定义提示词"""
        return self.client.get(f"kita:prompt:{session_id}")