"""Independent lexical/dense retrieval merged using reciprocal rank fusion."""

from __future__ import annotations

import time
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .image_searcher import ImagePage, ImageResult, ImageSearchService
from .searcher import SearchPage, SearchResult, SearchService, _snippet
from .vector_index import DEFAULT_MODEL_DIR, VectorIndex

CANDIDATE_LIMIT = 50
RRF_K = 60


def reciprocal_rank_fusion(*rankings: list[str], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen = set()
        for rank, record_id in enumerate(ranking, start=1):
            if record_id in seen:
                continue
            seen.add(record_id)
            scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class HybridSearchService:
    def __init__(self, index_dir: Path, vector_dir: Path, *, encoder=None, model_dir: Path = DEFAULT_MODEL_DIR) -> None:
        self.lexical = SearchService(index_dir)
        self.dense = VectorIndex(vector_dir, "articles", encoder=encoder, model_dir=model_dir)
        self._ranked = lru_cache(maxsize=128)(self._rank_candidates)

    def _rank_candidates(self, query_text: str, category: str) -> tuple[SearchResult, ...]:
        lexical = self.lexical.search(query_text, page_size=CANDIDATE_LIMIT, category=category)
        dense = self.dense.search(query_text, limit=CANDIDATE_LIMIT, category=category)
        by_id = {result.doc_id: result for result in lexical.results}
        passages = {record_id: text for record_id, _, text in dense}
        ranking = reciprocal_rank_fusion(list(by_id), [record_id for record_id, _, _ in dense])
        rows = []
        with self.lexical.ix.searcher() as searcher:
            for record_id, score in ranking:
                result = by_id.get(record_id)
                if result is None:
                    doc = searcher.document(doc_id=record_id)
                    if doc is None:
                        continue
                    result = SearchResult(
                        title=doc["title"], url=doc["url"],
                        snippet=_snippet(passages[record_id], query_text),
                        description=doc.get("description", ""), category=doc.get("category", ""),
                        published_at=doc.get("published_at", ""), comment_count=doc.get("comment_count", 0),
                        image_url=doc.get("image_url", ""), score=score, doc_id=record_id,
                    )
                rows.append(replace(result, score=score))
        return tuple(rows)

    def search(self, query_text: str, *, page: int = 1, page_size: int = 10,
               category: str = "", sort_by: str = "relevance") -> SearchPage:
        if not query_text.strip():
            return self.lexical.search(query_text, page=page, page_size=page_size, category=category, sort_by=sort_by)
        started = time.perf_counter()
        page, page_size = max(1, page), min(50, max(1, page_size))
        rows = self._ranked(query_text.strip(), category)
        if sort_by == "comments":
            rows = sorted(rows, key=lambda result: (-result.comment_count, -result.score, result.doc_id))
        start = (page - 1) * page_size
        return SearchPage(list(rows[start:start + page_size]), len(rows), page, page_size,
                          (time.perf_counter() - started) * 1000)


class HybridImageSearchService:
    def __init__(self, index_dir: Path, vector_dir: Path, *, encoder=None, model_dir: Path = DEFAULT_MODEL_DIR) -> None:
        self.lexical = ImageSearchService(index_dir)
        self.dense = VectorIndex(vector_dir, "images", encoder=encoder, model_dir=model_dir)
        self._ranked = lru_cache(maxsize=128)(self._rank_candidates)

    def _rank_candidates(self, query: str, category: str) -> tuple[ImageResult, ...]:
        lexical = self.lexical.search(query, page_size=CANDIDATE_LIMIT, category=category)
        dense = self.dense.search(query, limit=CANDIDATE_LIMIT, category=category)
        by_id = {result.image_id: result for result in lexical.results}
        ranking = reciprocal_rank_fusion(list(by_id), [record_id for record_id, _, _ in dense])
        rows = []
        seen_assets = set()
        with self.lexical.ix.searcher() as searcher:
            for record_id, score in ranking:
                doc = searcher.document(image_id=record_id)
                if doc is None:
                    continue
                identity = doc.get("canonical_image_url") or doc["image_url"]
                if identity in seen_assets:
                    continue
                seen_assets.add(identity)
                result = by_id.get(record_id)
                if result is None:
                    description = next((doc.get(field) for field in ("caption", "alt_text", "image_title", "nearby_text") if doc.get(field)), "")
                    result = ImageResult(record_id, doc["image_url"], doc["source_url"], doc.get("source_title", ""), description, score)
                rows.append(replace(result, score=score))
        return tuple(rows)

    def search(self, query: str, *, page: int = 1, page_size: int = 6, category: str = "") -> ImagePage:
        started = time.perf_counter()
        page, page_size = max(1, page), min(50, max(1, page_size))
        if not query.strip():
            return ImagePage([], 0, page, page_size, 0.0)
        rows = self._ranked(query.strip(), category)
        start = (page - 1) * page_size
        return ImagePage(list(rows[start:start + page_size]), len(rows), page, page_size,
                         (time.perf_counter() - started) * 1000)
