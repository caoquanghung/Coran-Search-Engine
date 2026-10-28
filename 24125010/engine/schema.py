"""Schema và analyzer dùng chung cho index/query."""

from __future__ import annotations

import unicodedata

from whoosh.analysis import LowercaseFilter, RegexTokenizer
from whoosh.fields import DATETIME, ID, KEYWORD, NUMERIC, STORED, TEXT, Schema


VI_ANALYZER = RegexTokenizer(r"[\wÀ-ỹ]+") | LowercaseFilter()


def fold_vietnamese(value: str) -> str:
    """Bỏ dấu để tìm 'cong nghe' vẫn khớp 'công nghệ'."""
    value = value.replace("Đ", "D").replace("đ", "d")
    return "".join(
        char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn"
    )


DOCUMENT_SCHEMA = Schema(
    doc_id=ID(stored=True, unique=True),
    title=TEXT(stored=True, analyzer=VI_ANALYZER, field_boost=3.0),
    description=TEXT(stored=True, analyzer=VI_ANALYZER, field_boost=1.8),
    content=TEXT(stored=True, analyzer=VI_ANALYZER),
    folded=TEXT(stored=False, analyzer=VI_ANALYZER),
    url=ID(stored=True),
    category=KEYWORD(stored=True, lowercase=True, commas=True, scorable=True),
    published_at=STORED,
    comment_count=NUMERIC(stored=True, sortable=True, numtype=int),
    image_url=STORED,
    crawled_at=DATETIME(stored=True),
)
