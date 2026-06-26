from __future__ import annotations

import time
from abc import ABC, abstractmethod
import asyncio
import inspect
from typing import Any, Dict, Optional

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """A JSON-Schema-compatible tool parameter."""

    name: str
    type: str = "string"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[list[Any]] = None

    def to_json_schema(self) -> dict[str, Any]:
        schema_type: Any = self.type if self.required else [self.type, "null"]
        schema: dict[str, Any] = {
            "type": schema_type,
            "description": self.description,
        }
        if self.enum:
            schema["enum"] = self.enum
        if not self.required and self.default is not None:
            schema["default"] = self.default
        return schema


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")

    model_config = {"populate_by_name": True}


class BaseTool(ABC):
    """Base class shared by local Agent calls and MCP exposure."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        raise NotImplementedError

    async def execute_async(self, run_context: Any = None, **kwargs: Any) -> str:
        return await asyncio.to_thread(self.execute, **kwargs)

    @property
    def input_schema(self) -> dict[str, Any]:
        properties = {p.name: p.to_json_schema() for p in self.parameters}
        required = [p.name for p in self.parameters if p.required]
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def validate_args(self, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        errors = sorted(
            Draft202012Validator(self.input_schema).iter_errors(args),
            key=lambda error: list(error.path),
        )
        if not errors:
            return True, None
        return False, "; ".join(error.message for error in errors)

    def as_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    """Single source of truth for Agent, Function Calling, and MCP tools."""

    def __init__(self, observability: Any = None, timeout_seconds: float = 30.0):
        self._tools: Dict[str, BaseTool] = {}
        self._observability = observability
        self._timeout_seconds = timeout_seconds

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> Optional[BaseTool]:
        return self._tools.get(tool_name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def definitions(self) -> list[dict[str, Any]]:
        return [
            tool.as_definition().model_dump(by_alias=True)
            for tool in self._tools.values()
        ]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.as_openai_tool() for tool in self._tools.values()]

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        session_id: str | None = None,
        trace_id: str | None = None,
        step: int | None = None,
    ) -> str:
        started = time.perf_counter()
        success = False
        tool = self.get(tool_name)
        if not tool:
            result = f"错误: 找不到名为 '{tool_name}' 的工具。"
        else:
            is_valid, error_msg = tool.validate_args(args)
            if not is_valid:
                result = f"错误: 参数校验失败: {error_msg}"
            else:
                tool_task = None
                cancel_task = None
                try:
                    result = tool.execute(**args)
                    error_prefixes = ("错误:", "工具执行错误:", "知识库检索错误")
                    success = not result.startswith(error_prefixes)
                except Exception as exc:
                    result = f"工具执行错误: {exc}"

        duration_ms = (time.perf_counter() - started) * 1000
        if self._observability:
            self._observability.record_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=result,
                duration_ms=duration_ms,
                success=success,
                session_id=session_id,
                trace_id=trace_id,
                step=step,
            )
        return result

    async def async_execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        session_id: str | None = None,
        trace_id: str | None = None,
        step: int | None = None,
        run_context: Any = None,
    ) -> str:
        started = time.perf_counter()
        success = False
        tool = self.get(tool_name)
        if not tool:
            result = f"错误: 找不到名为 '{tool_name}' 的工具。"
        else:
            is_valid, error_msg = tool.validate_args(args)
            if not is_valid:
                result = f"错误: 参数校验失败: {error_msg}"
            else:
                try:
                    if run_context:
                        await run_context.check_cancelled()
                    execute_async_signature = inspect.signature(tool.execute_async)
                    if "run_context" in execute_async_signature.parameters:
                        tool_coro = tool.execute_async(run_context=run_context, **args)
                    else:
                        tool_coro = tool.execute_async(**args)
                    tool_task = asyncio.create_task(tool_coro)
                    cancel_task = (
                        asyncio.create_task(self._wait_for_cancel(run_context))
                        if run_context
                        else None
                    )
                    wait_set = {tool_task}
                    if cancel_task:
                        wait_set.add(cancel_task)
                    try:
                        done, _ = await asyncio.wait(
                            wait_set,
                            timeout=self._timeout_seconds,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if tool_task in done:
                            result = tool_task.result()
                        elif cancel_task and cancel_task in done:
                            tool_task.cancel()
                            await cancel_task
                        else:
                            tool_task.cancel()
                            raise TimeoutError
                    finally:
                        if cancel_task:
                            cancel_task.cancel()
                    error_prefixes = ("错误:", "工具执行错误:", "知识库检索错误")
                    success = not result.startswith(error_prefixes)
                except TimeoutError:
                    result = (
                        f"工具执行错误: 工具 '{tool_name}' 超过 "
                        f"{self._timeout_seconds:g} 秒未完成"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = f"工具执行错误: {exc}"
                finally:
                    if tool_task and not tool_task.done():
                        tool_task.cancel()
                    if cancel_task and not cancel_task.done():
                        cancel_task.cancel()

        duration_ms = (time.perf_counter() - started) * 1000
        if self._observability:
            self._observability.record_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=result,
                duration_ms=duration_ms,
                success=success,
                session_id=session_id,
                trace_id=trace_id,
                step=step,
            )
        return result

    async def _wait_for_cancel(self, run_context: Any) -> None:
        while True:
            await run_context.check_cancelled()
            await asyncio.sleep(0.1)

    def generate_tool_prompt(self) -> str:
        if not self._tools:
            return ""
        import json

        definitions = json.dumps(
            self.definitions(), ensure_ascii=False, indent=2
        )
        return f"【可用工具 JSON Schema】\n{definitions}"
