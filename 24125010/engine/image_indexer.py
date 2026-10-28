"""Build and incrementally update a Whoosh index of image descriptions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from whoosh import index

from .image_schema import IMAGE_SCHEMA
from .schema import fold_vietnamese
from crawler.corpus import corpus_is_consistent, read_manifest


def image_values(row: dict) -> dict:
    fields = ("caption", "alt_text", "image_title", "nearby_text")
    values = {field: str(row.get(field) or "") for field in fields}
    return {
        "image_id": str(row["image_id"]),
        "image_url": str(row["image_url"]),
        "canonical_image_url": str(row.get("canonical_image_url") or row["image_url"]),
        "source_doc_id": str(row["source_doc_id"]),
        "source_url": str(row["source_url"]),
        "source_title": str(row.get("source_title") or ""),
        **values,
        **{f"{field}_folded": fold_vietnamese(value) for field, value in values.items()},
        "category": str(row.get("category") or ""),
        "published_at": str(row.get("published_at") or ""),
        "crawled_at": str(row.get("crawled_at") or ""),
        "position": int(row.get("position") or 0),
        "context_source": str(row.get("context_source") or ""),
    }


def read_images(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def build_image_index(images_path: Path, index_dir: Path) -> int:
    rows = read_images(images_path)
    manifest = read_manifest(images_path)
    if manifest and manifest.get("images") != len(rows):
        raise ValueError("Image export does not match corpus manifest")
    if manifest and not corpus_is_consistent(images_path.parent / str(manifest.get("documents_file") or "documents.jsonl"), images_path):
        raise ValueError("Corpus exports do not match the manifest")
    target = index_dir.with_name(index_dir.name + "_building")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    ix = index.create_in(target, IMAGE_SCHEMA)
    writer = ix.writer()
    count = 0
    try:
        for row in rows:
            if row.get("searchable"):
                writer.update_document(**image_values(row))
                count += 1
        writer.commit()
    except Exception:
        writer.cancel()
        shutil.rmtree(target)
        raise
    backup = index_dir.with_name(index_dir.name + "_old")
    if backup.exists():
        shutil.rmtree(backup)
    if index_dir.exists():
        index_dir.replace(backup)
    try:
        target.replace(index_dir)
    except Exception:
        if backup.exists():
            backup.replace(index_dir)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    return count


def update_image_index(rows: list[dict], index_dir: Path) -> int:
    if not rows:
        return 0
    if not index.exists_in(index_dir):
        index_dir.mkdir(parents=True, exist_ok=True)
        ix = index.create_in(index_dir, IMAGE_SCHEMA)
    else:
        ix = index.open_dir(index_dir)
    writer = ix.writer()
    try:
        for row in rows:
            if row.get("searchable"):
                writer.update_document(**image_values(row))
        writer.commit()
    except Exception:
        writer.cancel()
        raise
    return sum(bool(row.get("searchable")) for row in rows)


def image_index_stats(index_dir: Path) -> dict:
    if not index.exists_in(index_dir):
        return {"ready": False, "images": 0}
    with index.open_dir(index_dir).searcher() as searcher:
        return {"ready": True, "images": searcher.doc_count()}
