#!/usr/bin/env python3
"""Recover CodeWarrior/Itanium-style RTTI class hierarchy and vtables.

Scans the decompressed resident ARM9 image and every decoded ARM9 overlay
(each at its own load address, never merged) for type_info objects:

    +0 type_info-class vptr   (one of the __class_type_info vtables in ARM9)
    +4 char* mangled name     (e.g. "13CCaptureScene")
    +8 base type_info*        (single-inheritance __si_class_type_info only)

and vtables, which are laid out as  [offset_to_top=0][type_info*][fn0][fn1]...
The object vptr points at fn0 (vtable+8).

Requires work/code_analysis (bash tools/analyze_game_code.sh) and
work/code_analysis/runtime/arm9_decompressed.bin (tools/decompress_arm9.py).
"""
from __future__ import annotations

import csv
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CA = ROOT / "work" / "code_analysis"
NAME_RE = re.compile(rb"^[0-9]{1,3}[A-Za-z_][A-Za-z0-9_]*$")


def load_images():
    imgs = {"arm9": (0x02000000, (CA / "runtime" / "arm9_decompressed.bin").read_bytes())}
    with open(CA / "overlays.csv") as fh:
        for row in csv.DictReader(fh):
            path = CA / row["decoded_path"]
            if path.exists():
                imgs[f"ov{int(row['overlay_id']):03d}"] = (int(row["ram_address"], 16), path.read_bytes())
    return imgs


def scan(imgs):
    arm9_base, arm9 = imgs["arm9"]
    results = []
    for img, (base, data) in imgs.items():
        # address resolver: own image first, then resident ARM9
        def read_str(addr):
            for b, d in ((base, data), (arm9_base, arm9)):
                if b <= addr < b + len(d):
                    raw = d[addr - b : addr - b + 128].split(b"\0", 1)[0]
                    return raw if NAME_RE.match(raw) else None
            return None

        tinfos = {}
        for off in range(0, len(data) - 8, 4):
            tv, name = struct.unpack_from("<II", data, off)
            if not (0x02000000 <= tv < 0x020B0000):
                continue
            s = read_str(name)
            if s is None:
                continue
            m = re.match(rb"^([0-9]+)(.*)$", s)
            if int(m.group(1)) != len(m.group(2)):
                continue
            base_ti = struct.unpack_from("<I", data, off + 8)[0] if off + 12 <= len(data) else 0
            tinfos[base + off] = (s[len(m.group(1)):].decode(), tv, base_ti)
        for addr, (name, tv, base_ti) in tinfos.items():
            results.append((img, addr, name, tv, base_ti))
    return results


def vtables(imgs, img, ti_addr):
    base, data = imgs[img]
    out = []
    p = struct.pack("<I", ti_addr)
    i = data.find(p)
    while i != -1:
        if i % 4 == 0 and i >= 4 and struct.unpack_from("<I", data, i - 4)[0] == 0:
            fns = []
            j = i + 4
            while j + 4 <= len(data):
                v = struct.unpack_from("<I", data, j)[0]
                if not (0x02000000 <= v < 0x02400000) or v & 3:
                    break
                fns.append(v)
                j += 4
            if fns:
                out.append((base + i + 4, fns))
        i = data.find(p, i + 1)
    return out


def main(argv):
    pattern = re.compile(argv[1]) if len(argv) > 1 else None
    imgs = load_images()
    rows = scan(imgs)
    by_addr = {(img, a): n for img, a, n, _, _ in rows}
    for img, addr, name, tv, base_ti in sorted(rows):
        if pattern and not pattern.search(name):
            continue
        parent = by_addr.get((img, base_ti)) or by_addr.get(("arm9", base_ti)) or ""
        print(f"{img} ti=0x{addr:08X} {name}" + (f" : {parent}" if parent else ""))
        for vp, fns in vtables(imgs, img, addr):
            print(f"    vptr=0x{vp:08X} [{len(fns)}] " + " ".join(f"{f:08X}" for f in fns[:24]))


if __name__ == "__main__":
    main(sys.argv)
