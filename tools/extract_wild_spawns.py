#!/usr/bin/env python3
"""Extract free-roaming wild Pokemon placements from every map placement package.

Format (recovered from ARM9, see docs/scene_system.md section 6):

  data_game_us.acf entry  NARC  (mounted as "MPK", ARM9 0x0203F8F4)
      file "MPIF"  20-byte map info
      file "LYR\\0" + NARC  ("MLY")
          file 0: NARC ("MLG")       one file per layer:
              u32 layer_type, u32 count, count * packed record
  layer types (CMapPlacementDataLayer* classes, vfunc0 returns the type):
      1 Enemy  2 Npc  3 Object  4 EventRect  5 StartPoint  6 RunawayPoint
      8 FloorAttribute  9 WallAttribute  10 Shadow
  Enemy records: field descriptor ARM9 0x0209C370 (14 fields) unpacked by
  0x0203F5B8 into 0x1E-byte runtime records. On disk (26 bytes):
      s16 x, s16 z, u8 f2, u8 f3, u16 dex, u16 f5, u16 f8..f15
  At spawn (ov2 0x020D6F2C / 0x020D741C) record.dex becomes
  CFieldWildPokemon+0x85C, which wild contact passes to CaptureSetup_Add.

Map names: entry 2482.MPPS (resource 0x9B2, loaded into 0x020B7954) has 0x80-byte
records; ARM9 0x0203F4A8 copies rec[0] (set selector), rec[1] (map number),
rec[2] (sub-map) and rec+8 (u16 placement index). ov2 0x020D6460 loads placement
resource  rec+8 + (rec[0] ? 0x1E1B : 0x1CAD)  ->  map "mNNN_SS". Several records
can name the same map (story-progress variants).

Requires work/game_acf/archive (bash tools/extract_game_data.sh).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "work" / "game_acf" / "archive"
NAMES = ROOT / "work" / "localization" / "json" / "0268.json"
LAYER_NAMES = {1: "Enemy", 2: "Npc", 3: "Object", 4: "EventRect", 5: "StartPoint",
               6: "RunawayPoint", 8: "FloorAttribute", 9: "WallAttribute", 10: "Shadow"}
ENEMY = struct.Struct("<hhBBHH8H")


def narc_files(d: bytes) -> list[bytes]:
    if d[:4] != b"NARC":
        raise ValueError("not a NARC")
    off = struct.unpack_from("<H", d, 0xC)[0]
    fat, fimg = [], None
    while off + 8 <= len(d):
        magic, size = d[off:off + 4], struct.unpack_from("<I", d, off + 4)[0]
        if magic == b"BTAF":
            n = struct.unpack_from("<H", d, off + 8)[0]
            fat = [struct.unpack_from("<II", d, off + 12 + 8 * i) for i in range(n)]
        elif magic == b"GMIF":
            fimg = off + 8
        if size == 0:
            break
        off += size
    return [d[fimg + s:fimg + e] for s, e in fat]


def layers(package: bytes):
    files = narc_files(package)
    mpif = next((f for f in files if f[:4] == b"MPIF"), b"")
    lyr = next((f for f in files if f[:4] == b"LYR\0"), None)
    if lyr is None:
        return mpif, []
    mlg = narc_files(narc_files(lyr[4:])[0])
    return mpif, [(struct.unpack_from("<I", L, 0)[0], L) for L in mlg]


def map_index():
    """placement ACF entry -> list of (mpps_record, 'mNNN_SS')"""
    path = ARCHIVE / "2482.MPPS"
    out = collections.defaultdict(list)
    if not path.exists():
        return out
    d = path.read_bytes()
    rs, n = struct.unpack_from("<II", d, 4)
    for i in range(n):
        r = d[0x10 + rs * i:0x10 + rs * (i + 1)]
        idx = struct.unpack_from("<H", r, 8)[0]
        if idx == 0xFFFF:
            continue
        entry = idx + (0x1E1B if r[0] else 0x1CAD)
        out[entry].append((i, f"m{r[1]:03d}_{r[2]:02d}"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "capture" / "generated")
    args = ap.parse_args()
    names = {}
    if NAMES.exists():
        names = {int(k): v for k, v in json.loads(NAMES.read_text()).items() if k.isdigit()}

    maps = map_index()
    rows, packages, layer_counts = [], 0, collections.Counter()
    for path in sorted(ARCHIVE.glob("*.NARC")):
        data = path.read_bytes()
        try:
            mpif, lays = layers(data)
        except Exception:
            continue
        if not lays:
            continue
        packages += 1
        w, h = struct.unpack_from("<II", mpif, 4) if len(mpif) >= 12 else (0, 0)
        for ltype, L in lays:
            layer_counts[LAYER_NAMES.get(ltype, f"type{ltype}")] += 1
            if ltype != 1:
                continue
            count = struct.unpack_from("<I", L, 4)[0]
            for i in range(count):
                r = ENEMY.unpack_from(L, 8 + ENEMY.size * i)
                rows.append({
                    "acf_entry": int(path.stem),
                    "map": " ".join(sorted({m for _, m in maps.get(int(path.stem), [])})),
                    "mpps_records": " ".join(str(i) for i, _ in maps.get(int(path.stem), [])),
                    "map_w": w, "map_h": h, "index": i,
                    "x": r[0], "z": r[1], "f2": r[2], "f3": r[3],
                    "dex": r[4], "name": names.get(r[4], ""), "f5": r[5],
                    **{f"f{8 + k}": r[6 + k] for k in range(8)},
                })

    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / "wild_spawns.csv"
    with open(out, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    species = collections.Counter(r["dex"] for r in rows)
    print(f"placement packages: {packages}")
    print(f"layer counts: {dict(layer_counts)}")
    print(f"wild placements: {len(rows)} in {len({r['acf_entry'] for r in rows})} packages")
    print(f"distinct Ranger Pokemon IDs: {len(species)} ({sum(1 for k in species if k > 493)} above 493 = Ranger-specific forms)")
    named = sum(1 for r in rows if r["map"])
    print(f"placements with a resolved map name: {named}/{len(rows)}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
