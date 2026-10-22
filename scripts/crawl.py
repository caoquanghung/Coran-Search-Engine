#!/usr/bin/env python3
"""CLI thu thập dataset."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import VnExpressCrawler  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl các bài VnExpress nhiều bình luận nhất")
    parser.add_argument("--seeds", type=Path, default=Path("data/seeds.txt"))
    parser.add_argument("--output", type=Path, default=Path("data/documents.jsonl"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--pages", type=int, default=5, help="Số trang duyệt cho mỗi seed")
    parser.add_argument("--candidates", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0.35)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.seeds.exists():
        raise SystemExit(f"Không tìm thấy file seed: {args.seeds}")
    seeds = args.seeds.read_text(encoding="utf-8").splitlines()
    crawler = VnExpressCrawler(
        seeds,
        max_documents=args.limit,
        pages_per_seed=args.pages,
        candidate_limit=args.candidates,
        delay=args.delay,
    )
    articles = crawler.crawl()
    count = crawler.write_jsonl(articles, args.output)
    print(f"Đã lưu {count} bài vào {args.output}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
