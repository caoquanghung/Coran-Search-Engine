"""Tách dữ liệu có cấu trúc từ trang chi tiết VnExpress."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .image_records import ArticleImage, extract_article_images


_SPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"([\d.,]+)\s*(?:ý\s*kiến|bình\s*luận|comments?)", re.I)


def _text(value: object) -> str:
    return _SPACE_RE.sub(" ", value if isinstance(value, str) else "").strip()


def _number(value: str | None) -> int:
    if not value:
        return 0
    match = re.search(r"\d[\d.,]*", value)
    if not match:
        return 0
    return int(re.sub(r"\D", "", match.group()))


@dataclass(slots=True)
class Article:
    """Một tài liệu được lưu vào JSONL và Whoosh."""

    id: str
    title: str
    description: str
    content: str
    url: str
    category: str = ""
    published_at: str = ""
    comment_count: int = 0
    image_url: str = ""
    crawled_at: str = ""
    images: list[ArticleImage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    """Lấy NewsArticle đầu tiên; bỏ qua JSON-LD lỗi thay vì làm hỏng lượt crawl."""
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        if isinstance(value, dict) and isinstance(value.get("@graph"), list):
            candidates += value["@graph"]
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") in {
                "Article",
                "NewsArticle",
                "ReportageNewsArticle",
            }:
                return item
    return {}


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        node = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if node and node.get("content"):
            return _text(str(node["content"]))
    return ""


def _comment_count(soup: BeautifulSoup, html: str) -> int:
    selectors = (
        ".count-comment",
        ".txt_num_comment",
        "[data-component-type='comment'] .number",
        "[class*='comment'] [class*='count']",
    )
    for selector in selectors:
        for node in soup.select(selector):
            value = _number(node.get("data-count") or node.get_text(" ", strip=True))
            if value:
                return value

    # Các phiên bản trang VnExpress từng nhúng total comment dưới những key này.
    patterns = (
        r'"(?:comment_count|total_comment|total_comments|count_comment)"\s*:\s*"?(\d+)',
        r"(?:comment_count|total_comment|total_comments)\s*=\s*['\"]?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return int(match.group(1))
    match = _NUMBER_RE.search(soup.get_text(" ", strip=True))
    return _number(match.group(1)) if match else 0


def parse_article(html: str, source_url: str) -> Article | None:
    """Parse một trang bài báo. Trả về ``None`` nếu đây không phải bài hợp lệ."""
    soup = BeautifulSoup(html, "lxml")
    structured = _json_ld(soup)

    title_node = soup.select_one("h1.title-detail, h1.title_news_detail, h1")
    title = _text(title_node.get_text(" ") if title_node else "")
    title = title or _text(structured.get("headline")) or _meta(soup, "og:title")

    description_node = soup.select_one("p.description, .description, .lead_detail")
    description = _text(description_node.get_text(" ") if description_node else "")
    description = (
        description
        or _text(structured.get("description"))
        or _meta(soup, "description", "og:description")
    )

    canonical_node = soup.select_one('link[rel="canonical"]')
    canonical = str(canonical_node.get("href", "")) if canonical_node else ""
    url = urljoin(source_url, canonical or _meta(soup, "og:url") or source_url)

    category = _meta(soup, "article:section")
    if not category:
        breadcrumb = soup.select_one(".breadcrumb li:last-child, .breadcrumb a:last-child")
        category = _text(breadcrumb.get_text(" ") if breadcrumb else "")

    published_at = (
        _meta(soup, "article:published_time")
        or _text(structured.get("datePublished"))
        or _text((soup.select_one("time") or {}).get("datetime", ""))
    )
    image = structured.get("image", "")
    if isinstance(image, list):
        image = image[0] if image else ""
    if isinstance(image, dict):
        image = image.get("url", "")

    article_id_match = re.search(r"-(\d{7,})(?:\.html)?(?:\?|$)", url)
    article_id = (
        article_id_match.group(1)
        if article_id_match
        else hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    )
    crawled_at = datetime.now(timezone.utc).isoformat()
    images = extract_article_images(
        soup, source_doc_id=article_id, source_url=url,
        source_title=title, category=category, published_at=published_at,
        crawled_at=crawled_at,
    )
    body = soup.select_one("article.fck_detail, .fck_detail, article")
    if body:
        for unwanted in body.select(
            "script, style, iframe, figure figcaption, .box-tinlienquan, .social, .banner-ads"
        ):
            unwanted.decompose()
        paragraphs = [_text(p.get_text(" ")) for p in body.select("p")]
        content = "\n".join(p for p in paragraphs if p)
        if not content:
            content = _text(body.get_text(" "))
    else:
        article_body = structured.get("articleBody")
        content = _text(article_body if isinstance(article_body, str) else "")
    if not title or len(content) < 80:
        return None
    return Article(
        id=article_id,
        title=title,
        description=description,
        content=content,
        url=url,
        category=category,
        published_at=published_at,
        comment_count=_comment_count(soup, html),
        image_url=urljoin(url, str(image or _meta(soup, "og:image"))) if (image or _meta(soup, "og:image")) else "",
        crawled_at=crawled_at,
        images=images,
    )
