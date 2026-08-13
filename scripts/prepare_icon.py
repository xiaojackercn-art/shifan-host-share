from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_URL = "https://i.ibb.co/nMzmgBR7/AI.png"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)


def download() -> Image.Image:
    req = urllib.request.Request(ICON_URL, headers={"User-Agent": "Mozilla/5.0 ShifanAI-HostShare-Builder"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.width < 64 or img.height < 64:
        raise ValueError("下载的图标尺寸过小")
    return img


def fallback() -> Image.Image:
    img = Image.new("RGBA", (1024, 1024), (35, 74, 180, 255))
    draw = ImageDraw.Draw(img)
    text = "AI"
    try:
        font = ImageFont.truetype("arial.ttf", 360)
    except Exception:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), text, font=font)
    x = (1024 - (box[2] - box[0])) // 2
    y = (1024 - (box[3] - box[1])) // 2
    draw.text((x, y), text, fill="white", font=font)
    return img


def main() -> None:
    try:
        img = download()
        print(f"Downloaded icon from {ICON_URL}")
    except Exception as exc:
        print(f"WARNING: icon download failed ({exc}); using fallback icon", file=sys.stderr)
        img = fallback()

    square = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    copy = img.copy()
    copy.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    square.alpha_composite(copy, ((1024 - copy.width) // 2, (1024 - copy.height) // 2))
    square.save(ASSETS / "AI.png")
    square.save(ASSETS / "AI.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    try:
        square.save(ASSETS / "AI.icns", format="ICNS")
    except Exception as exc:
        print(f"WARNING: ICNS conversion failed: {exc}", file=sys.stderr)
    print("Icon assets prepared")


if __name__ == "__main__":
    main()
