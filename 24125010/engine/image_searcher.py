"""Independent BM25 image search over descriptions and local context."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

from whoosh import index, scoring
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh.query import DisjunctionMax

from .schema import fold_vietnamese


@dataclass(frozen=True)
class ImageResult:
    image_id: str
    image_url: str
    source_url: str
    source_title: str
    description: str
    score: float


@dataclass(frozen=True)
class ImagePage:
    results: list[ImageResult]
    total: int
    page: int
    page_size: int
    elapsed_ms: float

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.page_size))


FIELDS = ("caption", "alt_text", "image_title", "nearby_text")
BOOSTS = {"caption": 4.0, "alt_text": 3.0, "image_title": 2.0, "nearby_text": 1.0}


class ImageSearchService:
    def __init__(self, index_dir: Path) -> None:
        if not index.exists_in(index_dir):
            raise FileNotFoundError(index_dir)
        self.ix = index.open_dir(index_dir)

    def search(self, query: str, *, page: int = 1, page_size: int = 6, category: str = "") -> ImagePage:
        started = time.perf_counter()
        page, page_size = max(1, page), min(50, max(1, page_size))
        if not query.strip():
            return ImagePage([], 0, page, page_size, 0.0)
        parser = MultifieldParser(list(FIELDS), self.ix.schema, fieldboosts=BOOSTS, group=OrGroup.factory(0.85))
        folded_parser = MultifieldParser([f"{f}_folded" for f in FIELDS], self.ix.schema,
                                         fieldboosts={f"{f}_folded": boost for f, boost in BOOSTS.items()},
                                         group=OrGroup.factory(0.85))
        original = parser.parse(query)
        folded = folded_parser.parse(fold_vietnamese(query))
        terms = {fold_vietnamese(t).casefold() for t in re.findall(r"[^\W_]+", query) if len(t) > 1}
        with self.ix.searcher(weighting=scoring.BM25F(B=0.75, K1=1.5)) as searcher:
            hits = searcher.search(DisjunctionMax([original, folded]), limit=None)
            ranked = []
            for hit in hits:
                if category and hit.get("category") != category:
                    continue
                text = " ".join(str(hit.get(field) or "") for field in FIELDS)
                tokens = {fold_vietnamese(t).casefold() for t in re.findall(r"[^\W_]+", text)}
                coverage = len(terms & tokens)
                if terms and coverage < len(terms):
                    continue
                strong_text = " ".join(str(hit.get(field) or "") for field in FIELDS[:-1])
                strong_tokens = {fold_vietnamese(t).casefold() for t in re.findall(r"[^\W_]+", strong_text)}
                strong_coverage = len(terms & strong_tokens)
                if strong_text.strip() and strong_coverage < len(terms):
                    continue
                strong_exact = len({t.casefold() for t in re.findall(r"[^\W_]+", query)} &
                                   {t.casefold() for t in re.findall(r"[^\W_]+", strong_text)})
                exact = len({t.casefold() for t in re.findall(r"[^\W_]+", query)} &
                            {t.casefold() for t in re.findall(r"[^\W_]+", text)})
                description = next(
                    (value for field in FIELDS if (value := str(hit.get(field) or ""))
                     and terms.intersection({fold_vietnamese(t).casefold() for t in re.findall(r"[^\W_]+", value)})),
                    next((str(hit.get(f) or "") for f in FIELDS if hit.get(f)), ""),
                )
                ranked.append((coverage, strong_exact, strong_coverage, exact, float(hit.score or 0), str(hit["image_id"]),
                               str(hit.get("canonical_image_url") or hit["image_url"]),
                               ImageResult(str(hit["image_id"]), str(hit["image_url"]),
                                           str(hit["source_url"]), str(hit.get("source_title") or ""),
                                           description, float(hit.score or 0))))
        if fold_vietnamese(query) != query and any(row[1] == len(terms) for row in ranked):
            ranked = [row for row in ranked if row[1] == len(terms)]
        ranked.sort(key=lambda row: (-row[0], -row[1], -row[2], -row[3], -row[4], row[5]))
        unique: dict[str, ImageResult] = {}
        for row in ranked:
            unique.setdefault(row[6], row[7])
        results = list(unique.values())
        start = (page - 1) * page_size
        return ImagePage(results[start:start + page_size], len(results), page, page_size,
                         (time.perf_counter() - started) * 1000)
