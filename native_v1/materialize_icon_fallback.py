#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/icon-source.png")
    source = Path(__file__).with_name("icon_fallback.png")
    if not source.exists():
        raise RuntimeError(f"embedded icon fallback is missing: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    print(output)


if __name__ == "__main__":
    main()
