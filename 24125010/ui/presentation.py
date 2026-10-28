"""Escaped, responsive search-result markup without network requests."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlparse

BRAND = "WangWangSearch"
COLORS = ("#4285f4", "#ea4335", "#fbbc05", "#4285f4", "#34a853", "#ea4335")


def safe(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def safe_url(value: str) -> str:
    parsed = urlparse(value)
    return safe(value) if parsed.scheme in {"http", "https"} and parsed.netloc else "#"


def styles(home: bool) -> str:
    css = (Path(__file__).parent / "styles.css").read_text(encoding="utf-8")
    if home:
        css += """
        .st-key-topbar {max-width:720px;margin:clamp(60px,13vh,145px) auto 0;}
        .st-key-topbar [data-testid="stHorizontalBlock"]:not(.st-key-search_pill [data-testid="stHorizontalBlock"]) {grid-template-columns:minmax(0,1fr);gap:25px;}
        .st-key-topbar [data-testid="stHorizontalBlock"]:not(.st-key-search_pill [data-testid="stHorizontalBlock"]) > div {width:100%;}
        .st-key-topbar [data-testid="stHorizontalBlock"]:not(.st-key-search_pill [data-testid="stHorizontalBlock"]) > div:last-child {display:none;}
        .brand {font-size:58px;letter-spacing:-3.3px;text-align:center;line-height:1.25;}
        .st-key-search_pill {max-width:650px;margin:auto;}
        @media(max-width:700px){.brand{font-size:42px;letter-spacing:-2.5px;}.st-key-topbar{margin-top:80px;}}
        """
    return f"<style>{css}</style>"


def brand() -> str:
    letters = "".join(f'<span style="color:{COLORS[i % len(COLORS)]}">{safe(char)}</span>' for i, char in enumerate(BRAND))
    return f'<a class="brand" href="/?q=" target="_self" aria-label="{BRAND} — Trang chủ">{letters}</a>'


def format_date(value: str) -> str:
    try:
        year, month, day = value[:10].split("-")
        return f"{int(day)} thg {int(month)}, {year}"
    except (ValueError, AttributeError):
        return ""


def article(result) -> str:
    host = urlparse(result.url).netloc.removeprefix("www.")
    category = result.category or "Tin tức"
    date = format_date(result.published_at)
    date_html = f'<span class="result-date">{safe(date)} — </span>' if date else ""
    return f"""<article class="search-result">
      <a class="result-source" href="{safe_url(result.url)}" target="_blank" rel="noopener noreferrer">
        <span class="source-icon" aria-hidden="true">V<span>n</span></span>
        <span class="source-detail"><span class="source-name">VnExpress</span>
          <span class="source-path">{safe(host)} <span aria-hidden="true">›</span> {safe(category)}</span></span>
      </a>
      <h2><a href="{safe_url(result.url)}" target="_blank" rel="noopener noreferrer">{safe(result.title)}</a></h2>
      <div class="result-snippet">{date_html}{result.snippet}</div>
      <div class="result-details">{safe(category)}<span aria-hidden="true"> · </span>{int(result.comment_count):,} bình luận</div>
    </article>"""


def image_grid(results: list, *, preview: bool = False) -> str:
    cards = []
    for result in results:
        description = result.description or result.source_title
        host = urlparse(result.source_url).netloc.removeprefix("www.")
        cards.append(f"""<article class="image-card">
          <a class="image-link" href="{safe_url(result.source_url)}" target="_blank" rel="noopener noreferrer" aria-label="{safe(description)} — {safe(host)}">
            <div class="image-frame"><img src="{safe_url(result.image_url)}" alt="{safe(description)}" loading="lazy" decoding="async" referrerpolicy="no-referrer"></div>
            <div class="image-source"><span class="image-source-dot" aria-hidden="true">V</span>{safe(host)}</div>
            <div class="image-description">{safe(description)}</div>
          </a>
        </article>""")
    return f'<div class="image-grid {"image-preview-grid" if preview else ""}">' + "".join(cards) + "</div>"


def empty_state(query: str, *, images: bool = False) -> str:
    noun = "hình ảnh" if images else "kết quả"
    return f"""<div class="empty-state"><div class="empty-symbol" aria-hidden="true">⌕</div>
      <h2>Không tìm thấy {noun} phù hợp</h2>
      <p>Thử tìm kiếm khác cho <strong>“{safe(query)}”</strong>.</p>
      <ul><li>Kiểm tra lại chính tả.</li><li>Dùng từ khóa ngắn hơn hoặc diễn đạt theo cách khác.</li></ul></div>"""


def footer(count: int, *, home: bool, semantic: bool) -> str:
    mode = "Từ khóa & ngữ nghĩa" if semantic else "Tìm kiếm từ khóa"
    return f'<div class="page-footer {"home-footer" if home else ""}"><span>Việt Nam</span><span>{count:,} bài viết từ VnExpress <span class="footer-separator">·</span> {mode}</span></div>'
