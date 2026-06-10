"""
Foundry IQ knowledge retrieval wrapper.
In live mode: queries an Azure AI Search index backed by learning_content.json.
In demo mode: performs local keyword search over the JSON file.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"


class FoundryIQKnowledgeRetrieval:
    """
    Wraps Azure AI Search (Foundry IQ knowledge base) for grounded, cited retrieval.

    Each returned chunk includes:
    - document_id: source document identifier
    - title: section title
    - content: relevant excerpt
    - citation: formatted citation string (document + section)
    - relevance_score: float 0–1
    """

    def __init__(self, demo_mode: bool = True):
        self._demo_mode = demo_mode
        self._knowledge_base: list[dict] = self._load_local_kb()
        if not demo_mode:
            self._init_azure_search()

    def _load_local_kb(self) -> list[dict]:
        kb_path = DATA_DIR / "learning_content.json"
        with open(kb_path) as f:
            return json.load(f)

    def _init_azure_search(self) -> None:
        """Initialize Azure AI Search client for live Foundry IQ queries."""
        try:
            from azure.search.documents import SearchClient
            from azure.core.credentials import AzureKeyCredential

            endpoint = os.getenv("AZURE_SEARCH_ENDPOINT", "")
            key = os.getenv("AZURE_SEARCH_KEY", "")
            index = os.getenv("AZURE_SEARCH_INDEX", "learning-content")
            if endpoint and key:
                self._search_client = SearchClient(
                    endpoint=endpoint,
                    index_name=index,
                    credential=AzureKeyCredential(key),
                )
        except ImportError:
            pass

    def retrieve(
        self,
        query: str,
        certification_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Retrieve top-k relevant knowledge chunks for the given query.

        Args:
            query: Natural language search query
            certification_id: Filter to a specific certification (optional)
            top_k: Maximum number of results to return

        Returns:
            List of result dicts with citation metadata
        """
        if self._demo_mode:
            return self._local_search(query, certification_id, top_k)
        return self._azure_search(query, certification_id, top_k)

    def _local_search(
        self,
        query: str,
        certification_id: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Keyword-based local search against the JSON knowledge base."""
        query_tokens = set(re.split(r"\W+", query.lower()))

        scored: list[tuple[float, dict]] = []
        for item in self._knowledge_base:
            if certification_id and item.get("certification_id") != certification_id:
                continue

            searchable = " ".join([
                item.get("title", ""),
                item.get("summary", ""),
                " ".join(item.get("topics", [])),
            ]).lower()

            item_tokens = set(re.split(r"\W+", searchable))
            overlap = len(query_tokens & item_tokens)
            if overlap == 0:
                continue

            score = overlap / max(len(query_tokens), 1)
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, item in scored[:top_k]:
            results.append({
                "document_id": item["id"],
                "certification_id": item["certification_id"],
                "title": item["title"],
                "content": item["summary"],
                "content_type": item["content_type"],
                "url": item["url"],
                "estimated_minutes": item["estimated_minutes"],
                "topics": item.get("topics", []),
                "difficulty": item.get("difficulty", "intermediate"),
                "relevance_score": round(score, 3),
                "citation": (
                    f"[Source: learning_content.json › {item['id']} — "
                    f"\"{item['title']}\"]"
                ),
            })
        return results

    def _azure_search(
        self,
        query: str,
        certification_id: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Live Azure AI Search (semantic + vector hybrid)."""
        try:
            filter_expr = None
            if certification_id:
                filter_expr = f"certification_id eq '{certification_id}'"

            results_raw = self._search_client.search(
                search_text=query,
                query_type="semantic",
                semantic_configuration_name="default",
                filter=filter_expr,
                top=top_k,
                include_total_count=True,
            )

            results = []
            for r in results_raw:
                score = r.get("@search.reranker_score", 0) / 4.0
                results.append({
                    "document_id": r.get("id"),
                    "certification_id": r.get("certification_id"),
                    "title": r.get("title"),
                    "content": r.get("summary"),
                    "content_type": r.get("content_type"),
                    "url": r.get("url"),
                    "estimated_minutes": r.get("estimated_minutes"),
                    "topics": r.get("topics", []),
                    "difficulty": r.get("difficulty", "intermediate"),
                    "relevance_score": round(score, 3),
                    "citation": (
                        f"[Source: Foundry IQ Knowledge Base › {r.get('id')} — "
                        f"\"{r.get('title')}\"]"
                    ),
                })
            return results
        except Exception as exc:
            return self._local_search(query, certification_id, top_k)

    def get_by_certification(self, certification_id: str) -> list[dict]:
        """Return all knowledge items for a specific certification."""
        return [
            item for item in self._knowledge_base
            if item.get("certification_id") == certification_id
        ]
