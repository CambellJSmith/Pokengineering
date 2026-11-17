#!/usr/bin/env python3
"""Decompress the BLZ-compressed resident ARM9 image into its runtime layout.

Guardian Signs' arm9.bin is itself Nitro code-compressed: the module params
(found by scanning for the magic pair 0xDEC00621, 0x2106C0DE; they sit at
file+0xBA0 in B3RE) contain compressed_static_end = 0x02066C94. Bytes up to that file
offset are a BLZ stream (with an uncompressed secure-area prefix); bytes after
it are autoload (ITCM/DTCM) payloads and are left untouched.

This is why live ARM9 RAM did not match arm9.bin during earlier GDB work: the
stored file is compressed. After decompression, addresses map 1:1 onto RAM
from 0x02000000 up to the static end (0x020AA898).

Output: work/code_analysis/runtime/arm9_decompressed.bin
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import blz  # noqa: E402

ARM9_BASE = 0x02000000
MAGIC = struct.pack("<II", 0xDEC00621, 0x2106C0DE)


def main() -> int:
    src = ROOT / "arm9.bin"
    out = ROOT / "work" / "code_analysis" / "runtime" / "arm9_decompressed.bin"
    data = src.read_bytes()
    magic = data.find(MAGIC)
    if magic < 0:
        print("module params magic not found", file=sys.stderr)
        return 1
    base = magic - 0x1C
    params = struct.unpack_from("<7I", data, base)
    autoload_list, autoload_list_end, autoload_start, bss_start, bss_end, compressed_end, _sdk = params
    print(f"module params @ file+0x{base:X}")
    print(f"  autoload list          0x{autoload_list:08X}-0x{autoload_list_end:08X}")
    print(f"  autoload_start         0x{autoload_start:08X}")
    print(f"  static bss             0x{bss_start:08X}-0x{bss_end:08X}")
    print(f"  compressed_static_end  0x{compressed_end:08X}")
    if compressed_end == 0:
        decoded = data
    else:
        decoded = blz.decompress(data[: compressed_end - ARM9_BASE])
    end = ARM9_BASE + len(decoded)
    print(f"  decoded static image   0x{ARM9_BASE:08X}-0x{end:08X} ({len(decoded)} bytes)")
    if end != autoload_list_end:
        print(f"WARNING: decoded end != autoload list end (0x{autoload_list_end:08X})", file=sys.stderr)
    # sanity: script VM interpreter prologue (push {r3-r11,lr})
    if decoded[0x65A80:0x65A84] != bytes.fromhex("f84f2de9"):
        print("WARNING: VM interpreter prologue not found at 0x02065A80", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(decoded)
    print(f"sha256 {hashlib.sha256(decoded).hexdigest()}")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
