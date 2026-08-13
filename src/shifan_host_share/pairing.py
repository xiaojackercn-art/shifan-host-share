from __future__ import annotations

import hashlib

from .config import normalize_pair_code

DIRECTION_TAGS = {
    "left": "L",
    "right": "R",
    "up": "U",
    "down": "D",
}


def pairing_token(pair_code: str) -> str:
    raw = normalize_pair_code(pair_code)
    if len(raw) != 12:
        raise ValueError("配对码必须是完整的 12 位")
    return hashlib.sha256(("SHIFANAI-DESKFLOW-V1|" + raw).encode("utf-8")).hexdigest()[:12].upper()


def client_screen_name(pair_code: str, direction: str) -> str:
    if direction not in DIRECTION_TAGS:
        raise ValueError("屏幕方向无效")
    return f"SF-{DIRECTION_TAGS[direction]}-{pairing_token(pair_code)}"


def all_client_screen_names(pair_code: str) -> dict[str, str]:
    return {direction: client_screen_name(pair_code, direction) for direction in DIRECTION_TAGS}
