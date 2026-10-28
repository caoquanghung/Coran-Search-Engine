"""Lazy crawler lấy ảnh liên quan từ các bài vừa xuất hiện trong search result."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from engine.schema import fold_vietnamese

LOGGER = logging.getLogger(__name__)
WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class ResultImage:
    image_url: str
    source_url: str
    source_title: str
    caption: str
    score: tuple[int, int, int]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize(value: str) -> str:
    return fold_vietnamese(value).casefold()


def _terms(value: str) -> list[str]:
    return [_normalize(match.group()) for match in WORD_RE.finditer(value) if len(match.group()) > 1]


def _safe_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (
        parsed.netloc == "vnexpress.net" or parsed.netloc.endswith(".vnexpress.net")
    )


def _safe_image_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _image_source(node: object) -> str:
    if not hasattr(node, "get"):
        return ""
    for attribute in ("data-src", "data-original", "data-lazy-src", "src"):
        value = node.get(attribute, "")  # type: ignore[union-attr]
        if value and not str(value).startswith("data:"):
            return str(value).strip()
    srcset = str(node.get("data-srcset") or node.get("srcset") or "")  # type: ignore[union-attr]
    if srcset:
        # VnExpress thường đặt ảnh độ phân giải lớn ở cuối srcset.
        return srcset.split(",")[-1].strip().split(" ")[0]
    return ""


def extract_images(html_text: str, source_url: str, query: str) -> list[ResultImage]:
    """Trích và xếp hạng ảnh; không thực hiện request mạng."""
    soup = BeautifulSoup(html_text, "lxml")
    title_node = soup.select_one("h1.title-detail, h1.title_news_detail, h1")
    source_title = title_node.get_text(" ", strip=True) if title_node else ""
    query_terms = set(_terms(query))
    candidates: list[ResultImage] = []
    seen: set[str] = set()

    nodes = list(soup.select("article img, .fck_detail img"))
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image and og_image.get("content"):
        # Dùng một node giả để ảnh đại diện tham gia cùng pipeline.
        nodes.insert(0, og_image)

    for position, node in enumerate(nodes):
        raw_url = str(node.get("content", "")) if node.name == "meta" else _image_source(node)
        image_url = urljoin(source_url, raw_url)
        if not raw_url or not _safe_image_url(image_url) or image_url in seen:
            continue
        seen.add(image_url)

        figure = node.find_parent("figure")
        figcaption = figure.select_one("figcaption") if figure else None
        caption = " ".join(
            part
            for part in (
                str(node.get("alt", "")),
                figcaption.get_text(" ", strip=True) if figcaption else "",
            )
            if part
        ).strip()
        searchable = " ".join((source_title, caption))
        normalized_tokens = _terms(searchable)
        covered = query_terms.intersection(normalized_tokens)
        occurrences = sum(token in query_terms for token in normalized_tokens)
        # coverage > số lần lặp > ảnh xuất hiện sớm trong bài.
        score = (len(covered), occurrences, -position)
        candidates.append(
            ResultImage(
                image_url=image_url,
                source_url=source_url,
                source_title=source_title,
                caption=caption or source_title,
                score=score,
            )
        )
    return sorted(candidates, key=lambda item: item.score, reverse=True)


class LazyImageCrawler:
    """Crawl song song một tập URL kết quả nhỏ, có timeout và giới hạn ảnh."""

    def __init__(self, *, timeout: float = 6.0, workers: int = 3) -> None:
        self.timeout = timeout
        self.workers = workers
        self.session = requests.Session()
        retry = Retry(
            total=1,
            backoff_factor=0.25,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; HCMUS-IR-Image-MVP/1.0)",
                "Accept-Language": "vi-VN,vi;q=0.9",
            }
        )

    def _crawl_one(self, url: str, query: str) -> list[ResultImage]:
        if not _safe_article_url(url):
            return []
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return extract_images(response.text, url, query)
        except requests.RequestException as exc:
            LOGGER.warning("Không lazy-crawl được ảnh từ %s: %s", url, exc)
            return []

    def crawl(
        self,
        urls: Iterable[str],
        query: str,
        *,
        max_articles: int = 6,
        max_images: int = 6,
        images_per_article: int = 2,
    ) -> list[ResultImage]:
        safe_urls = list(dict.fromkeys(url for url in urls if _safe_article_url(url)))[:max_articles]
        if not safe_urls or not query.strip():
            return []

        collected: list[ResultImage] = []
        with ThreadPoolExecutor(max_workers=min(self.workers, len(safe_urls))) as executor:
            futures = {executor.submit(self._crawl_one, url, query): url for url in safe_urls}
            for future in as_completed(futures):
                collected.extend(future.result()[:images_per_article])

        unique: dict[str, ResultImage] = {}
        for image in collected:
            previous = unique.get(image.image_url)
            if previous is None or image.score > previous.score:
                unique[image.image_url] = image
        return sorted(unique.values(), key=lambda item: item.score, reverse=True)[:max_images]


def crawl_result_images(urls: Iterable[str], query: str, max_images: int = 6) -> list[dict[str, object]]:
    """API đơn giản, trả dict để cache/serialize thuận tiện trong Streamlit."""
    return [item.to_dict() for item in LazyImageCrawler().crawl(urls, query, max_images=max_images)]
