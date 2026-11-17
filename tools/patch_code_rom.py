#!/usr/bin/env python3
"""Apply RAM-addressed code patches to ARM9 and/or ARM9 overlays of a built ROM.

Guardian Signs ships ARM9 and all 34 overlays BLZ-compressed. Instead of
re-compressing, this tool stores every patched executable UNCOMPRESSED:

  overlay N : decode its FAT payload, patch, append it to the ROM (0x200
              aligned), point FAT[file_id] at it, and clear the overlay
              table's compressed flag/size word (entry +0x1C = 0).
  arm9      : decode up to compressed_static_end, patch, set the module-params
              compressed_static_end to 0, append it plus the original 12-byte
              Nitro footer, and update header ARM9 offset (0x20) / size (0x2C).

The header used-ROM size and CRC are then recomputed. Patch addresses are RAM
addresses exactly as seen in work/code_analysis (decompressed images).

Patch file (JSON):
  [
    {"target": "ov003", "addr": "0x020D0520", "hex": "0000a0e3", "expect": "04e02de5",
     "comment": "optional"},
    {"target": "arm9",  "addr": "0x0203DEE0", "hex": "..."}
  ]
"expect" (optional) must match the original bytes or the patch is refused.

Usage:
  bash tools/build_debug_rom.sh                      # base ROM
  python3 tools/patch_code_rom.py work/debug/guardian_signs_debug.nds \\
      --patches my_patches.json --output work/debug/patched.nds
  python3 tools/patch_code_rom.py IN.nds --decompress ov003 arm9 --output OUT.nds
      (no patches: just store those targets uncompressed; useful as a smoke test)
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blz  # noqa: E402

ALIGN = 0x200
ARM9_BASE = 0x02000000
PARAMS_MAGIC = struct.pack("<II", 0xDEC00621, 0x2106C0DE)


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for v in data:
        crc ^= v
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def append_aligned(rom: bytearray, payload: bytes) -> int:
    pad = (-len(rom)) % ALIGN
    rom.extend(b"\xFF" * pad)
    pos = len(rom)
    rom.extend(payload)
    return pos


def load_patches(path: Path | None):
    if not path:
        return []
    items = json.loads(path.read_text())
    out = []
    for it in items:
        out.append({
            "target": it["target"].lower(),
            "addr": int(str(it["addr"]), 0),
            "data": bytes.fromhex(it["hex"].replace(" ", "")),
            "expect": bytes.fromhex(it["expect"].replace(" ", "")) if it.get("expect") else None,
            "comment": it.get("comment", ""),
        })
    return out


def apply(image: bytearray, base: int, patches, name: str):
    for p in patches:
        off = p["addr"] - base
        if not (0 <= off and off + len(p["data"]) <= len(image)):
            raise SystemExit(f"{name}: patch at 0x{p['addr']:08X} is outside the image")
        if p["expect"] is not None and bytes(image[off:off + len(p["expect"])]) != p["expect"]:
            got = bytes(image[off:off + len(p["expect"])]).hex()
            raise SystemExit(f"{name}: expected {p['expect'].hex()} at 0x{p['addr']:08X}, found {got}")
        image[off:off + len(p["data"])] = p["data"]
        print(f"  patched {name} 0x{p['addr']:08X} ({len(p['data'])} bytes) {p['comment']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rom", type=Path)
    ap.add_argument("--patches", type=Path)
    ap.add_argument("--decompress", nargs="*", default=[], help="targets to store uncompressed even without patches (arm9, ov003, ...)")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    rom = bytearray(args.rom.read_bytes())
    patches = load_patches(args.patches)
    targets = sorted({p["target"] for p in patches} | {t.lower() for t in args.decompress})
    fat_off, ovt_off, ovt_size = u32(rom, 0x48), u32(rom, 0x50), u32(rom, 0x54)

    for tgt in targets:
        tp = [p for p in patches if p["target"] == tgt]
        if tgt == "arm9":
            off, size = u32(rom, 0x20), u32(rom, 0x2C)
            raw = bytes(rom[off:off + size])
            footer = bytes(rom[off + size:off + size + 12])
            m = raw.find(PARAMS_MAGIC)
            if m < 0:
                raise SystemExit("ARM9 module params not found")
            params = m - 0x1C
            comp_end = u32(raw, params + 0x14)
            image = bytearray(blz.decompress(raw) if comp_end else raw)
            struct.pack_into("<I", image, params + 0x14, 0)          # compressed_static_end = 0
            apply(image, ARM9_BASE, tp, "arm9")
            if footer[:4] != struct.pack("<I", 0xDEC00621):
                footer = b""
            pos = append_aligned(rom, bytes(image) + footer)
            struct.pack_into("<I", rom, 0x20, pos)
            struct.pack_into("<I", rom, 0x2C, len(image))
            print(f"arm9: {size:#x} compressed -> {len(image):#x} uncompressed at ROM {pos:#x}")
            continue
        if not tgt.startswith("ov"):
            raise SystemExit(f"unknown target {tgt}")
        ov = int(tgt[2:])
        if ov * 32 >= ovt_size:
            raise SystemExit(f"overlay {ov} not in table")
        e = ovt_off + ov * 32
        ov_id, ram, ram_size, bss, si0, si1, fid, comp = struct.unpack_from("<8I", rom, e)
        start, end = struct.unpack_from("<II", rom, fat_off + 8 * fid)
        raw = bytes(rom[start:end])
        image = bytearray(blz.decompress(raw) if (comp >> 24) & 1 else raw)
        if len(image) != ram_size:
            raise SystemExit(f"overlay {ov}: decoded {len(image):#x} != table size {ram_size:#x}")
        apply(image, ram, tp, tgt)
        pos = append_aligned(rom, bytes(image))
        struct.pack_into("<II", rom, fat_off + 8 * fid, pos, pos + len(image))
        struct.pack_into("<I", rom, e + 0x1C, 0)                         # not compressed
        print(f"{tgt}: {end - start:#x} compressed -> {len(image):#x} uncompressed at ROM {pos:#x}")

    struct.pack_into("<I", rom, 0x80, len(rom))
    struct.pack_into("<H", rom, 0x15E, crc16(rom[:0x15E]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rom)
    print(f"wrote {args.output} ({len(rom)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
