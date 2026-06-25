from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel, Field


class RAGEvaluationCase(BaseModel):
    query: str
    expected_keywords: list[str] = Field(min_length=1)
    tag: str | None = None


class RAGEvaluationReport(BaseModel):
    total: int
    hits: int
    hit_rate: float
    cases: list[dict]


def evaluate_rag(
    cases: Iterable[RAGEvaluationCase],
    retrieve: Callable[[str, str | None], str],
) -> RAGEvaluationReport:
    details = []
    hits = 0
    for case in cases:
        result = retrieve(case.query, case.tag)
        matched = [
            keyword for keyword in case.expected_keywords if keyword.lower() in result.lower()
        ]
        hit = bool(matched)
        hits += int(hit)
        details.append(
            {
                "query": case.query,
                "tag": case.tag,
                "hit": hit,
                "matched_keywords": matched,
            }
        )
    total = len(details)
    return RAGEvaluationReport(
        total=total,
        hits=hits,
        hit_rate=round(hits / total, 4) if total else 0.0,
        cases=details,
    )
