#!/usr/bin/env python3
"""Prepare E5 and build/reuse both persistent cosine vector indexes."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.vector_index import DEFAULT_MODEL_DIR, build_vector_indexes, download_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=Path("data/documents.jsonl"))
    parser.add_argument("--images", type=Path, default=Path("data/images.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("vector_index"))
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--download-model", action="store_true", help="Download and pin the model for offline inference")
    args = parser.parse_args()
    if args.download_model:
        print(download_model(args.model_dir), flush=True)
    manifest = build_vector_indexes(args.documents, args.images, args.index, model_dir=args.model_dir, progress=True)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
