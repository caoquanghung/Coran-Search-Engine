#!/usr/bin/env python3
"""Refetch existing article URLs and add image descriptions without reselection."""

import argparse
import logging
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler.corpus import write_corpus  # noqa: E402
from crawler.crawler import VnExpressCrawler  # noqa: E402
from crawler.parser import parse_article  # noqa: E402
from engine.indexer import read_documents  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/documents.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/images.jsonl"))
    parser.add_argument("--delay", type=float, default=0.35)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    docs = list(read_documents(args.input))
    crawler = VnExpressCrawler([], delay=args.delay)
    failures = []
    updated = 0
    for doc in docs:
        try:
            fresh = parse_article(crawler._get(str(doc["url"])), str(doc["url"]))
            if fresh is None:
                failures.append(str(doc["url"]))
                continue
            doc["images"] = [image.to_dict() for image in (fresh.images or [])]
            updated += 1
        except requests.RequestException:
            failures.append(str(doc["url"]))
            logging.exception("Backfill failed: %s", doc["url"])
    manifest = write_corpus(docs, args.input, args.output)
    print(f"Updated {updated} articles; {manifest['images']} images; {len(failures)} failed")
    if failures:
        failure_path = args.output.with_name("image_backfill_failures.txt")
        failure_path.write_text("\n".join(failures) + "\n", encoding="utf-8")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
