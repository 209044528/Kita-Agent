"""Standalone MCP entry point (stdio by default)."""

import argparse

from app.core.container import get_tool_registry
from app.infrastructure.mcp import create_mcp_server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
    )
    args = parser.parse_args()
    server = create_mcp_server(get_tool_registry())
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
