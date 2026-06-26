from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, Field


class RAGEvaluationCase(BaseModel):
    query: str
    expected_keywords: list[str] = Field(min_length=1)
    tag: str | None = None
    must_not_contain: list[str] = Field(default_factory=list)


class RAGEvaluationReport(BaseModel):
    total: int
    hits: int
    hit_rate: float
    keyword_recall: float = 0.0
    mrr: float = 0.0
    average_latency_ms: float = 0.0
    cases: list[dict[str, Any]]


def evaluate_rag(
    cases: Iterable[RAGEvaluationCase],
    retrieve: Callable[[str, str | None], str],
) -> RAGEvaluationReport:
    details = []
    hits = 0
    matched_keywords_total = 0
    expected_keywords_total = 0
    reciprocal_ranks = []
    latencies = []

    for case in cases:
        started = time.perf_counter()
        result = retrieve(case.query, case.tag)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)

        lower_result = result.lower()
        matched = [
            keyword
            for keyword in case.expected_keywords
            if keyword.lower() in lower_result
        ]
        forbidden = [
            keyword
            for keyword in case.must_not_contain
            if keyword.lower() in lower_result
        ]
        hit = bool(matched) and not forbidden
        hits += int(hit)
        matched_keywords_total += len(matched)
        expected_keywords_total += len(case.expected_keywords)
        reciprocal_ranks.append(_reciprocal_rank(result, matched))
        details.append(
            {
                "query": case.query,
                "tag": case.tag,
                "hit": hit,
                "matched_keywords": matched,
                "forbidden_keywords": forbidden,
                "latency_ms": round(latency_ms, 3),
                "result_preview": result[:500],
            }
        )

    total = len(details)
    return RAGEvaluationReport(
        total=total,
        hits=hits,
        hit_rate=round(hits / total, 4) if total else 0.0,
        keyword_recall=(
            round(matched_keywords_total / expected_keywords_total, 4)
            if expected_keywords_total
            else 0.0
        ),
        mrr=round(sum(reciprocal_ranks) / total, 4) if total else 0.0,
        average_latency_ms=round(sum(latencies) / total, 3) if total else 0.0,
        cases=details,
    )


def _reciprocal_rank(result: str, matched_keywords: list[str]) -> float:
    if not matched_keywords:
        return 0.0
    best_position = None
    lower_result = result.lower()
    for keyword in matched_keywords:
        pos = lower_result.find(keyword.lower())
        if pos >= 0:
            best_position = pos if best_position is None else min(best_position, pos)
    if best_position is None:
        return 0.0
    # Approximate rank by cited chunk separator/number before the first match.
    prefix = result[:best_position]
    rank = max(prefix.count("\n---\n") + 1, 1)
    return 1.0 / rank
