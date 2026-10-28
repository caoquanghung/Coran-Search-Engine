"""Extract searchable image descriptions from the original article HTML."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def image_identity(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", parsed.query, ""))


@dataclass(slots=True)
class ArticleImage:
    image_id: str
    image_url: str
    canonical_image_url: str
    source_doc_id: str
    source_url: str
    source_title: str
    alt_text: str = ""
    caption: str = ""
    image_title: str = ""
    nearby_text: str = ""
    category: str = ""
    published_at: str = ""
    crawled_at: str = ""
    position: int = 0
    width: int = 0
    height: int = 0
    context_source: str = ""
    searchable: bool = False
    record_version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


def _srcset(value: str) -> str:
    choices: list[tuple[float, str]] = []
    for entry in value.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        descriptor = parts[1] if len(parts) > 1 else "1x"
        try:
            size = float(descriptor[:-1]) if descriptor.endswith(("w", "x")) else 1.0
        except ValueError:
            size = 1.0
        choices.append((size, parts[0]))
    return max(choices)[1] if choices else ""


def _source(node: Tag) -> str:
    for attribute in ("data-src", "data-original", "data-lazy-src"):
        candidate = str(node.get(attribute) or "").strip()
        if candidate and not candidate.startswith(("data:", "blob:")) and candidate != "#":
            return candidate
    picture = node.find_parent("picture")
    for source in picture.select("source[srcset], source[data-srcset]") if picture else []:
        candidate = _srcset(str(source.get("data-srcset") or source.get("srcset") or ""))
        if candidate:
            return candidate
    candidate = _srcset(str(node.get("data-srcset") or node.get("srcset") or ""))
    if candidate:
        return candidate
    return str(node.get("src") or "").strip()


def _dimension(node: Tag, name: str) -> int:
    match = re.match(r"\d+", str(node.get(name) or ""))
    return int(match.group()) if match else 0


def _nearby(node: Tag) -> str:
    anchor = node.find_parent("figure") or node
    pieces: list[str] = []
    for sibling in (anchor.find_previous_sibling("p"), anchor.find_next_sibling("p")):
        if sibling and not sibling.find("img"):
            part = clean(sibling.get_text(" ", strip=True))
            if part and part not in pieces:
                pieces.append(part)
    return clean(" ".join(pieces))[:500]


def extract_article_images(
    soup: BeautifulSoup, *, source_doc_id: str, source_url: str,
    source_title: str, category: str = "", published_at: str = "", crawled_at: str = "",
) -> list[ArticleImage]:
    body = soup.select_one("article.fck_detail, .fck_detail, article")
    nodes = body.select("img") if body else []
    found: dict[str, ArticleImage] = {}
    for position, node in enumerate(nodes):
        if node.find_parent(class_=re.compile(r"(?:banner|social|related|tinlienquan|advert)", re.I)):
            continue
        width, height = _dimension(node, "width"), _dimension(node, "height")
        if (width and width < 48) or (height and height < 48):
            continue
        raw = _source(node)
        url = urljoin(source_url, raw)
        parsed = urlparse(url)
        if not raw or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        figure = node.find_parent("figure")
        caption_node = figure.select_one("figcaption, .figcaption, .Image, .image-caption") if figure else None
        caption = clean(caption_node.get_text(" ", strip=True)) if caption_node else ""
        alt = clean(str(node.get("alt") or ""))
        image_title = clean(str(node.get("title") or ""))
        nearby = _nearby(node)
        identity = image_identity(url)
        record = ArticleImage(
            image_id=hashlib.sha1(f"{source_doc_id}\0{identity}".encode()).hexdigest(),
            image_url=url, canonical_image_url=identity, source_doc_id=source_doc_id,
            source_url=source_url, source_title=source_title, alt_text=alt,
            caption=caption, image_title=image_title, nearby_text=nearby,
            category=category, published_at=published_at, crawled_at=crawled_at,
            position=position, width=width, height=height,
            context_source=",".join(k for k, v in (("caption", caption), ("alt", alt), ("title", image_title), ("nearby", nearby)) if v),
            searchable=bool(caption or alt or image_title or nearby),
        )
        previous = found.get(identity)
        if previous:
            for field in ("caption", "alt_text", "image_title", "nearby_text"):
                if len(getattr(record, field)) > len(getattr(previous, field)):
                    setattr(previous, field, getattr(record, field))
            previous.searchable = bool(previous.caption or previous.alt_text or previous.image_title or previous.nearby_text)
            previous.context_source = ",".join(k for k, v in (("caption", previous.caption), ("alt", previous.alt_text), ("title", previous.image_title), ("nearby", previous.nearby_text)) if v)
        else:
            found[identity] = record
    meta = soup.select_one('meta[property="og:image"]')
    if meta and meta.get("content"):
        url = urljoin(source_url, str(meta["content"]))
        parsed = urlparse(url)
        identity = image_identity(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc and identity not in found:
            found[identity] = ArticleImage(
                image_id=hashlib.sha1(f"{source_doc_id}\0{identity}".encode()).hexdigest(),
                image_url=url, canonical_image_url=identity, source_doc_id=source_doc_id,
                source_url=source_url, source_title=source_title, category=category,
                published_at=published_at, crawled_at=crawled_at, position=len(nodes),
            )
    return list(found.values())
