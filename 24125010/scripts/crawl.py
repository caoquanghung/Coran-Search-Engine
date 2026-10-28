#!/usr/bin/env python3
"""CLI thu thập dataset."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import VnExpressCrawler  # noqa: E402
from crawler.watch import CrawlLoop  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl các bài VnExpress nhiều bình luận nhất")
    parser.add_argument("--seeds", type=Path, default=Path("data/seeds.txt"))
    parser.add_argument("--output", type=Path, default=Path("data/documents.jsonl"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--pages", type=int, default=5, help="Số trang duyệt cho mỗi seed")
    parser.add_argument("--candidates", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--images-output", type=Path, default=Path("data/images.jsonl"))
    parser.add_argument("--watch", action="store_true", help="Discover and index only new content every interval")
    parser.add_argument("--once", action="store_true", help="Run one incremental pass and exit")
    parser.add_argument("--interval", type=float, default=900)
    parser.add_argument("--state", type=Path, default=Path("data/crawl_state.sqlite"))
    parser.add_argument("--article-index", type=Path, default=Path("index"))
    parser.add_argument("--image-index", type=Path, default=Path("image_index"))
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
    if args.watch or args.once:
        loop = CrawlLoop(crawler, documents_path=args.output, images_path=args.images_output,
                         article_index=args.article_index, image_index=args.image_index,
                         state_path=args.state)
        if args.once:
            print(loop.run_once())
        else:
            loop.run_forever(args.interval)
        return 0
    articles = crawler.crawl()
    manifest = crawler.write_corpus(articles, args.output, args.images_output)
    print(f"Đã lưu {manifest['documents']} bài và {manifest['images']} ảnh")
    return 0 if manifest["documents"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
