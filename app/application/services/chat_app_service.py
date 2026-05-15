from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import ILlmService
from app.infrastructure.repository.redis_agent_repo import RedisAgentRepository
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.domain.agent.prompt import DEFAULT_PERSONA_PROMPT, build_react_instruction_prompt
from app.domain.agent.tool import ToolRegistry
from app.domain.agent.tools.knowledge_search_tool import KnowledgeSearchTool

class ChatAppService:
    """
    应用服务层：负责业务流程编排
    """
    def __init__(self, llm_service: ILlmService, knowledge_service: KnowledgeAppService | None = None):
        self.llm_service = llm_service
        self.agent_repo = RedisAgentRepository()
        self.knowledge_service = knowledge_service

        # 初始化工具注册中心
        self.tool_registry = ToolRegistry()
        if knowledge_service:
            self.tool_registry.register(KnowledgeSearchTool(knowledge_service))

    def do_chat(self, session_id: str, user_input: str, knowledge_tag: str | None = None, system_prompt: str | None = None) -> str:
        """
        执行一次完整的对话业务流
        """
        custom_prompt = self.agent_repo.get_prompt(session_id)
        user_persona = custom_prompt.strip() if custom_prompt else DEFAULT_PERSONA_PROMPT

        # 构建系统提示词（包含工具描述）
        tool_descriptions = self.tool_registry.generate_tool_prompt()
        react_instruction = build_react_instruction_prompt(tool_descriptions)
        final_system_prompt = f"{user_persona}\n\n{react_instruction}"

        # 1. 从仓储中获取或创建 Agent
        agent = self.agent_repo.get(session_id)
        if not agent:
            agent = AgentEntity(
                session_id=session_id,
                system_prompt=final_system_prompt
            )
        elif system_prompt:
            # 如果是已有会话且用户修改了提示词，动态更新其内部状态
            agent.system_prompt = final_system_prompt
            if agent.messages and agent.messages[0]["role"] == "system":
                agent.messages[0]["content"] = final_system_prompt
            elif not agent.messages or agent.messages[0]["role"] != "system":
                agent.messages.insert(0, {"role": "system", "content": final_system_prompt})

        # 2. 执行对话（移除被动 RAG 拼接，让 Agent 主动调用工具）
        reply = agent.process_chat(user_input, self.llm_service, tool_registry=self.tool_registry)

        if not agent.title:
            summary_prompt = [{"role": "user",
                               "content": f"请为以下对话起一个极其简短的标题（不超过10个字）：\n用户：{user_input}\n助手：{reply}"}]
            try:
                title_gen = self.llm_service.generate_reply(summary_prompt)
                agent.title = title_gen.strip().replace("””, “").replace("””, “")
            except:
                agent.title = user_input[:15] + ("..." if len(user_input) > 15 else "")

        # 4. 存回仓储
        self.agent_repo.save(agent)

        return reply