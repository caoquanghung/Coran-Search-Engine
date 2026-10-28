"""Persistent image text index schema."""

from whoosh.fields import ID, NUMERIC, STORED, TEXT, Schema

from .schema import VI_ANALYZER


IMAGE_SCHEMA = Schema(
    image_id=ID(stored=True, unique=True),
    image_url=STORED, canonical_image_url=STORED,
    source_doc_id=ID(stored=True), source_url=STORED, source_title=STORED,
    caption=TEXT(stored=True, analyzer=VI_ANALYZER),
    alt_text=TEXT(stored=True, analyzer=VI_ANALYZER),
    image_title=TEXT(stored=True, analyzer=VI_ANALYZER),
    nearby_text=TEXT(stored=True, analyzer=VI_ANALYZER),
    caption_folded=TEXT(analyzer=VI_ANALYZER),
    alt_text_folded=TEXT(analyzer=VI_ANALYZER),
    image_title_folded=TEXT(analyzer=VI_ANALYZER),
    nearby_text_folded=TEXT(analyzer=VI_ANALYZER),
    category=ID(stored=True), published_at=STORED, crawled_at=STORED,
    position=NUMERIC(stored=True), context_source=STORED,
)
