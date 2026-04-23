import os
from dotenv import load_dotenv

from core.llm_api import chat_with_llm
from core.memory import Memory

load_dotenv()

# 定义 Kita 的人设
SYSTEM_PROMPT = """你叫 Kita，是一个幽默、专业的 AI 编程助手。
你的回答应该简明扼要。当你不知道答案时，你会诚实地说不知道。"""

def main():
    print("🤖 欢迎来到 Kita-Agent 控制台！环境启动成功。")
    print("-" * 40)

    memory = Memory(system_prompt=SYSTEM_PROMPT)

    print("现在你可以和 Kita 聊天了（输入 'quit' 或 'exit' 退出）\n")

    while True:
        user_input = input("你: ")

        if user_input.lower() in ['quit', 'exit']:
            print("Kita-Agent 已关闭。下次见！")
            break

        if not user_input.strip():
            continue

        memory.add_user_message(user_input)

        print("Kita 思考中...")

        reply = chat_with_llm(memory.get_messages())

        memory.add_assistant_message(reply)

        print(f"Kita: {reply}\n")


if __name__ == "__main__":
    main()