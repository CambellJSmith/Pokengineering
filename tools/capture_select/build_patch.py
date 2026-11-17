#!/usr/bin/env python3
"""Build the Capture Select v0 ROM patch (title-screen hook).

Controls on the title / demo screen:
    SELECT        start a capture of the current list entry, then advance
    L + SELECT    previous entry
    R + SELECT    skip ahead 10 entries
The capture HUD names the Pokemon. After the capture the game returns to the
title scene (0x2C).

How it works (see docs/scene_system.md §8-10):
  * ov28 (CDemoScene / CGameTitleScene) is grown: its BSS is materialised as
    zeros in the file and a code cave is appended after it, at
    ram + ram_size + bss_size (0x020EEA00), so no existing address moves.
  * vtable slot 2 (Update) of both scenes is redirected to `wrapper`, which
    calls the original Update (0x020D20A4), edge-detects SELECT on KEYINPUT,
    and on a press calls CaptureSetup_Clear (0x020418D4) and
    CaptureSetup_Add3 (0x020419D0) on 0x020B797C, sets BGM (+0x13C), arena
    (+0x13E) and return scene (+0x144), and returns scene 2 (CCaptureScene).
  * The list index and the previous key state live in CaptureSetup entry 7
    (+0x60 / +0x64), which is never used with count = 1 and is not cleared.

Output: work/capture_select/capture_select_patch.json and .meta.json, then
        python3 tools/patch_code_rom.py BASE.nds --patches <json> --output OUT.nds
"""
from __future__ import annotations

import csv
import json
import struct
import sys
from pathlib import Path

from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ranger_ids  # noqa: E402

OV = 28
OV_FILE = ROOT / "work/code_analysis/executables/overlays/overlay_028.bin"
OVT = ROOT / "a9ovr.bin"
ORIG_UPDATE = 0x020D20A4
VT_SLOT2 = [0x020DCE04 + 8, 0x020DD680 + 8]      # CDemoScene, CGameTitleScene
SETUP = 0x020B797C
CLEAR, ADD3 = 0x020418D4, 0x020419D0
KEYINPUT = 0x04000130
RETURN_SCENE = 0x2C


def target_list():
    """Distinct Ranger IDs from the capture database (real Pokemon only),
    ordered by National Dex then Ranger ID, with BGM/arena from the original
    script when one exists (0xFF = default)."""
    db = ROOT / "research/capture/capture_database.csv"
    best = {}
    for r in csv.DictReader(open(db)):
        if r["ranger_id"] == "":
            continue
        rid = int(r["ranger_id"])
        dex = ranger_ids.dex_of(rid)
        if dex is None or dex >= 900 or rid == 0:
            continue
        bgm = arena = 0xFF
        for tok in r["params"].split():
            if tok.startswith("CAP_BGM="):
                bgm = int(tok.split("=")[1] or 255)
            if tok.startswith("CAP_ARENA="):
                arena = int(tok.split("=")[1] or 255)
        cur = best.get(rid)
        if cur is None or (cur[1] == 0xFF and bgm != 0xFF) or (cur[2] == 0xFF and arena != 0xFF):
            best[rid] = (dex, bgm if bgm != 0xFF else (cur[1] if cur else 0xFF),
                         arena if arena != 0xFF else (cur[2] if cur else 0xFF))
    return sorted(((d, rid, b, a) for rid, (d, b, a) in best.items()))


def main():
    ovt = OVT.read_bytes()
    _id, ram, size, bss = struct.unpack_from("<4I", ovt, 32 * OV)
    image = OV_FILE.read_bytes()
    assert len(image) == size and ram == 0x020D1B80
    cave = ram + size + bss
    for a in VT_SLOT2:
        assert struct.unpack_from("<I", image, a - ram)[0] == ORIG_UPDATE, hex(a)

    targets = target_list()
    n = len(targets)
    asm = f"""
    wrapper:
        push {{r4-r7, lr}}
        bl   {ORIG_UPDATE:#x}
        mov  r4, r0
        ldr  r5, ={KEYINPUT:#x}
        ldrh r5, [r5]
        mvn  r5, r5
        ldr  r6, ={SETUP:#x}
        ldr  r7, [r6, #0x64]
        str  r5, [r6, #0x64]
        bic  r7, r5, r7
        tst  r7, #4
        beq  done
        ldr  r2, [r6, #0x60]
        tst  r5, #0x200
        subne r2, r2, #2
        tst  r5, #0x100
        addne r2, r2, #9
        ldr  r3, ={n}
    wrap_lo:
        cmp  r2, #0
        addlt r2, r2, r3
        blt  wrap_lo
    wrap_hi:
        cmp  r2, r3
        subge r2, r2, r3
        bge  wrap_hi
        add  r1, r2, #1
        str  r1, [r6, #0x60]
        adr  r7, table
        add  r7, r7, r2, lsl #2
        mov  r0, r6
        bl   {CLEAR:#x}
        mov  r0, r6
        ldrh r1, [r7]
        mov  r2, #0
        bl   {ADD3:#x}
        ldrb r0, [r7, #2]
        cmp  r0, #0xff
        moveq r0, #0
        add  r1, r6, #0x100
        strh r0, [r1, #0x3c]
        ldrb r0, [r7, #3]
        cmp  r0, #0xff
        ldreq r0, =0xffff
        strh r0, [r1, #0x3e]
        mov  r0, #{RETURN_SCENE:#x}
        str  r0, [r6, #0x144]
        mov  r4, #2
    done:
        mov  r0, r4
        pop  {{r4-r7, pc}}
        .ltorg
    table:
    """
    ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code, _ = ks.asm(asm, cave)
    code = bytes(code)
    table = b"".join(struct.pack("<HBB", rid, b, a) for _, rid, b, a in targets)
    cave_bytes = code + table

    patches = [{"target": f"ov{OV:03d}", "grow": True, "append_after_bss": cave_bytes.hex(),
                "comment": f"Capture Select cave at {cave:#010x} ({len(code)} code + {len(table)} table bytes)"}]
    for a in VT_SLOT2:
        patches.append({"target": f"ov{OV:03d}", "addr": f"{a:#010x}",
                        "expect": struct.pack('<I', ORIG_UPDATE).hex(),
                        "hex": struct.pack("<I", cave).hex(),
                        "comment": "Update -> Capture Select wrapper"})
    out = ROOT / "work/capture_select"
    out.mkdir(parents=True, exist_ok=True)
    (out / "capture_select_patch.json").write_text(json.dumps(patches, indent=1))
    (out / "capture_select_list.csv").write_text(
        "index,ranger_id,dex,name,bgm,arena\n" + "".join(
            f"{i},{rid},{d},{ranger_ids.name_of(rid)},{b},{a}\n" for i, (d, rid, b, a) in enumerate(targets)))
    print(f"cave {cave:#010x}: {len(code)} bytes code, {n} targets ({len(table)} bytes)")
    print(f"wrote {out/'capture_select_patch.json'} and capture_select_list.csv")


if __name__ == "__main__":
    main()
