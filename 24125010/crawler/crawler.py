"""Crawler đồng bộ, có retry/rate-limit, dành cho tập dữ liệu MVP nhỏ."""

from __future__ import annotations

import heapq
import json
import logging
import re
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .parser import Article, parse_article
from .corpus import write_corpus

LOGGER = logging.getLogger(__name__)
ARTICLE_URL_RE = re.compile(r"-\d{7,}\.html(?:\?.*)?$", re.I)


class VnExpressCrawler:
    """Khám phá bài từ các trang seed và giữ N bài có nhiều bình luận nhất."""

    def __init__(
        self,
        seeds: Iterable[str],
        *,
        max_documents: int = 100,
        pages_per_seed: int = 5,
        candidate_limit: int = 500,
        delay: float = 0.35,
        timeout: float = 15,
    ) -> None:
        self.seeds = [s.strip() for s in seeds if s.strip() and not s.startswith("#")]
        self.max_documents = max_documents
        self.pages_per_seed = pages_per_seed
        self.candidate_limit = candidate_limit
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; HCMUS-IR-MVP/1.0; "
                    "+https://vnexpress.net/)"
                ),
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
            }
        )

    @staticmethod
    def _clean_url(url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", parsed.query, ""))

    @classmethod
    def _is_article_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.netloc == "vnexpress.net" or parsed.netloc.endswith(".vnexpress.net")) and bool(ARTICLE_URL_RE.search(url))

    @staticmethod
    def _page_url(seed: str, page: int) -> str:
        if page == 1:
            return seed
        base = seed.rstrip("/")
        return f"{base}-p{page}" if not re.search(r"-p\d+$", base) else re.sub(r"-p\d+$", f"-p{page}", base)

    def _get(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        time.sleep(self.delay)
        return response.text

    def discover(self) -> list[str]:
        """Lấy URL ứng viên theo thứ tự xuất hiện, loại trùng ổn định."""
        found: dict[str, None] = {}
        for seed in self.seeds:
            for page in range(1, self.pages_per_seed + 1):
                page_url = self._page_url(seed, page)
                try:
                    soup = BeautifulSoup(self._get(page_url), "lxml")
                except requests.RequestException as exc:
                    LOGGER.warning("Không đọc được %s: %s", page_url, exc)
                    continue
                for anchor in soup.select("a[href]"):
                    url = self._clean_url(urljoin(page_url, str(anchor.get("href", ""))))
                    if self._is_article_url(url):
                        found.setdefault(url, None)
                        if len(found) >= self.candidate_limit:
                            return list(found)
        return list(found)

    def crawl(self) -> list[Article]:
        candidates = self.discover()
        LOGGER.info("Tìm thấy %d URL bài viết ứng viên", len(candidates))
        heap: list[tuple[int, str, Article]] = []
        for position, url in enumerate(candidates, start=1):
            try:
                article = parse_article(self._get(url), url)
            except requests.RequestException as exc:
                LOGGER.warning("Bỏ qua %s: %s", url, exc)
                continue
            except Exception:
                LOGGER.exception("Lỗi parse %s", url)
                continue
            if article is None:
                continue
            item = (article.comment_count, article.id, article)
            if len(heap) < self.max_documents:
                heapq.heappush(heap, item)
            elif item[:2] > heap[0][:2]:
                heapq.heapreplace(heap, item)
            LOGGER.info("[%d/%d] %d bình luận — %s", position, len(candidates), article.comment_count, article.title)
        return [item[2] for item in sorted(heap, key=lambda value: (-value[0], value[1]))]

    @staticmethod
    def write_jsonl(articles: Iterable[Article], output: Path) -> int:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        count = 0
        with temporary.open("w", encoding="utf-8") as stream:
            for article in articles:
                stream.write(json.dumps(article.to_dict(), ensure_ascii=False) + "\n")
                count += 1
        temporary.replace(output)
        return count

    @staticmethod
    def write_corpus(articles: Iterable[Article], output: Path, images_output: Path) -> dict:
        return write_corpus([article.to_dict() for article in articles], output, images_output)
