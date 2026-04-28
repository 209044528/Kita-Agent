from pydantic import BaseModel
from typing import List, Dict

class Message(BaseModel):
    role: str
    content: str

class Memory(BaseModel):
    # 领域属性
    messages: List[Message] = []

    # 领域行为
    def add_system_prompt(self, prompt: str):
        if not self.messages or self.messages[0].role != "system":
            self.messages.insert(0, Message(role="system", content=prompt))

    def add_user_message(self, text: str):
        self.messages.append(Message(role="user", content=text))

    def add_assistant_message(self, text: str):
        self.messages.append(Message(role="assistant", content=text))

    def get_messages_dict(self) -> List[Dict[str, str]]:
        # 将 Pydantic 对象转为 OpenAI API 需要的字典格式
        return [msg.model_dump() for msg in self.messages]