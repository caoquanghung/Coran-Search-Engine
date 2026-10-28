"""Xây/làm mới chỉ mục Whoosh bền vững trên ổ đĩa."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from whoosh import index

from .schema import DOCUMENT_SCHEMA, fold_vietnamese
from crawler.corpus import corpus_is_consistent, read_manifest


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def read_documents(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON không hợp lệ tại dòng {line_number}: {exc}") from exc


def build_index(documents_path: Path, index_dir: Path, *, recreate: bool = True) -> int:
    """Index JSONL. Ghi vào thư mục tạm rồi thay thế để hạn chế index dang dở."""
    if not documents_path.exists():
        raise FileNotFoundError(f"Không tìm thấy dataset: {documents_path}")
    manifest = read_manifest(documents_path)
    if manifest and not corpus_is_consistent(documents_path, documents_path.parent / str(manifest.get("images_file") or "images.jsonl")):
        raise ValueError("Corpus exports do not match the manifest")
    index_dir.parent.mkdir(parents=True, exist_ok=True)
    target = index_dir
    if recreate:
        target = index_dir.with_name(index_dir.name + "_building")
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        ix = index.create_in(target, DOCUMENT_SCHEMA)
    elif index.exists_in(index_dir):
        ix = index.open_dir(index_dir)
    else:
        index_dir.mkdir(parents=True, exist_ok=True)
        ix = index.create_in(index_dir, DOCUMENT_SCHEMA)

    writer = ix.writer(limitmb=128, procs=1)
    count = 0
    try:
        for doc in read_documents(documents_path):
            title = str(doc.get("title", "")).strip()
            content = str(doc.get("content", "")).strip()
            url = str(doc.get("url", "")).strip()
            if not title or not content or not url:
                continue
            description = str(doc.get("description", "")).strip()
            values = {
                "doc_id": str(doc.get("id") or url),
                "title": title,
                "description": description,
                "content": content,
                "folded": fold_vietnamese(" ".join((title, description, content))),
                "url": url,
                "category": str(doc.get("category", "")),
                "published_at": str(doc.get("published_at", "")),
                "comment_count": int(doc.get("comment_count") or 0),
                "image_url": str(doc.get("image_url", "")),
                "crawled_at": _parse_datetime(doc.get("crawled_at")),
            }
            writer.update_document(**values)
            count += 1
        writer.commit(optimize=True)
    except Exception:
        writer.cancel()
        raise

    if recreate:
        backup = index_dir.with_name(index_dir.name + "_old")
        if backup.exists():
            shutil.rmtree(backup)
        if index_dir.exists():
            index_dir.replace(backup)
        target.replace(index_dir)
        if backup.exists():
            shutil.rmtree(backup)
    return count


def update_article_index(doc: dict[str, Any], index_dir: Path) -> None:
    """Idempotent write for an article discovered by the scheduled crawler."""
    if not index.exists_in(index_dir):
        raise FileNotFoundError(index_dir)
    title = str(doc.get("title") or "").strip()
    content = str(doc.get("content") or "").strip()
    url = str(doc.get("url") or "").strip()
    if not title or not content or not url:
        raise ValueError("Article is missing title, content, or URL")
    description = str(doc.get("description") or "")
    writer = index.open_dir(index_dir).writer()
    try:
        writer.update_document(
            doc_id=str(doc.get("id") or url), title=title, description=description,
            content=content, folded=fold_vietnamese(" ".join((title, description, content))),
            url=url, category=str(doc.get("category") or ""),
            published_at=str(doc.get("published_at") or ""),
            comment_count=int(doc.get("comment_count") or 0),
            image_url=str(doc.get("image_url") or ""),
            crawled_at=_parse_datetime(doc.get("crawled_at")),
        )
        writer.commit()
    except Exception:
        writer.cancel()
        raise


def index_stats(index_dir: Path) -> dict[str, Any]:
    if not index.exists_in(index_dir):
        return {"ready": False, "documents": 0}
    ix = index.open_dir(index_dir)
    with ix.searcher() as searcher:
        return {"ready": True, "documents": searcher.doc_count_all()}
