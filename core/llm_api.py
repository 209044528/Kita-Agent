import os
import time
from openai import OpenAI
from dotenv import load_dotenv

# os读取env
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")
model_name = os.getenv("MODEL_NAME")

# 调用智能体
client = OpenAI(
    api_key=api_key,
    base_url=base_url
)


def chat_with_llm(user_message: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            # 打包发送 client-交流/图画-补全
            response = client.chat.completions.create(
                model=model_name, # type: ignore
                messages=[ # type: ignore
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7
            )
            # 请求-第0个回答（有多个）-信息内容
            content = response.choices[0].message.content
            return content or ""

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate limited" in error_msg.lower():
                print(f"⚠️ [系统提示] 触发 API 限流，等待 2 秒后进行第 {attempt + 1} 次重试...")
                time.sleep(2)
                continue
            else:
                return f"请求 API 时发生严重错误: {e}"

    return "❌ 哎呀，API 服务器太拥挤了，我重试了好几次都没成功，请稍后再试吧。"