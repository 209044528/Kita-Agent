from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import ILlmService
from app.infrastructure.repository.redis_agent_repo import RedisAgentRepository
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.domain.agent.prompt import DEFAULT_PERSONA_PROMPT, REACT_INSTRUCTION_PROMPT

class ChatAppService:
    """
    应用服务层：负责业务流程编排
    """
    def __init__(self, llm_service: ILlmService, knowledge_service: KnowledgeAppService | None = None):
        self.llm_service = llm_service
        self.agent_repo = RedisAgentRepository()
        self.knowledge_service = knowledge_service

    def do_chat(self, session_id: str, user_input: str, knowledge_tag: str | None = None, system_prompt: str | None = None) -> str:
        """
        执行一次完整的对话业务流
        """
        custom_prompt = self.agent_repo.get_prompt(session_id)
        user_persona = custom_prompt.strip() if custom_prompt else DEFAULT_PERSONA_PROMPT
        final_system_prompt = f"{user_persona}\n\n{REACT_INSTRUCTION_PROMPT}"

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

        # 2. 组装 RAG 上下文
        prompt_input = user_input
        original_input = user_input
        if self.knowledge_service:
            knowledge_context = self.knowledge_service.retrieve_knowledge(user_input, knowledge_tag)
            if knowledge_context:
                prompt_input = (
                    "请优先参考以下知识库内容回答，如果知识不足请明确说明。\n"
                    f"[Knowledge Context]\n{knowledge_context}\n\n"
                    f"[User Question]\n{user_input}"
                )

        # 3. 执行对话
        reply = agent.process_chat(prompt_input, self.llm_service, original_user_input=original_input, knowledge_service=self.knowledge_service)

        if not agent.title:
            summary_prompt = [{"role": "user",
                               "content": f"请为以下对话起一个极其简短的标题（不超过10个字）：\n用户：{original_input}\n助手：{reply}"}]
            try:
                title_gen = self.llm_service.generate_reply(summary_prompt)
                agent.title = title_gen.strip().replace("“", "").replace("”", "")
            except:
                agent.title = original_input[:15] + ("..." if len(original_input) > 15 else "")

        # 4. 存回仓储
        self.agent_repo.save(agent)

        return reply