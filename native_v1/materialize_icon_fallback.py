#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/icon-source.png")
    scale = 2
    size = 1024 * scale
    margin = 66 * scale
    radius = 205 * scale

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = gradient.load()
    top = (29, 102, 224)
    bottom = (9, 52, 130)
    for y in range(size):
        t = y / max(1, size - 1)
        r = lerp(top[0], bottom[0], t)
        g = lerp(top[1], bottom[1], t)
        b = lerp(top[2], bottom[2], t)
        for x in range(size):
            side = abs((x / size) - 0.48)
            lift = max(0.0, 0.12 - side * 0.18)
            pixels[x, y] = (
                min(255, round(r + 20 * lift)),
                min(255, round(g + 32 * lift)),
                min(255, round(b + 38 * lift)),
                255,
            )

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=255,
    )
    image.alpha_composite(Image.composite(gradient, Image.new("RGBA", (size, size)), mask))

    draw = ImageDraw.Draw(image)
    white = (255, 255, 255, 245)
    soft = (204, 229, 255, 245)
    mint = (91, 231, 196, 255)
    shadow = (5, 29, 76, 70)

    # Subtle inset highlight for a polished native-icon finish.
    draw.rounded_rectangle(
        (margin + 2 * scale, margin + 2 * scale, size - margin - 2 * scale, size - margin - 2 * scale),
        radius=radius - 2 * scale,
        outline=(255, 255, 255, 48),
        width=3 * scale,
    )

    # Two displays, slightly offset to communicate one keyboard/mouse controlling
    # another machine. Shapes are intentionally simple so the icon remains clear
    # at 16px taskbar size.
    left = (210 * scale, 260 * scale, 565 * scale, 520 * scale)
    right = (468 * scale, 418 * scale, 805 * scale, 662 * scale)
    draw.rounded_rectangle(
        (left[0] + 12 * scale, left[1] + 16 * scale, left[2] + 12 * scale, left[3] + 16 * scale),
        radius=46 * scale,
        fill=shadow,
    )
    draw.rounded_rectangle(left, radius=46 * scale, outline=white, width=24 * scale)
    draw.line((388 * scale, 520 * scale, 388 * scale, 612 * scale), fill=white, width=22 * scale)
    draw.line((318 * scale, 612 * scale, 458 * scale, 612 * scale), fill=white, width=22 * scale)

    draw.rounded_rectangle(
        (right[0] + 10 * scale, right[1] + 14 * scale, right[2] + 10 * scale, right[3] + 14 * scale),
        radius=42 * scale,
        fill=shadow,
    )
    draw.rounded_rectangle(right, radius=42 * scale, outline=soft, width=22 * scale)
    draw.line((636 * scale, 662 * scale, 636 * scale, 740 * scale), fill=soft, width=20 * scale)
    draw.line((574 * scale, 740 * scale, 698 * scale, 740 * scale), fill=soft, width=20 * scale)

    # Connection arrow sits on top of both displays, remaining legible at small sizes.
    draw.line((414 * scale, 386 * scale, 590 * scale, 386 * scale), fill=mint, width=28 * scale)
    draw.line((546 * scale, 342 * scale, 594 * scale, 386 * scale), fill=mint, width=28 * scale)
    draw.line((546 * scale, 430 * scale, 594 * scale, 386 * scale), fill=mint, width=28 * scale)

    # Cursor marker — small enough not to clutter the symbol.
    cursor = [
        (688 * scale, 530 * scale),
        (688 * scale, 624 * scale),
        (716 * scale, 596 * scale),
        (745 * scale, 654 * scale),
        (775 * scale, 638 * scale),
        (746 * scale, 582 * scale),
        (785 * scale, 574 * scale),
    ]
    draw.polygon(cursor, fill=white)

    image = image.resize((1024, 1024), Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    print(f"generated high-resolution ShifanAI product icon: {output}")


if __name__ == "__main__":
    main()
