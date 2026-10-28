"""Durable discovery and incremental indexing for new articles."""

from __future__ import annotations

import fcntl
import json
import logging
import sqlite3
import time
import shutil
from contextlib import contextmanager
from pathlib import Path

import requests

from .corpus import corpus_is_consistent, write_corpus
from .crawler import VnExpressCrawler
from .parser import parse_article
from engine.image_indexer import build_image_index, update_image_index
from engine.indexer import build_index, read_documents, update_article_index
from engine.vector_index import build_vector_indexes

LOGGER = logging.getLogger(__name__)


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class CrawlLoop:
    def __init__(self, crawler: VnExpressCrawler, *, documents_path: Path,
                 images_path: Path, article_index: Path, image_index: Path,
                 state_path: Path, vector_dir: Path | None = None) -> None:
        self.crawler = crawler
        self.documents_path = documents_path
        self.images_path = images_path
        self.article_index = article_index
        self.image_index = image_index
        self.state_path = state_path
        self.vector_dir = vector_dir or article_index.parent / "vector_index"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(state_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS articles (url TEXT PRIMARY KEY, doc_id TEXT, status TEXT NOT NULL, payload TEXT, attempts INTEGER DEFAULT 0, retry_at REAL DEFAULT 0)")
        self.db.execute("CREATE INDEX IF NOT EXISTS article_doc_id ON articles(doc_id)")
        self.db.commit()
        self._snapshot_bootstrap()
        self._seed()

    def _snapshot_bootstrap(self) -> None:
        for path in (self.documents_path, self.images_path):
            snapshot = path.with_name("bootstrap_" + path.name)
            if path.exists() and not snapshot.exists():
                shutil.copy2(path, snapshot)

    def _seed(self) -> None:
        if not self.documents_path.exists():
            return
        for doc in read_documents(self.documents_path):
            url = self.crawler._clean_url(str(doc.get("url") or ""))
            if url:
                self.db.execute("INSERT OR IGNORE INTO articles(url,doc_id,status) VALUES (?,?,?)",
                                (url, str(doc.get("id") or url), "done"))
        self.db.commit()

    def _documents(self) -> list[dict]:
        return list(read_documents(self.documents_path)) if self.documents_path.exists() else []

    def _index_pending(self, url: str, doc: dict) -> None:
        documents = self._documents()
        changed = False
        if not any(str(item.get("id")) == str(doc.get("id")) for item in documents):
            documents.append(doc)
            changed = True
        if changed or not corpus_is_consistent(self.documents_path, self.images_path):
            write_corpus(documents, self.documents_path, self.images_path)
        if not self.article_index.exists():
            build_index(self.documents_path, self.article_index)
        else:
            update_article_index(doc, self.article_index)
        if not self.image_index.exists():
            build_image_index(self.images_path, self.image_index)
        else:
            update_image_index(doc.get("images") or [], self.image_index)
        if (self.vector_dir / "manifest.json").exists():
            build_vector_indexes(self.documents_path, self.images_path, self.vector_dir)
        self.db.execute("UPDATE articles SET status='done', payload=NULL WHERE url=?", (url,))
        self.db.commit()

    def run_once(self) -> dict[str, int]:
        with _lock(self.state_path.with_suffix(".lock")):
            counts = {"discovered": 0, "skipped": 0, "new": 0, "images": 0, "failed": 0}
            for url, payload in self.db.execute("SELECT url,payload FROM articles WHERE status='pending'").fetchall():
                try:
                    self._index_pending(url, json.loads(payload))
                except Exception:
                    LOGGER.exception("Could not resume indexing %s", url)
                    counts["failed"] += 1
            urls = self.crawler.discover()
            counts["discovered"] = len(urls)
            for url in urls:
                normalized = self.crawler._clean_url(url)
                prior = self.db.execute("SELECT status,attempts,retry_at FROM articles WHERE url=?", (normalized,)).fetchone()
                if prior and (prior[0] in {"done", "invalid", "pending"} or prior[2] > time.time()):
                    counts["skipped"] += 1
                    continue
                try:
                    article = parse_article(self.crawler._get(url), url)
                    if article is None:
                        self.db.execute("INSERT INTO articles(url,status) VALUES (?,'invalid') ON CONFLICT(url) DO UPDATE SET status='invalid'", (normalized,))
                        self.db.commit()
                        continue
                    doc = article.to_dict()
                    duplicate = self.db.execute("SELECT 1 FROM articles WHERE doc_id=? AND status='done' LIMIT 1", (article.id,)).fetchone()
                    if duplicate:
                        self.db.execute("INSERT INTO articles(url,doc_id,status) VALUES (?,?,'done') ON CONFLICT(url) DO UPDATE SET doc_id=excluded.doc_id,status='done'", (normalized, article.id))
                        self.db.commit()
                        counts["skipped"] += 1
                        continue
                    self.db.execute("INSERT INTO articles(url,doc_id,status,payload) VALUES (?,?,'pending',?) ON CONFLICT(url) DO UPDATE SET doc_id=excluded.doc_id,status='pending',payload=excluded.payload", (normalized, article.id, json.dumps(doc, ensure_ascii=False)))
                    self.db.commit()
                    self._index_pending(normalized, doc)
                    counts["new"] += 1
                    counts["images"] += len(doc.get("images") or [])
                except requests.RequestException:
                    LOGGER.exception("Fetch failed for %s", url)
                    attempts = (prior[1] if prior else 0) + 1
                    retry_at = time.time() + min(3600, 30 * 2 ** min(attempts, 6))
                    self.db.execute("INSERT INTO articles(url,status,attempts,retry_at) VALUES (?,'retry',?,?) ON CONFLICT(url) DO UPDATE SET status='retry',attempts=excluded.attempts,retry_at=excluded.retry_at", (normalized, attempts, retry_at))
                    self.db.commit()
                    counts["failed"] += 1
                except Exception:
                    LOGGER.exception("Could not process %s", url)
                    counts["failed"] += 1
            LOGGER.info("Crawl pass: %s", counts)
            return counts

    def run_forever(self, interval: float = 900) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        next_run = time.monotonic()
        while True:
            time.sleep(max(0, next_run - time.monotonic()))
            self.run_once()
            next_run += interval
            if next_run <= time.monotonic():
                next_run = time.monotonic() + interval
