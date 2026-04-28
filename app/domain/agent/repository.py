from abc import ABC, abstractmethod

class ILlmService(ABC):
    @abstractmethod
    def generate_reply(self, messages: list) -> str:
        pass