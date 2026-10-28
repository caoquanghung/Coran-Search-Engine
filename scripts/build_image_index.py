#!/usr/bin/env python3
"""Build the persistent image description index."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.image_indexer import build_image_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/images.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("image_index"))
    args = parser.parse_args()
    count = build_image_index(args.input, args.index)
    print(f"Indexed {count} searchable images into {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
