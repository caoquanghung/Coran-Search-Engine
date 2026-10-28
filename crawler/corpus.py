"""Versioned article and image exports."""

from __future__ import annotations

import json
import os
import uuid
import hashlib
from pathlib import Path
from typing import Iterable, Mapping


def _stage(path: Path, rows: Iterable[Mapping]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return tmp


def write_corpus(documents: list[dict], documents_path: Path, images_path: Path) -> dict:
    """Publish both exports; nested article images remain the recovery source."""
    images = [image for doc in documents for image in doc.get("images", [])]
    generation = uuid.uuid4().hex
    doc_tmp = _stage(documents_path, documents)
    image_tmp = _stage(images_path, images)
    manifest_path = documents_path.parent / "corpus_manifest.json"
    manifest = {"generation": generation, "documents": len(documents), "images": len(images), "record_version": 1,
                "documents_file": documents_path.name, "images_file": images_path.name,
                "documents_sha256": hashlib.sha256(doc_tmp.read_bytes()).hexdigest(),
                "images_sha256": hashlib.sha256(image_tmp.read_bytes()).hexdigest()}
    manifest_tmp = _stage(manifest_path, [manifest])
    # The manifest is written last. A mismatched export can be recovered from nested records.
    doc_tmp.replace(documents_path)
    image_tmp.replace(images_path)
    manifest_tmp.replace(manifest_path)
    return manifest


def read_manifest(path: Path) -> dict | None:
    manifest_path = path.parent / "corpus_manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def corpus_is_consistent(documents_path: Path, images_path: Path) -> bool:
    manifest = read_manifest(documents_path)
    return bool(
        manifest and documents_path.exists() and images_path.exists()
        and hashlib.sha256(documents_path.read_bytes()).hexdigest() == manifest.get("documents_sha256")
        and hashlib.sha256(images_path.read_bytes()).hexdigest() == manifest.get("images_sha256")
    )
