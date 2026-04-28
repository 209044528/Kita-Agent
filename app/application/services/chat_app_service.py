from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import ILlmService
from app.infrastructure.repository.memory_agent_repo import MemoryAgentRepository
from app.domain.agent.prompt import AGENT_SYSTEM_PROMPT

class ChatAppService:
    """
    应用服务层：负责业务流程编排
    """
    def __init__(self, llm_service: ILlmService):
        self.llm_service = llm_service
        self.agent_repo = MemoryAgentRepository()

    def do_chat(self, session_id: str, user_input: str) -> str:
        """
        执行一次完整的对话业务流
        """
        # 1. 提：从仓储中获取或创建 Agent 聚合根
        agent = self.agent_repo.get_by_id(session_id)
        if not agent:
            agent = AgentEntity(
                session_id=session_id,
                system_prompt=AGENT_SYSTEM_PROMPT
            )

        # 2. 调：调用行为进行思考和对话
        reply = agent.process_chat(user_input, self.llm_service)

        # 3. 存：将更新状态后的 Agent 存回仓储
        self.agent_repo.save(agent)

        return reply