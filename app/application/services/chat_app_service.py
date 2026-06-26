import asyncio
from typing import AsyncGenerator
from app.domain.agent.entity import AgentEntity
from app.domain.agent.repository import ILLMClient, IAgentRepository
from app.application.services.knowledge_app_service import KnowledgeAppService
from app.application.services.intent_service import IntentTreeService
from app.domain.agent.prompt import DEFAULT_PERSONA_PROMPT, build_react_instruction_prompt
from app.domain.agent.tool import ToolRegistry
from app.domain.agent.tools.knowledge_search_tool import KnowledgeSearchTool
from app.domain.agent.tools.mcp_call_tool import MCPCallTool
from app.core.config import settings
from app.core.run_context import AgentRunContext
from app.core.security import RequestIdentity
from app.core.task_manager import AgentTaskManager
from app.domain.agent.events import AgentStreamEvent
from app.infrastructure.mcp.client import MCPClientService

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
        task_manager: AgentTaskManager | None = None,
        intent_service: IntentTreeService | None = None,
        mcp_client: MCPClientService | None = None,
    ):
        self.llm_client = llm_client
        self.agent_repo = agent_repo
        self.knowledge_service = knowledge_service
        self.observability = observability
        self.task_manager = task_manager
        self.intent_service = intent_service
        self.mcp_client = mcp_client

        # 初始化工具注册中心
        self.tool_registry = ToolRegistry(
            observability=observability,
            timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
        )
        if knowledge_service:
            self.tool_registry.register(KnowledgeSearchTool(knowledge_service))
        if mcp_client:
            self.tool_registry.register(MCPCallTool(mcp_client))

    async def do_stream_chat(
        self,
        session_id: str,
        user_input: str,
        model_name: str | None = None,
        system_prompt: str | None = None,
        identity: RequestIdentity | None = None,
        task_id: str | None = None,
        knowledge_tag: str | None = None,
        knowledge_dir: str | None = None,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """
        执行流式对话业务流
        """
        identity = identity or RequestIdentity("anonymous", "admin")
        custom_prompt = await asyncio.to_thread(
            self.agent_repo.get_prompt, session_id, identity.user_id
        )
        requested_prompt = system_prompt.strip() if system_prompt else None
        user_persona = (
            requested_prompt
            or (custom_prompt.strip() if custom_prompt else DEFAULT_PERSONA_PROMPT)
        )

        intent_route = self.intent_service.route(user_input, identity) if self.intent_service else None
        effective_user_input = (
            intent_route.rewritten_query
            if intent_route and intent_route.rewritten_query
            else user_input
        )
        if intent_route and intent_route.knowledge_tag and not knowledge_tag:
            knowledge_tag = intent_route.knowledge_tag
        if intent_route and intent_route.knowledge_dir and not knowledge_dir:
            knowledge_dir = intent_route.knowledge_dir

        tool_descriptions = self.tool_registry.generate_tool_prompt()
        react_instruction = build_react_instruction_prompt(tool_descriptions)
        final_system_prompt = f"{user_persona}\n\n{react_instruction}"
        if intent_route and intent_route.has_route:
            final_system_prompt += "\n\n" + intent_route.to_prompt_block()

        agent = await asyncio.to_thread(
            self.agent_repo.get, session_id, identity.user_id
        )
        if not agent:
            agent = AgentEntity(
                session_id=session_id,
                owner_user_id=identity.user_id,
                system_prompt=final_system_prompt,
            )
        elif agent.owner_user_id != identity.user_id:
            raise PermissionError("会话不属于当前用户")
        else:
            agent.system_prompt = final_system_prompt
            if agent.messages and agent.messages[0]["role"] == "system":
                agent.messages[0]["content"] = final_system_prompt
            elif not agent.messages or agent.messages[0]["role"] != "system":
                agent.messages.insert(0, {"role": "system", "content": final_system_prompt})

        if agent.conversation_summary:
            summary_block = (
                "\n\n【对话摘要记忆】\n"
                f"{agent.conversation_summary}\n"
                "请把这些摘要作为长期上下文，但不要逐字复述。"
            )
            agent.system_prompt = final_system_prompt + summary_block
            if agent.messages and agent.messages[0]["role"] == "system":
                agent.messages[0]["content"] = agent.system_prompt

        # 执行流式对话
        full_reply_content = ""
        if intent_route and intent_route.has_route:
            yield AgentStreamEvent(event="intent", data=intent_route.to_dict())

        run_context = AgentRunContext(
            task_id=task_id or "",
            identity=identity,
            session_id=session_id,
            knowledge_tag=knowledge_tag,
            knowledge_dir=knowledge_dir,
            task_manager=self.task_manager,
        )
        async for event in agent.stream_events(
            effective_user_input,
            self.llm_client,
            model_name=model_name,
            original_user_input=user_input,
            tool_registry=self.tool_registry,
            observability=self.observability,
            run_context=run_context,
        ):
            if event.content:
                full_reply_content += event.content
            yield event

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

        await self._maybe_update_summary(agent, model_name=model_name)

        await asyncio.to_thread(self.agent_repo.save, agent, identity.user_id)

    async def _maybe_update_summary(self, agent: AgentEntity, model_name: str | None = None) -> None:
        non_system = [m for m in agent.messages if m.get("role") != "system"]
        if len(non_system) <= settings.SUMMARY_TRIGGER_MESSAGES:
            return

        keep = max(settings.SUMMARY_KEEP_RECENT_MESSAGES, 2)
        to_summarize = non_system[:-keep]
        if not to_summarize:
            return

        transcript = "\n".join(
            f"{m.get('role')}: {m.get('content', '')}" for m in to_summarize
        )[-8000:]
        prompt = [
            {
                "role": "user",
                "content": (
                    "请将以下对话压缩为可供后续 Agent 使用的长期摘要记忆。"
                    "保留用户偏好、已确认事实、任务进展、重要约束；不要编造。\n\n"
                    f"已有摘要：{agent.conversation_summary or '无'}\n\n"
                    f"待压缩对话：\n{transcript}"
                ),
            }
        ]
        try:
            summary = ""
            async for chunk in self.llm_client.stream_chat(prompt, model=model_name):
                summary += chunk
            agent.conversation_summary = summary.strip()[:4000]
            system = agent.messages[0] if agent.messages and agent.messages[0].get("role") == "system" else None
            recent = non_system[-keep:]
            agent.messages = ([system] if system else []) + recent
        except Exception:
            # Summarization is an optimization; keep the full conversation on failure.
            return
