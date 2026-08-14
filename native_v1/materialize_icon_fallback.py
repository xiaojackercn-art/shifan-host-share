#!/usr/bin/env python3
from __future__ import annotations

import base64
import sys
from pathlib import Path


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/icon-source.png")
    raw = Path(__file__).with_name("icon_fallback.b64").read_text(encoding="utf-8").strip()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(raw, validate=True))
    print(output)


if __name__ == "__main__":
    main()
