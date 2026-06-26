from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.security import RequestIdentity
from app.infrastructure.platform_store import PlatformStore


@dataclass
class IntentMatch:
    node_id: str
    name: str
    kind: str
    score: float
    node: dict[str, Any]


@dataclass
class IntentRoute:
    rewritten_query: str
    matches: list[IntentMatch] = field(default_factory=list)
    knowledge_tag: str | None = None
    knowledge_dir: str | None = None
    top_k: int | None = None
    system_prompt_suffix: str = ""
    mcp_tools: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_route(self) -> bool:
        return bool(
            self.matches
            or self.knowledge_tag
            or self.knowledge_dir
            or self.system_prompt_suffix
            or self.mcp_tools
        )

    def to_prompt_block(self) -> str:
        if not self.has_route:
            return ""
        lines = ["【意图路由】"]
        if self.matches:
            lines.append(
                "命中意图: "
                + ", ".join(
                    f"{match.name}({match.kind}, score={match.score:.2f})"
                    for match in self.matches
                )
            )
        if self.knowledge_tag or self.knowledge_dir:
            lines.append(
                f"优先检索知识库: tag={self.knowledge_tag or '未指定'}, "
                f"dir={self.knowledge_dir or '未指定'}"
            )
        if self.mcp_tools:
            lines.append("可用 MCP 工具路由:")
            for tool in self.mcp_tools:
                lines.append(
                    f"- server={tool.get('server_name')}, tool={tool.get('tool_name')}"
                )
            lines.append(
                "如需调用 MCP，请使用 mcp_call 工具，并传入 server_name、tool_name、arguments。"
            )
        if self.system_prompt_suffix:
            lines.append("意图附加指令:")
            lines.append(self.system_prompt_suffix)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rewritten_query": self.rewritten_query,
            "knowledge_tag": self.knowledge_tag,
            "knowledge_dir": self.knowledge_dir,
            "top_k": self.top_k,
            "mcp_tools": self.mcp_tools,
            "matches": [
                {
                    "node_id": match.node_id,
                    "name": match.name,
                    "kind": match.kind,
                    "score": match.score,
                }
                for match in self.matches
            ],
        }


class IntentTreeService:
    """Intent tree and routing service.

    This first implementation is deterministic and explainable. It intentionally
    avoids a hard dependency on an LLM classifier while leaving the route object
    rich enough for a future model-based classifier.
    """

    def __init__(self, store: PlatformStore, *, threshold: float = 0.35, max_matches: int = 3):
        self.store = store
        self.threshold = threshold
        self.max_matches = max_matches

    def upsert_node(self, node: dict[str, Any], identity: RequestIdentity) -> str:
        kind = str(node.get("kind", "KB")).upper()
        if kind not in {"KB", "MCP", "SYSTEM"}:
            raise ValueError("intent kind must be KB, MCP, or SYSTEM")
        node["kind"] = kind
        return self.store.upsert_intent_node(node, created_by=identity.user_id)

    def list_nodes(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        return self.store.list_intent_nodes(include_disabled=include_disabled)

    def delete_node(self, node_id: str) -> bool:
        return self.store.delete_intent_node(node_id)

    def upsert_query_mapping(
        self,
        *,
        source_term: str,
        target_term: str,
        identity: RequestIdentity,
        mapping_id: str | None = None,
        enabled: bool = True,
    ) -> str:
        return self.store.upsert_query_term_mapping(
            source_term=source_term,
            target_term=target_term,
            created_by=identity.user_id,
            mapping_id=mapping_id,
            enabled=enabled,
        )

    def list_query_mappings(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        return self.store.list_query_term_mappings(include_disabled=include_disabled)

    def rewrite_query(self, query: str) -> str:
        rewritten = query
        for mapping in self.store.list_query_term_mappings(include_disabled=False):
            source = mapping.get("source_term") or ""
            target = mapping.get("target_term") or ""
            if not source or not target:
                continue
            if source.lower() in rewritten.lower() and target.lower() not in rewritten.lower():
                rewritten = f"{rewritten} {target}"
        return rewritten

    def classify(
        self,
        query: str,
        *,
        include_disabled: bool = False,
    ) -> list[IntentMatch]:
        rewritten = self.rewrite_query(query)
        query_tokens = self._tokens(rewritten)
        query_lower = rewritten.lower()
        matches: list[IntentMatch] = []
        for node in self.store.list_intent_nodes(include_disabled=include_disabled):
            score = self._score_node(node, query_lower=query_lower, query_tokens=query_tokens)
            if score >= self.threshold:
                matches.append(
                    IntentMatch(
                        node_id=node["node_id"],
                        name=node["name"],
                        kind=node["kind"],
                        score=round(score, 4),
                        node=node,
                    )
                )

        matches.sort(
            key=lambda match: (match.score, int(match.node.get("priority") or 0)),
            reverse=True,
        )
        return matches[: self.max_matches]

    def route(self, query: str, identity: RequestIdentity | None = None) -> IntentRoute:
        rewritten = self.rewrite_query(query)
        matches = self.classify(rewritten)
        route = IntentRoute(rewritten_query=rewritten, matches=matches)
        system_prompts: list[str] = []

        for match in matches:
            node = match.node
            kind = match.kind
            if kind == "KB":
                route.knowledge_tag = route.knowledge_tag or node.get("knowledge_tag")
                route.knowledge_dir = route.knowledge_dir or node.get("knowledge_dir")
                route.top_k = route.top_k or node.get("top_k")
            elif kind == "MCP":
                if node.get("mcp_server") and node.get("mcp_tool"):
                    route.mcp_tools.append(
                        {
                            "server_name": node.get("mcp_server"),
                            "tool_name": node.get("mcp_tool"),
                            "intent_node_id": node.get("node_id"),
                            "intent_name": node.get("name"),
                        }
                    )
            elif kind == "SYSTEM" and node.get("prompt_template"):
                system_prompts.append(str(node["prompt_template"]))

        route.system_prompt_suffix = "\n".join(system_prompts)
        return route

    def _score_node(
        self,
        node: dict[str, Any],
        *,
        query_lower: str,
        query_tokens: set[str],
    ) -> float:
        score = 0.0
        keywords = [str(keyword).strip().lower() for keyword in node.get("keywords", [])]
        keywords = [keyword for keyword in keywords if keyword]
        if keywords:
            hits = sum(1 for keyword in keywords if keyword in query_lower)
            score += hits / max(len(keywords), 1)

        name = str(node.get("name") or "").lower()
        if name and name in query_lower:
            score += 0.5

        description_tokens = self._tokens(str(node.get("description") or ""))
        if description_tokens:
            overlap = len(query_tokens & description_tokens)
            score += min(overlap / max(len(description_tokens), 1), 0.5)

        priority_bonus = min(max(int(node.get("priority") or 0), 0), 100) / 1000
        return min(score + priority_bonus, 1.0)

    def _tokens(self, text: str) -> set[str]:
        return {
            token.lower()
            for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", text)
            if token.strip()
        }
