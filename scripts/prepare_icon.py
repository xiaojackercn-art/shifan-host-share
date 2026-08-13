from __future__ import annotations

import io
import shutil
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ICON_URL = "https://i.ibb.co/nMzmgBR7/AI.png"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
WEB = ROOT / "src" / "shifan_host_share" / "web"


def download_with_retry() -> Image.Image:
    last = None
    for attempt in range(1, 5):
        try:
            req = urllib.request.Request(
                ICON_URL,
                headers={
                    "User-Agent": "Mozilla/5.0 ShifanAI-HostShare/0.4 Builder",
                    "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            if img.width < 64 or img.height < 64:
                raise ValueError(f"图标尺寸异常 {img.size}")
            return img
        except Exception as exc:
            last = exc
            print(f"Icon download attempt {attempt}/4 failed: {exc}")
            time.sleep(attempt * 3)
    raise RuntimeError(f"无法下载用户指定图标 {ICON_URL}: {last}")


def rounded_icon(img: Image.Image) -> Image.Image:
    # Keep the user's exact artwork, but remove the hard square corners. The
    # transparent outer margin also prevents Windows taskbar/installer icons
    # from looking like a white square tile.
    side = 1024
    inset = 38
    inner_side = side - inset * 2
    art = img.copy()
    art.thumbnail((inner_side, inner_side), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    x = (side - art.width) // 2
    y = (side - art.height) // 2
    tile = Image.new("RGBA", (art.width, art.height), (0, 0, 0, 0))
    tile.alpha_composite(art)
    radius = max(28, int(min(art.size) * 0.18))
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, art.width - 1, art.height - 1), radius=radius, fill=255)
    tile.putalpha(Image.composite(tile.getchannel("A"), Image.new("L", art.size, 0), mask))
    canvas.alpha_composite(tile, (x, y))
    return canvas


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    img = download_with_retry()
    print(f"Using exact user icon with rounded transparent corners: {ICON_URL} ({img.width}x{img.height})")
    icon = rounded_icon(img)
    icon.save(ASSETS / "AI.png")
    icon.save(ASSETS / "AI.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(ASSETS / "AI.icns", format="ICNS")
    if WEB.exists():
        shutil.copy2(ASSETS / "AI.png", WEB / "AI.png")


if __name__ == "__main__":
    main()
