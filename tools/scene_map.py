#!/usr/bin/env python3
"""Recover the Guardian Signs scene table: scene ID -> overlay -> class.

Resident ARM9 (decompressed) contains two parallel switch statements over the
scene ID (0..0x39):

  0x0203D9BC  scene_overlay(sceneId)  -> calls 0x0203E714(overlayId, ...),
              which unloads the previous scene overlay (FS_UnloadOverlay
              0x0207DFD0) and loads the new one (FS_LoadOverlay 0x0207DF7C).
  0x0203DEE0  scene_create(sceneId)   -> operator new(size) (0x02001164),
              then the scene constructor at a fixed address inside the
              newly loaded overlay.

Each CScene subclass also returns its own ID from vtable slot 13
("mov r0,#id ; bx lr"), which this tool uses to name the scene.

Usage: python3 tools/scene_map.py [--csv out.csv]
"""
from __future__ import annotations

import argparse
import csv
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtti_hierarchy as rh  # noqa: E402

OVERLAY_SWITCH = 0x0203D9BC
FACTORY_SWITCH = 0x0203DEE0
ALLOC_FUNCS = {0x02001164, 0x02001154, 0x0200113C}
SCENE_ID_SLOT = 13

md = Cs(CS_ARCH_ARM, CS_MODE_ARM)


def word(data, base, addr):
    return struct.unpack_from("<I", data, addr - base)[0]


def insns(data, base, addr, count):
    return list(md.disasm(data[addr - base : addr - base + 4 * count], addr))


def pc_literal(data, base, ins):
    off = int(ins.op_str.split("#")[1].rstrip("]"), 16)
    if "#-" in ins.op_str:
        off = -int(ins.op_str.split("#-")[1].rstrip("]"), 16)
    return word(data, base, ins.address + 8 + off)


def switch_targets(data, base, func):
    for ins in insns(data, base, func, 8):
        if ins.mnemonic == "addls" and ins.op_str.startswith("pc, pc"):
            table = ins.address + 8
            break
    else:
        raise RuntimeError(f"no jump table in {func:#x}")
    out = []
    for ins in insns(data, base, table, 0x80):
        if ins.mnemonic != "b":
            break
        out.append(int(ins.op_str[1:], 16))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    args = ap.parse_args()

    imgs = rh.load_images()
    a9base, a9 = imgs["arm9"]

    overlay_of = []
    for t in switch_targets(a9, a9base, OVERLAY_SWITCH):
        first = insns(a9, a9base, t, 1)[0]
        if first.mnemonic == "ldr" and "[pc" in first.op_str:
            overlay_of.append(pc_literal(a9, a9base, first))
        else:  # "sub r0, r3, #1" with r3 = 0  -> -1 (no overlay)
            overlay_of.append(-1)

    factory = []
    for t in switch_targets(a9, a9base, FACTORY_SWITCH):
        size = ctor = None
        for ins in insns(a9, a9base, t, 14):
            if size is None and ins.mnemonic == "mov" and ins.op_str.startswith("r0, #"):
                size = int(ins.op_str[5:], 0)
            elif size is None and ins.mnemonic == "ldr" and ins.op_str.startswith("r0, [pc"):
                size = pc_literal(a9, a9base, ins)
            elif ins.mnemonic == "bl":
                tgt = int(ins.op_str[1:], 16)
                if tgt not in ALLOC_FUNCS:
                    ctor = tgt
                    break
            elif ins.mnemonic == "b" and size is not None:
                break
        factory.append((size, ctor))

    # class name per (image, sceneId) using vtable slot 13
    rows = rh.scan(imgs)
    names = {(img, a): n for img, a, n, _, _ in rows}
    scene_classes = {}
    for img, ti, name, _tv, base_ti in rows:
        for vptr, fns in rh.vtables(imgs, img, ti):
            if len(fns) <= SCENE_ID_SLOT:
                continue
            f = fns[SCENE_ID_SLOT]
            src = imgs["arm9"] if a9base <= f < a9base + len(a9) else imgs[img]
            if not (src[0] <= f < src[0] + len(src[1])):
                continue
            seq = insns(src[1], src[0], f, 2)
            if len(seq) == 2 and seq[0].mnemonic == "mov" and seq[0].op_str.startswith("r0, #") and seq[1].op_str == "lr":
                parent = names.get((img, base_ti)) or names.get(("arm9", base_ti)) or ""
                if parent.endswith("Scene") or name.endswith("Scene") or "Scene" in parent:
                    sid = int(seq[0].op_str[5:], 0)
                    scene_classes.setdefault(sid, set()).add((name, img, vptr))

    out = []
    for sid, (ov, (size, ctor)) in enumerate(zip(overlay_of, factory)):
        img = "arm9" if ctor and a9base <= ctor < a9base + len(a9) else (f"ov{ov:03d}" if ov >= 0 else "")
        cands = sorted(c for c in scene_classes.get(sid, ()) if c[1] in (img, "arm9", f"ov{ov:03d}"))
        cls = " / ".join(f"{n}" for n, _, _ in cands)
        out.append({
            "scene_id": sid,
            "overlay": ov,
            "object_size": hex(size) if size is not None else "",
            "constructor": f"0x{ctor:08X}" if ctor else "",
            "class": cls,
            "vptr": " / ".join(f"0x{v:08X}" for _, _, v in cands),
        })
    for r in out:
        print(f"{r['scene_id']:3d} 0x{r['scene_id']:02X}  ov={r['overlay']:>3}  size={r['object_size']:>7}  ctor={r['constructor']:>10}  {r['class']}")
    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)


if __name__ == "__main__":
    main()
