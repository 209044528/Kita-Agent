import re
from dotenv import load_dotenv

from core.llm_api import chat_with_llm
from core.memory import Memory
from core.prompt import AGENT_SYSTEM_PROMPT
from core.tools import AVAILABLE_TOOLS

load_dotenv()


def main():
    print("Kita-Agent 终端已启动！")
    print("-" * 50)

    # 提示词
    memory = Memory(system_prompt=AGENT_SYSTEM_PROMPT)

    while True:
        user_input = input("\n你: ")
        if user_input.lower() in ['quit', 'exit']:
            print("Kita-Agent 已关闭。")
            break
        if not user_input.strip():
            continue

        # 把用户的最新问题加入记忆
        memory.add_user_message(user_input)

        print("Kita 正在处理任务...\n")
        # 最多思考五步
        for step in range(5):
            # 发送所有的上下文让大模型决策
            llm_reply = chat_with_llm(memory.get_messages())

            # 把大模型本次的思考过程也存入记忆，保持上下文连贯
            memory.add_assistant_message(llm_reply)

            # 打印 AI 的内部思考过程
            print(f"--- [内部思考 第 {step + 1} 步] ---")
            print(f"{llm_reply}\n")

            # 解析 1: 判断是不是结束动作 Finish[...]
            finish_match = re.search(r"Action:\s*Finish\[(.*)\]", llm_reply, re.DOTALL)
            if finish_match:
                final_answer = finish_match.group(1).strip()
                print(f"✅ Kita 最终回答: {final_answer}")
                # 任务完成，跳出这个 5 次的内部循环，等待用户的下一个提问
                break

            # 解析 2: 判断是不是调用工具 tool_name(kwarg="value") group(1) 单词词组、group(2) 任意内容
            tool_match = re.search(r"Action:\s*(\w+)\((.*)\)", llm_reply)
            if tool_match:
                tool_name = tool_match.group(1)
                args_str = tool_match.group(2)

                # 提取参数值
                arg_value_match = re.search(r'="?([^"]*)"?', args_str)
                arg_value = arg_value_match.group(1) if arg_value_match else args_str

                # 执行本地工具
                if tool_name in AVAILABLE_TOOLS:
                    print(f"🔧 [系统操作]: 正在调用工具 '{tool_name}', 参数: {arg_value}")
                    # 调用 tools.py
                    observation_result = AVAILABLE_TOOLS[tool_name](arg_value)
                else:
                    observation_result = f"错误: 找不到名为 '{tool_name}' 的工具。"

                print(f"👁️ [观察结果]: {observation_result}")

                memory.add_user_message(f"Observation: {observation_result}")
                continue

            print("⚠️ [系统警告]: AI 输出格式不规范，强制纠正...")
            memory.add_user_message("Observation: 错误，请严格按照 'Thought: ... Action: ...' 格式输出。")

        else:
            print("❌ Kita 思考了太多次都没有得出结果，任务已强制终止。")


if __name__ == "__main__":
    main()