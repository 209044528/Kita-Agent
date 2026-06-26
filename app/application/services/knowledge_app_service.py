from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List

import httpx
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from app.core.config import settings
from app.domain.knowledge.repository import (
    DocumentEntity,
    IKnowledgeRepository,
    RetrievedChunk,
)
from app.infrastructure.parser.git_parser import GitRepositoryParser


class KnowledgeAppService:
    def __init__(
        self,
        knowledge_repo: IKnowledgeRepository,
        use_model_reranker: bool = False,
        git_parser: GitRepositoryParser | None = None,
    ):
        self.knowledge_repo = knowledge_repo
        self.use_model_reranker = use_model_reranker
        self.git_parser = git_parser or GitRepositoryParser()
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
            ]
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        )

    def process_and_store_text(
        self,
        raw_text: str,
        tag: str,
        source_name: str,
        *,
        user_id: str = "anonymous",
        visibility: str = "public",
        allowed_user_ids: list[str] | None = None,
        knowledge_dir: str | None = None,
    ) -> None:
        """Split text into chunks and persist them with ownership/provenance metadata."""
        chunks = self._split_text(raw_text)
        documents = []
        allowed_user_ids = allowed_user_ids or []

        for index, (chunk_content, header_meta) in enumerate(chunks):
            chunk_hash = hashlib.md5(
                f"{tag}:{source_name}:{index}:{chunk_content}".encode("utf-8")
            ).hexdigest()
            metadata = {
                "knowledge_tag": tag,
                "source": source_name,
                "chunk_hash": chunk_hash,
                "chunk_index": index,
                "owner_user_id": user_id,
                "visibility": visibility,
                "allowed_user_ids": allowed_user_ids,
                "knowledge_dir": knowledge_dir or "",
                **header_meta,
            }
            documents.append(
                DocumentEntity(content=chunk_content, metadata=metadata, id=chunk_hash)
            )

        if documents:
            self.knowledge_repo.add_documents(documents)

    def retrieve_knowledge(
        self,
        user_query: str,
        tag: str | None = None,
        initial_top_k: int = 15,
        final_top_k: int = 3,
        *,
        user_id: str = "anonymous",
        is_admin: bool = False,
        knowledge_dir: str | None = None,
        include_citations: bool = True,
        channels: list[str] | None = None,
    ) -> str:
        """Backward-compatible text context retrieval."""
        chunks = self.retrieve_chunks(
            user_query=user_query,
            tag=tag,
            initial_top_k=initial_top_k,
            final_top_k=final_top_k,
            user_id=user_id,
            is_admin=is_admin,
            knowledge_dir=knowledge_dir,
            channels=channels,
        )
        return self.format_retrieved_chunks(chunks, include_citations=include_citations)

    def retrieve_chunks(
        self,
        user_query: str,
        tag: str | None = None,
        initial_top_k: int = 15,
        final_top_k: int = 3,
        *,
        user_id: str = "anonymous",
        is_admin: bool = False,
        knowledge_dir: str | None = None,
        channels: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Multi-channel RAG pipeline with structured chunks and provenance."""
        if not user_query or not user_query.strip():
            return []

        channels = channels or ["vector", "keyword"]
        filters = self._metadata_filter(tag=tag, knowledge_dir=knowledge_dir)
        query_plan = self._rewrite_and_split_query(user_query)
        candidates: dict[str, RetrievedChunk] = {}
        fetch_k = max(initial_top_k, final_top_k * 4)

        for query in query_plan:
            if "vector" in channels:
                try:
                    for doc, raw_score in self.knowledge_repo.similarity_search_with_score(
                        query=query,
                        top_k=fetch_k,
                        filter_kwargs=filters,
                    ):
                        self._merge_candidate(
                            candidates, doc, channel="vector", raw_score=float(raw_score)
                        )
                except Exception as exc:
                    logger.warning("Vector retrieval failed for query={!r}: {}", query, exc)

            if "keyword" in channels:
                try:
                    for doc, raw_score in self.knowledge_repo.keyword_search(
                        query=query,
                        top_k=fetch_k,
                        filter_kwargs=filters,
                    ):
                        self._merge_candidate(
                            candidates, doc, channel="keyword", raw_score=float(raw_score)
                        )
                except Exception as exc:
                    logger.warning("Keyword retrieval failed for query={!r}: {}", query, exc)

        visible = [
            chunk
            for chunk in candidates.values()
            if self._passes_access_filter(
                chunk.metadata,
                user_id=user_id,
                is_admin=is_admin,
                knowledge_dir=knowledge_dir,
            )
        ]
        if not visible:
            return []

        self._normalize_and_score(visible)
        visible.sort(key=lambda chunk: chunk.score, reverse=True)
        rerank_pool = visible[: max(initial_top_k, final_top_k)]
        if self.use_model_reranker:
            rerank_pool = self._rerank_chunks_with_model(user_query, rerank_pool)

        rerank_pool.sort(key=lambda chunk: chunk.score, reverse=True)
        final_chunks = rerank_pool[:final_top_k]
        for index, chunk in enumerate(final_chunks, start=1):
            chunk.provenance["citation_index"] = index
        return final_chunks

    def format_retrieved_chunks(
        self, chunks: list[RetrievedChunk], *, include_citations: bool = True
    ) -> str:
        if not chunks:
            return ""
        parts = []
        for index, chunk in enumerate(chunks, start=1):
            citation = f"[{index}] " if include_citations else ""
            source_bits = [
                f"source={chunk.source or 'unknown'}",
                f"tag={chunk.tag or 'N/A'}",
                f"dir={chunk.knowledge_dir or '/'}",
                f"score={chunk.score:.3f}",
                f"channels={','.join(chunk.channels)}",
            ]
            parts.append(
                f"{citation}{chunk.content}\n"
                f"来源: {' | '.join(source_bits)} | chunk_id={chunk.id}"
            )
        return "\n---\n".join(parts)

    def delete_knowledge_by_tag(self, tag: str) -> int:
        return self.knowledge_repo.delete_by_tag(tag)

    def ingest_git_repo(
        self,
        repo_url: str,
        branch: str = "main",
        knowledge_tag: str | None = None,
        *,
        user_id: str = "anonymous",
        visibility: str = "public",
        allowed_user_ids: list[str] | None = None,
        knowledge_dir: str | None = None,
    ) -> None:
        if not knowledge_tag:
            clean_url = repo_url.rstrip("/").replace(".git", "")
            if "github.com" in clean_url and ("/tree/" in clean_url or "/blob/" in clean_url):
                clean_url = clean_url.split("/tree/")[0].split("/blob/")[0]
            knowledge_tag = clean_url.split("/")[-1]

        documents = self.git_parser.parse_repo(repo_url, branch)
        allowed_user_ids = allowed_user_ids or []
        for index, doc in enumerate(documents):
            chunk_hash = doc.id or hashlib.md5(
                f"{knowledge_tag}:{repo_url}:{index}:{doc.content}".encode("utf-8")
            ).hexdigest()
            doc.id = chunk_hash
            doc.metadata.update(
                {
                    "knowledge_tag": knowledge_tag,
                    "source": doc.metadata.get("source") or repo_url,
                    "chunk_hash": chunk_hash,
                    "chunk_index": doc.metadata.get("chunk", index),
                    "owner_user_id": user_id,
                    "visibility": visibility,
                    "allowed_user_ids": allowed_user_ids,
                    "knowledge_dir": knowledge_dir or "",
                }
            )

        if documents:
            self.knowledge_repo.add_documents(documents)
            logger.info("Git repo ingested: repo={} tag={}", repo_url, knowledge_tag)

    def _split_text(self, raw_text: str) -> list[tuple[str, dict]]:
        try:
            md_chunks = self.markdown_splitter.split_text(raw_text)
            chunks: list[tuple[str, dict]] = []
            for md_doc in md_chunks:
                header_metadata = getattr(md_doc, "metadata", {}) or {}
                content = getattr(md_doc, "page_content", md_doc)
                for sub_chunk in self.text_splitter.split_text(str(content)):
                    chunks.append((sub_chunk, dict(header_metadata)))
            return chunks
        except Exception as exc:
            logger.warning("Markdown splitting failed, falling back: {}", exc)
            return [(chunk, {}) for chunk in self.text_splitter.split_text(raw_text)]

    def _metadata_filter(
        self, *, tag: str | None = None, knowledge_dir: str | None = None
    ) -> dict | None:
        filters = {}
        if tag:
            filters["knowledge_tag"] = tag
        if knowledge_dir:
            filters["knowledge_dir"] = knowledge_dir
        return filters or None

    def _rewrite_and_split_query(self, query: str) -> list[str]:
        cleaned = " ".join(query.strip().split())
        variants = [cleaned]
        segments = re.split(r"[?？!！。\n；;]|以及|并且|还有|和|与|,|，", cleaned)
        variants.extend(segment.strip() for segment in segments if len(segment.strip()) >= 2)

        tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", cleaned)
        if 2 <= len(tokens) <= 12:
            variants.append(" ".join(tokens))
        elif len(tokens) > 12:
            variants.append(" ".join(tokens[:12]))

        deduped = []
        seen = set()
        for variant in variants:
            key = variant.lower()
            if variant and key not in seen:
                seen.add(key)
                deduped.append(variant)
        return deduped[:6]

    def _merge_candidate(
        self,
        candidates: dict[str, RetrievedChunk],
        doc: DocumentEntity,
        *,
        channel: str,
        raw_score: float,
    ) -> None:
        metadata = doc.metadata or {}
        chunk_id = (
            doc.id
            or metadata.get("chunk_hash")
            or hashlib.md5(doc.content.encode("utf-8")).hexdigest()
        )
        chunk = candidates.get(chunk_id)
        if not chunk:
            chunk = RetrievedChunk(
                id=chunk_id,
                content=doc.content,
                metadata=metadata,
                source=str(metadata.get("source") or ""),
                tag=metadata.get("knowledge_tag"),
                knowledge_dir=metadata.get("knowledge_dir") or None,
                channels=[],
                provenance={
                    "chunk_hash": metadata.get("chunk_hash", chunk_id),
                    "chunk_index": metadata.get("chunk_index"),
                    "headers": {
                        key: value
                        for key, value in metadata.items()
                        if key.lower().startswith("header")
                    },
                },
            )
            candidates[chunk_id] = chunk

        if channel not in chunk.channels:
            chunk.channels.append(channel)
        if channel == "vector":
            chunk.vector_score = (
                raw_score
                if chunk.vector_score is None
                else min(chunk.vector_score, raw_score)
            )
        elif channel == "keyword":
            chunk.keyword_score = (
                raw_score
                if chunk.keyword_score is None
                else max(chunk.keyword_score, raw_score)
            )

    def _passes_access_filter(
        self,
        metadata: dict,
        *,
        user_id: str,
        is_admin: bool,
        knowledge_dir: str | None,
    ) -> bool:
        if knowledge_dir and (metadata.get("knowledge_dir") or "") != knowledge_dir:
            return False
        if is_admin:
            return True

        visibility = metadata.get("visibility") or "public"
        if visibility == "public":
            return True
        owner_user_id = metadata.get("owner_user_id")
        if owner_user_id and owner_user_id == user_id:
            return True
        allowed = metadata.get("allowed_user_ids") or []
        if isinstance(allowed, str):
            allowed = [item.strip() for item in allowed.split(",") if item.strip()]
        return user_id in allowed

    def _normalize_and_score(self, chunks: list[RetrievedChunk]) -> None:
        vector_values = [
            1.0 / (1.0 + max(chunk.vector_score or 0.0, 0.0))
            for chunk in chunks
            if chunk.vector_score is not None
        ]
        keyword_values = [
            chunk.keyword_score for chunk in chunks if chunk.keyword_score is not None
        ]
        vector_norm = self._minmax(vector_values)
        keyword_norm = self._minmax(keyword_values)
        vector_index = 0
        keyword_index = 0

        for chunk in chunks:
            v = None
            k = None
            if chunk.vector_score is not None:
                v = vector_norm[vector_index]
                chunk.vector_score = v
                vector_index += 1
            if chunk.keyword_score is not None:
                k = keyword_norm[keyword_index]
                chunk.keyword_score = k
                keyword_index += 1
            if v is not None and k is not None:
                chunk.score = 0.65 * v + 0.35 * k
            elif v is not None:
                chunk.score = v
            elif k is not None:
                chunk.score = k

    def _minmax(self, values: Iterable[float | None]) -> list[float]:
        clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        if not clean:
            return []
        low = min(clean)
        high = max(clean)
        if high == low:
            return [1.0 for _ in clean]
        return [(value - low) / (high - low) for value in clean]

    def _rerank_chunks_with_model(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        try:
            payload = {
                "query": query,
                "documents": [chunk.content for chunk in chunks],
                "return_documents": False,
            }
            with httpx.Client(timeout=30.0) as client:
                response = client.post(settings.RERANKER_API_URL, json=payload)
                response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return chunks

            raw_scores = [0.0 for _ in chunks]
            for position, item in enumerate(results):
                index = item.get("index", position)
                if 0 <= index < len(chunks):
                    raw_scores[index] = float(
                        item.get("score", item.get("relevance_score", 0.0))
                    )
            normalized = self._minmax(raw_scores)
            for chunk, rerank_score in zip(chunks, normalized):
                chunk.rerank_score = rerank_score
                chunk.score = 0.55 * rerank_score + 0.45 * chunk.score
        except Exception as exc:
            logger.warning(
                "Reranker unavailable at {}, using fused retrieval scores: {}",
                settings.RERANKER_API_URL,
                exc,
            )
        return chunks
