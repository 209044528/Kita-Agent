from __future__ import annotations

import inspect
from typing import Annotated, Any

from pydantic import Field
from app.domain.agent.tool import ToolParameter, ToolRegistry


_PYTHON_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _build_handler(registry: ToolRegistry, tool_name: str, parameters: list[ToolParameter]):
    def handler(**kwargs: Any) -> str:
        return registry.execute(tool_name, kwargs)

    signature_parameters = []
    annotations: dict[str, Any] = {"return": str}
    for parameter in parameters:
        base_type = _PYTHON_TYPES.get(parameter.type, Any)
        python_type = Annotated[
            base_type,
            Field(description=parameter.description),
        ]
        annotations[parameter.name] = python_type
        default = inspect.Parameter.empty if parameter.required else parameter.default
        signature_parameters.append(
            inspect.Parameter(
                parameter.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
                annotation=python_type,
            )
        )
    handler.__name__ = tool_name
    handler.__annotations__ = annotations
    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=signature_parameters,
        return_annotation=str,
    )
    return handler


def create_mcp_server(registry: ToolRegistry):
    """Adapt the existing ToolRegistry to the official MCP Python SDK."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "MCP support requires `mcp==1.12.4`; install requirements-mcp.txt."
        ) from exc

    server = FastMCP(
        "Kita-Agent",
        instructions="Kita-Agent knowledge, code, and vision tool server.",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )
    for tool in registry.list_tools():
        server.add_tool(
            _build_handler(registry, tool.name, tool.parameters),
            name=tool.name,
            description=tool.description,
            structured_output=False,
        )
    return server
