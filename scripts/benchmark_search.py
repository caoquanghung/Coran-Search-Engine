#!/usr/bin/env python3
"""Measure model startup, new-query retrieval, and cached UI interactions locally."""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.hybrid_searcher import HybridImageSearchService, HybridSearchService  # noqa: E402
from engine.vector_index import DEFAULT_MODEL_DIR, get_encoder  # noqa: E402


def timed(call):
    started = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - started) * 1000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", help="Repeat for several new queries")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--index", type=Path, default=Path("index"))
    parser.add_argument("--image-index", type=Path, default=Path("image_index"))
    parser.add_argument("--vectors", type=Path, default=Path("vector_index"))
    args = parser.parse_args()
    queries = args.query or ["nước dâng làm ngập đường phố", "ô tô chạy bằng pin", "chi phí khám chữa bệnh"]
    encoder, load_ms = timed(lambda: get_encoder(args.model_dir))
    _, first_embedding_ms = timed(lambda: encoder.query_vector("khởi động tìm kiếm"))
    articles = HybridSearchService(args.index, args.vectors, model_dir=args.model_dir)
    images = HybridImageSearchService(args.image_index, args.vectors, model_dir=args.model_dir)
    report = {"device": str(encoder.model.device), "cpu_threads": encoder._torch.get_num_threads(),
              "model_load_ms": round(load_ms, 2), "first_embedding_ms": round(first_embedding_ms, 2), "queries": []}
    for query in queries:
        _, embedding_ms = timed(lambda: encoder.query_vector(query))
        _, retrieval_ms = timed(lambda: (articles.search(query), images.search(query)))
        cached = [timed(lambda: (articles.search(query), images.search(query)))[1] for _ in range(max(1, args.repeat))]
        _, navigation_ms = timed(lambda: (articles.search(query, page=2, sort_by="comments"), images.search(query)))
        report["queries"].append({"query": query, "embedding_ms": round(embedding_ms, 2),
                                  "retrieval_ms": round(retrieval_ms, 2),
                                  "cached_median_ms": round(statistics.median(cached), 3),
                                  "sort_and_page_ms": round(navigation_ms, 3)})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
