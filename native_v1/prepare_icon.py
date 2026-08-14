#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--radius", type=float, default=0.18, help="corner radius as fraction of size")
    args = parser.parse_args()

    image = Image.open(args.source).convert("RGBA")
    canvas = Image.new("RGBA", (args.size, args.size), (0, 0, 0, 0))

    # Preserve the full source artwork while giving it breathing room so taskbar,
    # Dock and installer renderers do not crop the mark.
    inset = round(args.size * 0.055)
    target = args.size - inset * 2
    image.thumbnail((target, target), Image.Resampling.LANCZOS)
    x = (args.size - image.width) // 2
    y = (args.size - image.height) // 2
    canvas.alpha_composite(image, (x, y))

    radius = round(args.size * args.radius)
    mask = Image.new("L", (args.size, args.size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, args.size - 1, args.size - 1), radius=radius, fill=255)
    alpha = canvas.getchannel("A")
    canvas.putalpha(ImageChops.multiply(alpha, mask))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, "PNG")
    print(args.output)


if __name__ == "__main__":
    main()
