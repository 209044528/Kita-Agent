import re
from loguru import logger
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, AsyncGenerator
from app.domain.agent.repository import ILLMClient
from app.domain.agent.tool import ToolRegistry


class AgentEntity(BaseModel):
    """
    Agent 聚合根 (充血模型)
    自带 ReAct 推理循环逻辑。
    """
    session_id: str
    title: str = ""
    system_prompt: str = ""
    messages: List[Dict[str, str]] = Field(default_factory=list)

    def __init__(self, **data):
        super().__init__(**data)
        if self.system_prompt and not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})

    async def stream_chat(
        self,
        user_input: str,
        llm_client: ILLMClient,
        model_name: Optional[str] = None,
        original_user_input: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式处理对话，执行 ReAct 推理循环并逐块产出内容
        仅产出 Finish[...] 中的最终答案。
        """
        display_input = original_user_input if original_user_input else user_input
        self.messages.append({"role": "user", "content": display_input})
        working_messages = self.messages.copy()

        for step in range(5):
            logger.info(f"[流式内部思考 第 {step + 1} 步]")
            
            # 实时反馈：展示当前步骤，避免用户焦虑
            if step == 0:
                yield "💡 正在思考... "
            else:
                yield f"\n🔍 正在进行第 {step + 1} 步搜索... "

            full_reply = ""
            finish_found = False
            finish_marker_pos = -1
            last_yield_pos = -1

            async for chunk in llm_client.stream_chat(working_messages, model=model_name):
                full_reply += chunk
                
                if not finish_found:
                    # 灵活匹配 Action: Finish[
                    match = re.search(r"Action:\s*Finish\[", full_reply, re.IGNORECASE)
                    if match:
                        finish_found = True
                        finish_marker_pos = match.end()
                        last_yield_pos = finish_marker_pos
                        # 首次发现 Finish 时，如果是新起一行，可以做个换行处理
                        yield "\n" 
                
                if finish_found:
                    # 提取 Finish[ 之后到当前末尾的内容
                    content_so_far = full_reply[last_yield_pos:]
                    
                    # 检查是否有结束括号
                    if "]" in content_so_far:
                        content_so_far = content_so_far[:content_so_far.find("]")]
                    
                    if content_so_far:
                        yield content_so_far
                        last_yield_pos += len(content_so_far)
            
            working_messages.append({"role": "assistant", "content": full_reply})

            # 解析 1: 检查是否结束思考 (保留原有解析逻辑用于循环控制)
            finish_match = re.search(r"Action:\s*Finish\[(.*)\]", full_reply, re.DOTALL)
            if finish_match:
                final_answer = finish_match.group(1).strip()
                self.messages.append({"role": "assistant", "content": final_answer})
                return

            elif re.search(r"Action:\s*Finish", full_reply, re.IGNORECASE):
                # 备选解析
                parts = re.split(r"Action:\s*Finish", full_reply, flags=re.IGNORECASE)
                content = parts[-1].strip()
                final_answer = content[1:-1].strip() if content.startswith("[") else content.strip("]")
                self.messages.append({"role": "assistant", "content": final_answer})
                return

            # 解析 2: 检查是否需要调用工具
            tool_match = re.search(r"Action:\s*(\w+)\((.*)\)", full_reply, re.DOTALL)
            if tool_match:
                tool_name = tool_match.group(1)
                args_str = tool_match.group(2).strip()

                tool_args = {}
                query_match = re.search(r'query\s*=\s*"([^"]*)"', args_str)
                tag_match = re.search(r'tag\s*=\s*"([^"]*)"', args_str)
                if query_match: tool_args['query'] = query_match.group(1)
                if tag_match: tool_args['tag'] = tag_match.group(1)
                
                observation_result = self._execute_tool(tool_name, tool_args, tool_registry)
                logger.info(f"[工具执行]: {tool_name} -> {observation_result}")

                yield " ✓ 已找到相关信息\n"
                working_messages.append({"role": "user", "content": f"Observation: {observation_result}"})
                continue

            # 异常处理
            logger.warning(f"[系统警告]: AI 第 {step+1} 步输出格式不规范")
            working_messages.append({"role": "user", "content": "Observation: 错误，请严格按照 'Thought: ... Action: ...' 格式输出。"})

        error_msg = "\n❌ Kita 思考了太多次都没有得出结果，任务已强制终止。"
        yield error_msg
        self.messages.append({"role": "assistant", "content": error_msg})

    def _execute_tool(self, tool_name: str, tool_args: dict, tool_registry: Optional[ToolRegistry] = None) -> str:
        """
        内部工具执行器，通过 ToolRegistry 动态路由
        """
        if not tool_registry:
            return "错误: 工具注册中心未初始化，无法执行工具调用。"

        return tool_registry.execute(tool_name, tool_args)