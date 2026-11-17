#!/usr/bin/env python3
"""Ranger Pokemon ID -> National Dex number -> English name.

Guardian Signs identifies every capturable Pokemon (including per-encounter
variants) by a "Ranger ID" 0..769. The same index is used by:
  2480.FPKD  field Pokemon data, 0x58 x 770, resource 0x9B0 -> 0x020BD37C
  6846.CPOK  capture Pokemon data, 0x50 x 770, resource 0x1ABE -> 0x020B7C78
             (+0x0C model index: sprite set = ACF entry 0x6B7 + model)
FPKD record +0x2E (u16) is the National Dex number (verified against rendered
sprites: 1 Bulbasaur, 13 Pidgey, 18 Pikachu, 21 Sandslash, 22 Vulpix, ...).
Dex values 900/901 (IDs 381-384) are special non-Pokemon targets without a
Pokemon sprite. Names come from localization file 0268 (Dex-indexed).

Requires work/game_acf/archive (tools/extract_game_data.sh); names need
work/localization (tools/extract_localization.sh).
"""
from __future__ import annotations

import json
import struct
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FPKD = ROOT / "work" / "game_acf" / "archive" / "2480.FPKD"
NAMES = ROOT / "work" / "localization" / "json" / "0268.json"
DEX_OFFSET = 0x2E


@lru_cache(maxsize=None)
def _tables():
    dex = []
    if FPKD.exists():
        d = FPKD.read_bytes()
        size, count = struct.unpack_from("<II", d, 4)
        dex = [struct.unpack_from("<H", d, 0x10 + size * i + DEX_OFFSET)[0] for i in range(count)]
    names = {}
    if NAMES.exists():
        names = {int(k): v for k, v in json.loads(NAMES.read_text()).items() if k.isdigit()}
    return dex, names


def dex_of(rid: int) -> int | None:
    dex, _ = _tables()
    return dex[rid] if 0 <= rid < len(dex) else None


def name_of(rid: int) -> str:
    dex, names = _tables()
    n = dex_of(rid)
    if n is None:
        return ""
    if n >= 900:
        return f"special#{n}"
    return names.get(n, f"dex{n}")


def available() -> bool:
    return bool(_tables()[0])


if __name__ == "__main__":
    for a in sys.argv[1:] or ["13", "21", "243"]:
        r = int(a, 0)
        print(r, dex_of(r), name_of(r))
