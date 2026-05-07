import re
from pydantic import BaseModel, Field
from typing import List, Dict
from app.domain.agent.repository import ILlmService


class AgentEntity(BaseModel):
    """
    Agent 聚合根 (充血模型)
    自带 ReAct 推理循环逻辑。
    """
    session_id: str
    system_prompt: str = ""
    messages: List[Dict[str, str]] = Field(default_factory=list)

    def __init__(self, **data):
        super().__init__(**data)
        if self.system_prompt and not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})

    def process_chat(self, user_input: str, llm_service: ILlmService, original_user_input: str | None = None) -> str:
        """
        处理对话，支持 RAG 增强的输入

        Args:
            user_input: 实际发送给 LLM 的输入（可能包含 RAG 上下文）
            original_user_input: 用户的原始问题（用于存储到历史记录）
        """
        # 存储用户的原始问题到历史记录
        display_input = original_user_input if original_user_input else user_input
        self.messages.append({"role": "user", "content": display_input})

        # 使用完整输入（包含 RAG 上下文）构建工作消息列表
        working_messages = self.messages[:-1] + [{"role": "user", "content": user_input}]

        for step in range(5):
            print(f"\n🧠 --- [内部思考 第 {step + 1} 步] ---")

            # 获取 LLM 回答
            reply = llm_service.generate_reply(working_messages)

            print(f"💡 AI 输出:\n{reply}\n")

            working_messages.append({"role": "assistant", "content": reply})

            # 解析 1: 检查是否结束思考
            finish_match = re.search(r"Action:\s*Finish\[(.*?)\]", reply, re.DOTALL)
            if finish_match:
                final_answer = finish_match.group(1).strip()
                # 只保存最终答案到历史记录
                self.messages.append({"role": "assistant", "content": final_answer})
                return final_answer

            # 解析 2: 检查是否需要调用工具
            tool_match = re.search(r"Action:\s*(\w+)\((.*?)\)", reply)
            if tool_match:
                tool_name = tool_match.group(1)
                args_str = tool_match.group(2)

                arg_value_match = re.search(r'="?([^"]*)"?', args_str)
                arg_value = arg_value_match.group(1) if arg_value_match else args_str

                observation_result = self._execute_tool(tool_name, arg_value)
                print(f"🔧 [工具执行]: 调用 {tool_name}, 参数: {arg_value}, 结果: {observation_result}")

                working_messages.append({"role": "user", "content": f"Observation: {observation_result}"})
                continue

            print("⚠️ [系统警告]: AI 输出格式不规范，强制纠正...")
            working_messages.append(
                {"role": "user", "content": "Observation: 错误，请严格按照 'Thought: ... Action: ...' 格式输出。"})

        error_msg = "❌ Kita 思考了太多次都没有得出结果，任务已强制终止。"
        self.messages.append({"role": "assistant", "content": error_msg})
        return error_msg

    def _execute_tool(self, tool_name: str, arg_value: str) -> str:
        """
        内部工具执行器。
        """
        if tool_name == "calculator":
            try:
                # ⚠️ 注意：生产环境禁止直接 eval
                result = eval(arg_value)
                return str(result)
            except Exception as e:
                return f"计算错误，请检查表达式格式: {e}"

        return f"错误: 找不到名为 '{tool_name}' 的工具。"