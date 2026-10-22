#!/usr/bin/env python3
"""CLI xây Whoosh index từ JSONL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import build_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Xây Whoosh index")
    parser.add_argument("--input", type=Path, default=Path("data/documents.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("index"))
    parser.add_argument("--update", action="store_true", help="Cập nhật thay vì tạo lại index")
    args = parser.parse_args()
    count = build_index(args.input, args.index, recreate=not args.update)
    print(f"Đã index {count} tài liệu vào {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
