#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()

    image = Image.open(args.source).convert("RGBA")
    if image.width != image.height:
        raise RuntimeError(f"product icon must be square, got {image.size}")

    # Preserve the approved artwork exactly; only resize it for native icon sets.
    image = image.resize((args.size, args.size), Image.Resampling.LANCZOS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, "PNG", optimize=True)
    print(f"prepared exact product icon: {args.output} ({args.size}x{args.size})")


if __name__ == "__main__":
    main()
