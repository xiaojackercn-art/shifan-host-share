#!/usr/bin/env python3
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/icon-source.png")
    raw = Path(__file__).with_name("icon_fallback.b64").read_text(encoding="utf-8")
    raw = re.sub(r"\s+", "", raw)
    raw += "=" * ((4 - len(raw) % 4) % 4)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(raw, validate=False)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("embedded icon fallback is not a PNG")
    output.write_bytes(data)
    print(output)


if __name__ == "__main__":
    main()
