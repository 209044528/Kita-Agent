from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """工具参数定义"""
    name: str
    type: str
    description: str
    required: bool = True


class BaseTool(ABC):
    """工具基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，用于生成提示词"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        """工具参数定义"""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """
        执行工具逻辑

        Args:
            **kwargs: 工具参数

        Returns:
            执行结果字符串
        """
        pass

    def validate_args(self, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证参数

        Returns:
            (是否有效, 错误信息)
        """
        required_params = {p.name for p in self.parameters if p.required}
        provided_params = set(args.keys())

        missing = required_params - provided_params
        if missing:
            return False, f"缺少必需参数: {', '.join(missing)}"

        return True, None

    def format_for_prompt(self) -> str:
        """格式化为提示词中的工具描述"""
        params_str = ", ".join([
            f'{p.name}="{p.description}"' for p in self.parameters
        ])
        return f"{self.name}({params_str})"


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(tool_name)

    def list_tools(self) -> list[BaseTool]:
        """列出所有工具"""
        return list(self._tools.values())

    def execute(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        执行工具

        Args:
            tool_name: 工具名称
            args: 工具参数

        Returns:
            执行结果
        """
        tool = self.get(tool_name)
        if not tool:
            return f"错误: 找不到名为 '{tool_name}' 的工具。"

        is_valid, error_msg = tool.validate_args(args)
        if not is_valid:
            return f"错误: {error_msg}"

        try:
            return tool.execute(**args)
        except Exception as e:
            return f"工具执行错误: {e}"

    def generate_tool_prompt(self) -> str:
        """生成工具提示词"""
        if not self._tools:
            return ""

        tool_descriptions = [f"- {tool.format_for_prompt()}: {tool.description}"
                           for tool in self._tools.values()]

        return "【可用工具】\n" + "\n".join(tool_descriptions)
