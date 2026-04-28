import time
from openai import OpenAI
from app.core.config import settings
from app.domain.agent.repository import ILlmService

class OpenAILlmServiceImpl(ILlmService):
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        self.model_name = settings.MODEL_NAME

    def generate_reply(self, messages: list) -> str:
        for attempt in range(3):
            try:
                print(f"   ⏳ 正在向 LLM 发送网络请求 (尝试 {attempt + 1}/3)...")
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.7
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                if attempt == 2:
                    return f"系统错误: {str(e)}"
                time.sleep(2)