#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/icon-source.png")
    source = Path(__file__).with_name("icon_fallback.png")
    if not source.exists():
        raise RuntimeError(f"embedded product icon is missing: {source}")

    # This PNG is committed from the exact icon shown in the approved v0.9 UI.
    # Never download a replacement from a third-party image host during builds.
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    print(f"materialized specified product icon: {output}")


if __name__ == "__main__":
    main()
