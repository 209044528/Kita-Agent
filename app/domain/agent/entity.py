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
    title: str = ""
    system_prompt: str = ""
    messages: List[Dict[str, str]] = Field(default_factory=list)

    def __init__(self, **data):
        super().__init__(**data)
        if self.system_prompt and not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})

    def process_chat(self, user_input: str, llm_service: ILlmService, original_user_input: str | None = None, knowledge_service=None) -> str:
        """
        处理对话，支持 RAG 增强的输入

        Args:
            user_input: 实际发送给 LLM 的输入（可能包含 RAG 上下文）
            original_user_input: 用户的原始问题（用于存储到历史记录）
            knowledge_service: 知识库服务实例，用于工具调用时检索知识
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

                # 解析参数（支持 query 和 tag）
                tool_args = {}
                query_match = re.search(r'query\s*=\s*"([^"]*)"', args_str)
                tag_match = re.search(r'tag\s*=\s*"([^"]*)"', args_str)

                if query_match:
                    tool_args['query'] = query_match.group(1)
                if tag_match:
                    tool_args['tag'] = tag_match.group(1)

                observation_result = self._execute_tool(tool_name, tool_args, knowledge_service)
                print(f"🔧 [工具执行]: 调用 {tool_name}, 参数: {tool_args}, 结果: {observation_result}")

                working_messages.append({"role": "user", "content": f"Observation: {observation_result}"})
                continue

            print("⚠️ [系统警告]: AI 输出格式不规范，强制纠正...")
            working_messages.append(
                {"role": "user", "content": "Observation: 错误，请严格按照 'Thought: ... Action: ...' 格式输出。"})

        error_msg = "❌ Kita 思考了太多次都没有得出结果，任务已强制终止。"
        self.messages.append({"role": "assistant", "content": error_msg})
        return error_msg

    def _execute_tool(self, tool_name: str, tool_args: dict, knowledge_service=None) -> str:
        """
        内部工具执行器。
        """
        if tool_name == "knowledge_search":
            if not knowledge_service:
                return "错误: 知识库服务未初始化，无法执行检索。"

            query = tool_args.get('query')
            if not query:
                return "错误: 缺少必需参数 query。"

            tag = tool_args.get('tag')

            try:
                result = knowledge_service.retrieve_knowledge(query, tag)
                if not result or result.strip() == "":
                    return "未找到相关知识，请尝试其他关键词或直接回答用户问题。"
                return result
            except Exception as e:
                return f"知识库检索错误: {e}"

        return f"错误: 找不到名为 '{tool_name}' 的工具。"