import re
import logging
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from app.domain.agent.repository import ILlmService
from app.domain.agent.tool import ToolRegistry

logger = logging.getLogger(__name__)


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

    def process_chat(
        self,
        user_input: str,
        llm_service: ILlmService,
        original_user_input: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None
    ) -> str:
        """
        处理对话，执行 ReAct 推理循环

        Args:
            user_input: 用户输入
            llm_service: LLM 服务实例
            original_user_input: 用户的原始问题（用于存储到历史记录，如果与 user_input 不同）
            tool_registry: 工具注册中心，用于动态路由工具调用
        """
        # 存储用户输入到历史记录
        display_input = original_user_input if original_user_input else user_input
        self.messages.append({"role": "user", "content": display_input})

        # 构建工作消息列表
        working_messages = self.messages.copy()

        for step in range(5):
            logger.info(f"[内部思考 第 {step + 1} 步]")

            # 获取 LLM 回答
            reply = llm_service.generate_reply(working_messages)

            logger.info(f"AI 输出: {reply}")

            working_messages.append({"role": "assistant", "content": reply})

            # 解析 1: 检查是否结束思考 (使用贪婪匹配解决嵌套方括号问题)
            finish_match = re.search(r"Action:\s*Finish\[(.*)\]", reply, re.DOTALL)
            if finish_match:
                final_answer = finish_match.group(1).strip()
                # 只保存最终答案到历史记录
                self.messages.append({"role": "assistant", "content": final_answer})
                return final_answer

            elif re.search(r"Action:\s*Finish", reply, re.IGNORECASE):
                # 备选解析方案：寻找最后一个 ']'
                parts = re.split(r"Action:\s*Finish", reply, flags=re.IGNORECASE)
                content = parts[-1].strip()
                if content.startswith("["):
                    end_idx = content.rfind("]")
                    if end_idx != -1:
                        final_answer = content[1:end_idx].strip()
                    else:
                        final_answer = content[1:].strip()
                else:
                    final_answer = content.replace("]", "").strip()

                self.messages.append({"role": "assistant", "content": final_answer})
                return final_answer

            # 解析 2: 检查是否需要调用工具 (同样改为贪婪匹配，支持多行和嵌套圆括号)
            tool_match = re.search(r"Action:\s*(\w+)\((.*)\)", reply, re.DOTALL)
            if tool_match:
                tool_name = tool_match.group(1)
                args_str = tool_match.group(2).strip()

                # 解析参数（支持 query 和 tag）
                tool_args = {}
                query_match = re.search(r'query\s*=\s*"([^"]*)"', args_str)
                tag_match = re.search(r'tag\s*=\s*"([^"]*)"', args_str)

                if query_match:
                    tool_args['query'] = query_match.group(1)
                if tag_match:
                    tool_args['tag'] = tag_match.group(1)

                observation_result = self._execute_tool(tool_name, tool_args, tool_registry)
                logger.info(f"[工具执行]: 调用 {tool_name}, 参数: {tool_args}, 结果: {observation_result}")

                working_messages.append({"role": "user", "content": f"Observation: {observation_result}"})
                continue

            logger.warning("[系统警告]: AI 输出格式不规范，强制纠正")
            working_messages.append(
                {"role": "user", "content": "Observation: 错误，请严格按照 'Thought: ... Action: ...' 格式输出。"})

        error_msg = "❌ Kita 思考了太多次都没有得出结果，任务已强制终止。"
        self.messages.append({"role": "assistant", "content": error_msg})
        return error_msg

    def _execute_tool(self, tool_name: str, tool_args: dict, tool_registry: Optional[ToolRegistry] = None) -> str:
        """
        内部工具执行器，通过 ToolRegistry 动态路由

        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            tool_registry: 工具注册中心

        Returns:
            工具执行结果
        """
        if not tool_registry:
            return "错误: 工具注册中心未初始化，无法执行工具调用。"

        return tool_registry.execute(tool_name, tool_args)