#!/usr/bin/env python3
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/AI.png")
    source = Path(__file__).with_name("icon_fallback.b64")
    if not source.exists():
        raise RuntimeError(f"embedded icon source is missing: {source}")

    # The embedded source is the user-specified 视饭AI:主机共享 icon.  Keep the
    # build independent from third-party image hosts so an expired URL can never
    # silently fall back to a generic icon again.
    raw = re.sub(r"\s+", "", source.read_text(encoding="utf-8"))
    raw += "=" * ((4 - len(raw) % 4) % 4)
    data = base64.b64decode(raw, validate=False)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("embedded product icon is not a PNG")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(f"materialized product icon: {output}")


if __name__ == "__main__":
    main()
