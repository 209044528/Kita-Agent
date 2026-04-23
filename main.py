import os
from dotenv import load_dotenv

from core.llm_api import chat_with_llm

load_dotenv()


def main():
    print("🤖 欢迎来到 Kita-Agent 控制台！环境启动成功。")
    print("-" * 40)
    print("现在你可以和 Kita 聊天了（输入 'quit' 或 'exit' 退出）\n")

    while True:
        user_input = input("你: ")

        if user_input.lower() in ['quit', 'exit']:
            print("Kita-Agent 已关闭。下次见！")
            break

        if not user_input.strip():
            continue

        print("Kita 思考中...")

        reply = chat_with_llm(user_input)

        print(f"Kita: {reply}\n")


if __name__ == "__main__":
    main()