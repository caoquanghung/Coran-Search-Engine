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
from crawler.corpus import write_corpus  # noqa: E402
from crawler.parser import parse_article  # noqa: E402
from engine.indexer import read_documents, build_index  # noqa: E402
from engine.image_indexer import build_image_index  # noqa: E402
from engine.vector_index import build_vector_indexes  # noqa: E402
import requests  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl and index up to 1000 VnExpress article candidates")
    parser.add_argument("--seeds", type=Path, default=Path("data/seeds.txt"))
    parser.add_argument("--output", type=Path, default=Path("data/documents.jsonl"))
    parser.add_argument("--limit", type=int, default=1000, help="Target article count for a bootstrap or expansion")
    parser.add_argument("--pages", type=int, default=5, help="Số trang duyệt cho mỗi seed")
    parser.add_argument("--candidates", type=int, default=1500, help="Discovery budget; exceeds --limit to allow invalid/duplicate pages")
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--images-output", type=Path, default=Path("data/images.jsonl"))
    parser.add_argument("--watch", action="store_true", help="Discover and index only new content every interval")
    parser.add_argument("--once", action="store_true", help="Run one incremental pass and exit")
    parser.add_argument("--expand", action="store_true", help="Keep existing articles and add unseen candidates up to --limit, then rebuild indexes")
    parser.add_argument("--interval", type=float, default=900)
    parser.add_argument("--state", type=Path, default=Path("data/crawl_state.sqlite"))
    parser.add_argument("--article-index", type=Path, default=Path("index"))
    parser.add_argument("--image-index", type=Path, default=Path("image_index"))
    parser.add_argument("--vector-index", type=Path, help="Defaults to vector_index beside the article index")
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
                         state_path=args.state, vector_dir=args.vector_index)
        if args.once:
            print(loop.run_once())
        else:
            loop.run_forever(args.interval)
        return 0
    if args.expand:
        documents = list(read_documents(args.output)) if args.output.exists() else []
        seen_urls = {crawler._clean_url(str(doc.get("url") or "")) for doc in documents}
        seen_ids = {str(doc.get("id")) for doc in documents}
        if len(documents) < args.limit:
            candidates = crawler.discover()
            for position, url in enumerate(candidates, start=1):
                if len(documents) >= args.limit:
                    break
                if crawler._clean_url(url) in seen_urls:
                    continue
                try:
                    article = parse_article(crawler._get(url), url)
                except requests.RequestException as exc:
                    logging.warning("Could not fetch %s: %s", url, exc)
                    continue
                if article is None or article.id in seen_ids:
                    continue
                documents.append(article.to_dict())
                seen_urls.add(crawler._clean_url(url))
                seen_urls.add(crawler._clean_url(article.url))
                seen_ids.add(article.id)
                logging.info("[%d/%d] Stored %d/%d articles", position, len(candidates), len(documents), args.limit)
        if not documents:
            return 1
        manifest = write_corpus(documents, args.output, args.images_output)
        article_count = build_index(args.output, args.article_index)
        image_count = build_image_index(args.images_output, args.image_index)
        vector_dir = args.vector_index or args.article_index.parent / "vector_index"
        if (vector_dir / "manifest.json").exists():
            build_vector_indexes(args.output, args.images_output, vector_dir)
        print(f"Stored {manifest['documents']} articles and {manifest['images']} images; indexed {article_count} articles and {image_count} searchable images")
        return 0
    articles = crawler.crawl()
    manifest = crawler.write_corpus(articles, args.output, args.images_output)
    print(f"Đã lưu {manifest['documents']} bài và {manifest['images']} ảnh")
    return 0 if manifest["documents"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
