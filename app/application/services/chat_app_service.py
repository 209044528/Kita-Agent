from typing import AsyncGenerator
from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import ILLMClient, IAgentRepository
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.domain.agent.prompt import DEFAULT_PERSONA_PROMPT, build_react_instruction_prompt
from app.domain.agent.tool import ToolRegistry
from app.domain.agent.tools.knowledge_search_tool import KnowledgeSearchTool

class ChatAppService:
    """
    应用服务层：负责业务流程编排
    """
    def __init__(
        self, 
        llm_client: ILLMClient, 
        agent_repo: IAgentRepository,
        knowledge_service: KnowledgeAppService | None = None,
        observability=None,
    ):
        self.llm_client = llm_client
        self.agent_repo = agent_repo
        self.knowledge_service = knowledge_service
        self.observability = observability

        # 初始化工具注册中心
        self.tool_registry = ToolRegistry(observability=observability)
        if knowledge_service:
            self.tool_registry.register(KnowledgeSearchTool(knowledge_service))

    async def do_stream_chat(
        self,
        session_id: str,
        user_input: str,
        model_name: str | None = None,
        system_prompt: str | None = None
    ) -> AsyncGenerator[str, None]:
        """
        执行流式对话业务流
        """
        custom_prompt = self.agent_repo.get_prompt(session_id)
        user_persona = custom_prompt.strip() if custom_prompt else DEFAULT_PERSONA_PROMPT

        tool_descriptions = self.tool_registry.generate_tool_prompt()
        react_instruction = build_react_instruction_prompt(tool_descriptions)
        final_system_prompt = f"{user_persona}\n\n{react_instruction}"

        agent = self.agent_repo.get(session_id)
        if not agent:
            agent = AgentEntity(session_id=session_id, system_prompt=final_system_prompt)
        elif system_prompt:
            agent.system_prompt = final_system_prompt
            if agent.messages and agent.messages[0]["role"] == "system":
                agent.messages[0]["content"] = final_system_prompt
            elif not agent.messages or agent.messages[0]["role"] != "system":
                agent.messages.insert(0, {"role": "system", "content": final_system_prompt})

        # 执行流式对话
        full_reply_content = ""
        async for chunk in agent.stream_chat(
            user_input,
            self.llm_client,
            model_name=model_name,
            tool_registry=self.tool_registry,
            observability=self.observability,
        ):
            full_reply_content += chunk
            yield chunk

        # 存回仓储
        if not agent.title and agent.messages:
            assistant_msgs = [m for m in agent.messages if m["role"] == "assistant"]
            last_reply = assistant_msgs[-1]["content"] if assistant_msgs else full_reply_content

            summary_prompt = [{"role": "user",
                               "content": f"请为以下对话起一个极其简短的标题（不超过10个字）：\n用户：{user_input}\n助手：{last_reply}"}]
            try:
                title_gen = ""
                async for chunk in self.llm_client.stream_chat(summary_prompt, model=model_name):
                    title_gen += chunk
                agent.title = title_gen.strip().replace("“", "").replace("”", "")
            except:
                agent.title = user_input[:15] + ("..." if len(user_input) > 15 else "")

        self.agent_repo.save(agent)
