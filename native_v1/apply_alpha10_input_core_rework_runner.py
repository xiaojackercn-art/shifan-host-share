#!/usr/bin/env python3
from __future__ import annotations

import sys

import apply_alpha10_input_core_rework as overlay


def replace_first(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count < 1:
        raise RuntimeError(f"{label}: expected at least one match, found 0")
    return text.replace(old, new, 1)


overlay.replace_once = replace_first

if __name__ == "__main__":
    overlay.main()
