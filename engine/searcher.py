"""Xử lý truy vấn và truy hồi theo BM25F."""

from __future__ import annotations

import html
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from whoosh import index, scoring, sorting
from whoosh.qparser import MultifieldParser, OrGroup, QueryParser

from .schema import fold_vietnamese


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    description: str
    category: str
    published_at: str
    comment_count: int
    image_url: str
    score: float


@dataclass(frozen=True)
class SearchPage:
    results: list[SearchResult]
    total: int
    page: int
    page_size: int
    elapsed_ms: float

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.page_size))


WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _normalize(value: str) -> str:
    """Dạng so khớp chung: Unicode case-folded và không dấu."""
    return fold_vietnamese(value).casefold()


def _query_terms(query: str) -> tuple[set[str], set[str]]:
    surface = {match.group().casefold() for match in WORD_RE.finditer(query)}
    return {_normalize(term) for term in surface if len(term) > 1}, surface


def _matching_tokens(
    text: str, normalized_terms: set[str]
) -> list[tuple[int, int, str, str]]:
    """(start, end, normalized, surface) của các token khớp query."""
    return [
        (match.start(), match.end(), normalized, match.group().casefold())
        for match in WORD_RE.finditer(text)
        if (normalized := _normalize(match.group())) in normalized_terms
    ]


def _best_window(text: str, query: str, limit: int) -> tuple[int, int, set[str]]:
    """Sliding window tối đa query coverage trong giới hạn ký tự."""
    normalized_terms, surface_terms = _query_terms(query)
    matches = _matching_tokens(text, normalized_terms)
    if not matches:
        return 0, min(len(text), limit), normalized_terms

    left = 0
    counts: Counter[str] = Counter()
    exact_counts: Counter[str] = Counter()
    best_score: tuple[int, int, int, int, int] | None = None
    best_span = (matches[0][0], matches[0][1])

    for right, current in enumerate(matches):
        counts[current[2]] += 1
        if current[3] in surface_terms:
            exact_counts[current[2]] += 1

        while current[1] - matches[left][0] > limit:
            removed = matches[left]
            counts[removed[2]] -= 1
            if not counts[removed[2]]:
                del counts[removed[2]]
            if removed[3] in surface_terms:
                exact_counts[removed[2]] -= 1
                if not exact_counts[removed[2]]:
                    del exact_counts[removed[2]]
            left += 1

        # Bỏ các lần lặp ở đầu mà không làm giảm coverage để có cửa sổ gọn nhất.
        while left < right and counts[matches[left][2]] > 1:
            removed = matches[left]
            counts[removed[2]] -= 1
            if removed[3] in surface_terms:
                exact_counts[removed[2]] -= 1
                if not exact_counts[removed[2]]:
                    del exact_counts[removed[2]]
            left += 1
        span_start, span_end = matches[left][0], current[1]
        score = (
            len(counts),                 # Maximum Query Coverage
            len(exact_counts),           # ưu tiên đúng surface form khi hòa
            sum(counts.values()),        # mật độ term trong cửa sổ
            -(span_end - span_start),    # cửa sổ gọn hơn
            -span_start,                 # xuất hiện sớm hơn
        )
        if best_score is None or score > best_score:
            best_score = score
            best_span = (span_start, span_end)

    match_start, match_end = best_span
    match_length = match_end - match_start
    spare = max(0, limit - match_length)
    start = max(0, match_start - spare // 2)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    if start:
        boundary = text.find(" ", start, match_start + 1)
        if boundary >= 0:
            start = boundary + 1
    return start, end, normalized_terms


def _highlight(text: str, normalized_terms: set[str]) -> str:
    spans = [(start, end) for start, end, _, _ in _matching_tokens(text, normalized_terms)]
    if not spans:
        return html.escape(text)
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(html.escape(text[cursor:start]))
        parts.append(f"<mark>{html.escape(text[start:end])}</mark>")
        cursor = end
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def _snippet(text: str, query: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    start, end, normalized_terms = _best_window(clean, query, limit)
    value = clean[start:end]
    prefix = "…" if start else ""
    suffix = "…" if end < len(clean) else ""
    return prefix + _highlight(value, normalized_terms) + suffix


class SearchService:
    def __init__(self, index_dir: Path) -> None:
        if not index.exists_in(index_dir):
            raise FileNotFoundError(f"Chưa có Whoosh index tại {index_dir}")
        self.ix = index.open_dir(index_dir)

    def search(
        self,
        query_text: str,
        *,
        page: int = 1,
        page_size: int = 10,
        category: str = "",
        sort_by: str = "relevance",
    ) -> SearchPage:
        started = time.perf_counter()
        page = max(1, page)
        page_size = min(50, max(1, page_size))
        with self.ix.searcher(weighting=scoring.BM25F(B=0.75, K1=1.5)) as searcher:
            if query_text.strip():
                parser = MultifieldParser(
                    ["title", "description", "content"],
                    schema=self.ix.schema,
                    fieldboosts={"title": 3.0, "description": 1.8, "content": 1.0},
                    group=OrGroup.factory(0.85),
                )
                parsed = parser.parse(query_text)
                # Field folded giúp cùng một logic hoạt động với cả query có/không dấu.
                parsed |= QueryParser("folded", self.ix.schema).parse(
                    fold_vietnamese(query_text)
                )
            else:
                parsed = QueryParser("content", self.ix.schema).parse("*")
            if category:
                category_query = QueryParser("category", self.ix.schema).parse(category)
                parsed = parsed & category_query

            sortedby = None
            if sort_by == "comments":
                sortedby = sorting.FieldFacet("comment_count", reverse=True)
            hits = searcher.search(parsed, limit=None, sortedby=sortedby)
            total = len(hits)
            start = (page - 1) * page_size
            rows = hits[start : start + page_size]
            results = [
                SearchResult(
                    title=hit["title"],
                    url=hit["url"],
                    snippet=_snippet(
                        " ".join((hit.get("description", ""), hit.get("content", ""))),
                        query_text,
                    ),
                    description=hit.get("description", ""),
                    category=hit.get("category", ""),
                    published_at=hit.get("published_at", ""),
                    comment_count=hit.get("comment_count", 0),
                    image_url=hit.get("image_url", ""),
                    score=0.0 if sortedby is not None else float(hit.score or 0),
                )
                for hit in rows
            ]
        return SearchPage(
            results=results,
            total=total,
            page=page,
            page_size=page_size,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
