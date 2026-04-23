class Memory:
    def __init__(self, system_prompt: str):
        self.messages = [
            {"role": "system", "content": system_prompt}
        ]

    def add_user_message(self, text: str):
        """记录用户的发言"""
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        """记录 AI 的发言"""
        self.messages.append({"role": "assistant", "content": text})

    def get_messages(self) -> list:
        """获取完整的聊天记录列表"""
        return self.messages