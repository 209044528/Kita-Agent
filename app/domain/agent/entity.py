from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from app.domain.agent.repository import ILLMClient
from app.domain.agent.tool import ToolRegistry
from app.domain.agent.tool_call import ToolCallParser


class AgentEntity(BaseModel):
    """Agent aggregate with a bounded ReAct loop."""

    session_id: str
    title: str = ""
    system_prompt: str = ""
    messages: List[Dict[str, str]] = Field(default_factory=list)

    def __init__(self, **data: Any):
        super().__init__(**data)
        if self.system_prompt and not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})

    async def stream_chat(
        self,
        user_input: str,
        llm_client: ILLMClient,
        model_name: Optional[str] = None,
        original_user_input: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None,
        observability: Any = None,
        max_steps: int = 5,
    ) -> AsyncGenerator[str, None]:
        display_input = original_user_input or user_input
        self.messages.append({"role": "user", "content": display_input})
        working_messages = self.messages.copy()
        parser = ToolCallParser()
        trace_id = (
            observability.start_trace(self.session_id, display_input, model_name)
            if observability
            else None
        )

        for step in range(1, max_steps + 1):
            logger.info("[Agent step] session={} step={}", self.session_id, step)
            yield "💡 正在思考... " if step == 1 else f"\n🔎 正在进行第 {step} 步检索... "

            full_reply = ""
            async for chunk in llm_client.stream_chat(working_messages, model=model_name):
                full_reply += chunk

            working_messages.append({"role": "assistant", "content": full_reply})
            if observability:
                observability.record_event(
                    trace_id=trace_id,
                    session_id=self.session_id,
                    event_type="model_output",
                    step=step,
                    payload={"output": full_reply, "model": model_name},
                )

            try:
                action = parser.parse(full_reply)
            except ValueError as exc:
                logger.warning("[Agent parse failure] step={} error={}", step, exc)
                if observability:
                    observability.record_bad_case(
                        category="tool_call_parse_failure",
                        session_id=self.session_id,
                        trace_id=trace_id,
                        input_text=display_input,
                        detail=str(exc),
                        model_output=full_reply,
                    )
                working_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Observation: 输出无法解析。请只返回一个合法 JSON 对象，"
                            "字段为 tool、arguments，可选 thought。"
                        ),
                    }
                )
                continue

            if action.is_finish:
                final_answer = action.final_answer or ""
                yield f"\n{final_answer}"
                self.messages.append({"role": "assistant", "content": final_answer})
                if observability:
                    observability.finish_trace(
                        trace_id, self.session_id, final_answer, step, success=True
                    )
                return

            observation = self._execute_tool(
                action.tool,
                action.arguments,
                tool_registry,
                trace_id=trace_id,
                step=step,
            )
            logger.info("[Tool execution] {} -> {}", action.tool, observation)
            yield " ✅ 已完成工具调用\n"
            working_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Observation: "
                        + observation
                        + "\n请继续按结构化动作协议输出下一个 JSON 对象。"
                    ),
                }
            )

        error_msg = "\n❌ Kita 达到最大推理步数，任务已终止。"
        yield error_msg
        self.messages.append({"role": "assistant", "content": error_msg})
        if observability:
            observability.record_bad_case(
                category="max_steps_exceeded",
                session_id=self.session_id,
                trace_id=trace_id,
                input_text=display_input,
                detail=f"Exceeded {max_steps} steps",
            )
            observability.finish_trace(
                trace_id, self.session_id, error_msg, max_steps, success=False
            )

    def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_registry: Optional[ToolRegistry] = None,
        *,
        trace_id: str | None = None,
        step: int | None = None,
    ) -> str:
        if not tool_registry:
            return "错误: 工具注册中心未初始化。"
        return tool_registry.execute(
            tool_name,
            tool_args,
            session_id=self.session_id,
            trace_id=trace_id,
            step=step,
        )
