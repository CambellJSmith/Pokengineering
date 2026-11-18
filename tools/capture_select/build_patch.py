#!/usr/bin/env python3
"""Build the Capture Select ROM patch: an on-screen battle menu on the title screen.

On the title / demo screen:
    SELECT          open the Capture Select menu
    (or the title menu's "Capture Select" button, which replaces Ranger Net)
    UP / DOWN       move (hold to repeat)
    LEFT / RIGHT    page (also L / R)
    A               start the highlighted battle
    B               close the menu (title reloads)
After a battle the game returns to the title scene (0x2C).

Battles (one menu entry each), built from research/capture/capture_database.csv:
  * every scripted field capture sequence (all its targets and options; label
    shown, e.g. "Sunkern x6 MQ01_EV002_0")
  * the 7 capture tutorials (capture scripts 1506-1512)
  * every sky capture: scripted (1C10) and free-flight sky enemies (SPKD)
  * every co-op capture Pokemon (MPCP)
  * every remaining wild Ranger ID ("WILD <name> <map>")
  * EXTRA: every other Ranger ID with capture data but no known trigger
    (e.g. Palkia, Heatran, Giratina), so every species/variant is selectable

Implementation (docs/scene_system.md section 10):
  * ov28 is grown: BSS materialised, code cave appended at 0x020EEA00.
  * Update (vtable slot 2) of CDemoScene / CGameTitleScene -> `wrapper`.
    Closed: call the original Update unless SELECT is newly pressed.
    Open: skip the title logic, keep the bottom-screen engine (A) in mode 5
    with BG3 as a 256x192 direct-colour bitmap in VRAM bank C (mapped to main
    BG at 0x06020000; C is unused on the title), handle input, and redraw
    with an embedded 8x8 font (Lat15-VGA8 console font) when needed.
  * A: CaptureSetup_Clear + CaptureSetup_Add3 per target, BGM (+0x13C),
    arena (+0x13E), return scene (+0x144), restore VRAMCNT_C, return scene 2.
  * Menu state lives at CaptureSetup+0x128 (unused tail of player record 3,
    which only multiplayer uses and Clear doesn't touch), so all 8 entry
    slots are free for targets:
      +0 u16 index  +2 u16 top  +4 u16 previous keys  +6 u8 open  +7 u8 dirty
      +8 u8 saved VRAMCNT_C  +9 u8 key-repeat counter
  * Every option a script sets is copied: targets (up to 8), BGM +0x13C,
    arena +0x13E, flags |= +0x142, +0x140, capture script +0x150 (tutorials),
    +0x154, +0x156.
"""
from __future__ import annotations

import collections
import csv
import gzip
import json
import re
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
RETURN_SCENE = 0x2C
VRAM = 0x06020000
FONT_FILE = Path("/usr/share/consolefonts/Lat15-VGA8.psf.gz")
MAX_TARGETS = 8
STATE = 0x020B797C + 0x128   # unused tail of player record 3 (multiplayer only), not touched by Clear
ROWS = 20
FALLBACK_ARENA = 13   # verified outdoor arena (sand + grass), used when nothing better is known
# Manual arena choices (arena catalog: screenshots of all 66 arena IDs from
# tools/emu/batch_battles.py; docs/scene_system.md section 10):
SKY_ARENA = 48                                   # clouds / open sky
MANUAL_ARENA_BY_DEX = {485: 40,                  # Heatran -> volcanic red earth
                       487: 31,                  # Giratina -> dark cave
                       484: 81, 483: 81,         # Palkia / Dialga -> ornate temple
                       493: 81,                  # Arceus -> ornate temple
                       151: 17,                  # Mew -> stone ruins
                       386: 48,                  # Deoxys -> sky
                       492: 77}                  # Shaymin -> flower meadow
# Styler presets (START in the menu): (level -> CaptureSetup+0x6C, energy -> +0x75/+0x76).
# Verified in the emulator: +0x75/+0x76 = 99 shows "099/099" energy; Clear's +0x6C = 1
# matches "Styler Level 01" on the result screen. Preset 0 keeps the Clear defaults.
STYLER_PRESETS = [None, (25, 60), (50, 99)]
TUTORIAL_CHAPTER = {2: 3, 3: 5, 4: 6, 5: 11, 7: 19}   # tutorial n is first started in chapter C0xx
# ov3 hook: skip Browser registration / release check for menu battles
OV3 = 3
OV3_FILE = ROOT / "work/code_analysis/executables/overlays/overlay_003.bin"
STATE_LOAD = 0x020D05D8          # "ldr r5, [r2, #0x14]" in the CCaptureScene state switch 0x020D05C4
STATE_LOAD_BYTES = bytes.fromhex("145092e5")   # verified outdoor arena (sand + grass), used when a battle has no map

C_BG = 0x8000 | (12 << 10) | (3 << 5) | 2       # navy
C_HI = 0x8000 | (0 << 10) | (16 << 5) | 31      # orange
C_FG = 0xFFFF                                   # white
C_HEAD = 0x8000 | (31 << 10) | (31 << 5) | 0    # cyan-ish (BGR: r=0,g=31,b=31)


def font_bytes() -> bytes:
    vendored = Path(__file__).with_name("font8x8.bin")   # ASCII 32..127 from Lat15-VGA8
    if vendored.exists():
        return vendored.read_bytes()
    d = gzip.open(FONT_FILE).read()
    if d[:2] != b"\x36\x04" or d[3] != 8:
        raise SystemExit("expected an 8x8 PSF1 font")
    glyphs = d[4:4 + 256 * 8]
    return glyphs[32 * 8:128 * 8]        # ASCII 32..127


def map_arenas():
    """map name -> default capture arena (MPPS record +0x6C).

    In the field, CFieldToCaptureState::Enter asks the field context
    (vfunc +0x50, ov2 0x020D89DC) for the arena when CaptureSetup+0x13E is
    0xFFFF: MPPS record of the current map, byte +0x6C + floor type (0..14),
    or +0x7B / +0x7C / +0x7A for floor types 15-22 / 23-30 / 31. From the
    title there is no field, so the menu uses the map's default (+0x6C)."""
    p = ROOT / "work/game_acf/archive/2482.MPPS"
    out = {}
    if p.exists():
        m = p.read_bytes()
        rs, n = struct.unpack_from("<II", m, 4)
        for i in range(n):
            r = m[0x10 + rs * i:0x10 + rs * (i + 1)]
            out.setdefault(f"m{r[1]:03d}_{r[2]:02d}", r[0x6C])
    return out


def chapter_maps():
    """chapter number -> start map (2483.CHPT +0 = MPPS index, +8 = chapter)."""
    c, m = ROOT / "work/game_acf/archive/2483.CHPT", ROOT / "work/game_acf/archive/2482.MPPS"
    out = {}
    if c.exists() and m.exists():
        cd, md = c.read_bytes(), m.read_bytes()
        rs, n = struct.unpack_from("<II", cd, 4)
        mrs = struct.unpack_from("<I", md, 4)[0]
        for i in range(n):
            idx, _a, _b, _x, _z, chap = struct.unpack_from("<HBBhhB", cd, 0x10 + rs * i)
            r = md[0x10 + mrs * idx:0x10 + mrs * (idx + 1)]
            out.setdefault(chap, f"m{r[1]:03d}_{r[2]:02d}")
    return out


def battles():
    """Menu entries as dicts: desc, label, ids, bgm, arena, flags, s150, v140, v154, v156.
    0xFF / 0xFFFF mean "leave the CaptureSetup_Clear default"."""
    db = list(csv.DictReader(open(ROOT / "research/capture/capture_database.csv")))

    def opts(s):
        o = {"bgm": 0xFF, "arena": 0xFF, "flags": 0, "s150": 0, "v140": 0xFFFF, "v154": 0xFFFF, "v156": 0xFFFF}
        for tok in s.split():
            k, _, v = tok.partition("=")
            if k == "CAP_BGM" and v: o["bgm"] = int(v)
            elif k == "CAP_ARENA" and v: o["arena"] = int(v)
            elif k == "CAP_FLAG1": o["flags"] |= 1
            elif k == "CAP_FLAG2": o["flags"] |= 2
            elif k == "CAP_FLAG4": o["flags"] |= 4
            elif k == "CAP_150" and v: o["s150"] = int(v)
            elif k == "CAP_140" and v: o["v140"] = int(v)
            elif k == "CAP_154" and v: o["v154"] = int(v)
            elif k == "CAP_156" and v: o["v156"] = int(v)
        return o

    arenas = map_arenas()
    chapters = chapter_maps()
    # habitat: most common arena of the maps where each species is placed or
    # scripted (same National Dex), used for battles without their own map
    habitat = collections.defaultdict(collections.Counter)
    for r in db:
        if r["ranger_id"] and r["source"] in ("wild_placement", "field_script"):
            mp = r["map"] or r.get("chapter_start_map", "")
            if arenas.get(mp, 0xFF) != 0xFF:
                habitat[ranger_ids.dex_of(int(r["ranger_id"]))][arenas[mp]] += 1

    sky_dex = {ranger_ids.dex_of(int(r["ranger_id"])) for r in db
               if r["ranger_id"] and r["source"] in ("sky_1C10", "sky_enemy")}

    def entry(ids, label, o, desc=None, map_name="", kind=""):
        o = dict(o)
        how = "script" if o["arena"] != 0xFF else ""
        if not how and arenas.get(map_name, 0xFF) != 0xFF:
            o["arena"], how = arenas[map_name], "map"
        dex = [ranger_ids.dex_of(i) for i in ids]
        if not how and kind == "sky":
            o["arena"], how = SKY_ARENA, "manual:sky"
        if not how and dex and dex[0] in MANUAL_ARENA_BY_DEX:
            o["arena"], how = MANUAL_ARENA_BY_DEX[dex[0]], "manual:legendary"
        if not how and dex and dex[0] in sky_dex and not habitat.get(dex[0]):
            o["arena"], how = SKY_ARENA, "manual:sky-species"
        if not how and dex and habitat.get(dex[0]):
            o["arena"], how = habitat[dex[0]].most_common(1)[0][0], "habitat"
        if not how:
            o["arena"], how = FALLBACK_ARENA, "fallback"
        return dict(desc=desc or describe(ids), label=label, ids=ids, map=map_name, arena_from=how, **o)

    out, seen_ids, seen_keys = [], set(), set()
    groups = collections.OrderedDict()
    for r in db:
        if r["source"] == "field_script" and r["ranger_id"]:
            groups.setdefault(r["trigger"], []).append(r)
    scripted = []
    for trig, rows in groups.items():
        ids = [int(r["ranger_id"]) for r in rows][:MAX_TARGETS]
        o = opts(rows[0]["params"])
        key = (tuple(ids), tuple(sorted(o.items())), rows[0]["map"] or rows[0].get("chapter_start_map", ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        scripted.append(entry(ids, rows[0]["label"] or rows[0]["map"], o,
                              map_name=rows[0]["map"] or rows[0].get("chapter_start_map", "")))
    scripted.sort(key=lambda e: e["label"])
    out += scripted
    for e in scripted:
        seen_ids.update(e["ids"])
    tut = collections.OrderedDict()
    for r in db:
        if r["source"] == "tutorial":
            tut.setdefault(r["label"], (r, []))[1].extend([int(r["ranger_id"])] if r["ranger_id"] else [])
    for label, (r, ids) in sorted(tut.items()):
        # count stays 0: the tutorial's capture script adds its own targets
        desc = "Tutorial %s: %s" % (label[-1], describe(ids)) if ids else "Tutorial %s" % label[-1]
        chap = TUTORIAL_CHAPTER.get(int(label[-1]))
        e = entry(ids, "", opts(r["params"]), desc=desc, map_name=chapters.get(chap, ""))
        e["ids"] = []        # count stays 0: the tutorial's capture script adds its own targets
        out.append(e)
    for src, label in (("sky_1C10", "SKY"), ("sky_enemy", "SKY"), ("coop", "CO-OP")):
        for r in db:
            if r["source"] == src and r["ranger_id"]:
                rid = int(r["ranger_id"])
                if rid in seen_ids or (ranger_ids.dex_of(rid) or 999) >= 900:
                    continue
                seen_ids.add(rid)
                out.append(entry([rid], label, opts(""), kind="sky" if label == "SKY" else ""))
    wild = {}
    for r in db:
        if r["source"] == "wild_placement" and r["ranger_id"]:
            rid = int(r["ranger_id"])
            if rid in seen_ids or rid == 0 or (ranger_ids.dex_of(rid) or 999) >= 900:
                continue
            if rid not in wild or (not wild[rid] and r["map"]):
                wild[rid] = r["map"]
    for rid in sorted(wild, key=lambda i: (ranger_ids.dex_of(i), i)):
        out.append(entry([rid], "WILD " + (wild[rid] or "co-op"), opts(""), map_name=wild[rid]))
    # EXTRA: every remaining Ranger ID that has capture data (CPOK/FPKD) but
    # no trigger found (e.g. Palkia, Heatran, Giratina), so that every
    # species and variant in the game can be picked.
    used = set(seen_ids) | set(wild)
    for e in out:
        used.update(e["ids"])
    used.update(int(r["ranger_id"]) for r in db if r["source"] == "tutorial" and r["ranger_id"])
    extra = [i for i in range(1, 770) if i not in used and (ranger_ids.dex_of(i) or 999) < 900]
    for rid in sorted(extra, key=lambda i: (ranger_ids.dex_of(i), i)):
        out.append(entry([rid], f"EXTRA #{rid}", opts("")))
    return out


def section_of(e):
    """Menu section for L/R jumps: story/quest events, tutorials, sky, co-op, wild, extra."""
    lab, desc = e["label"], e["desc"]
    if desc.startswith("Tutorial"):
        return "tutorial"
    for key in ("SKY", "CO-OP", "WILD", "EXTRA"):
        if lab.startswith(key):
            return key
    return "event"


def describe(ids):
    names = [ranger_ids.name_of(i) for i in ids]
    if len(set(names)) == 1 and len(names) > 1:
        return f"{names[0]} x{len(names)}"
    return "+".join(names)


def entry_text(i, desc, label):
    s = f"{i + 1:03d} {desc} {label}".rstrip()
    s = re.sub(r"[^\x20-\x7e]", "?", s)
    return s[:31]


def main():
    ovt = OVT.read_bytes()
    _id, ram, size, bss = struct.unpack_from("<4I", ovt, 32 * OV)
    image = OV_FILE.read_bytes()
    assert len(image) == size and ram == 0x020D1B80
    cave = ram + size + bss
    for a in VT_SLOT2:
        assert struct.unpack_from("<I", image, a - ram)[0] == ORIG_UPDATE, hex(a)

    blist = battles()
    n = len(blist)
    starts, prev = [], None
    for i, e in enumerate(blist):
        cat = section_of(e)
        if cat != prev:
            starts.append(i)
            prev = cat
    nsect = len(starts)
    sections_asm = "\n".join(f"    .short {x}" for x in starts)
    asm = f"""
wrapper:
    push {{r4-r11, lr}}
    mov  r8, r0
    mov  r9, r1
    mov  r10, r2
    mov  r11, r3
    ldr  r6, ={STATE:#x}
    ldr  r5, =0x04000130
    ldrh r5, [r5]
    mvn  r5, r5
    ldr  r1, =0x3ff
    and  r5, r5, r1
    ldrh r7, [r6, #4]
    strh r5, [r6, #4]
    bic  r7, r5, r7
    ldrb r0, [r6, #6]
    cmp  r0, #0
    bne  menu
    tst  r7, #4
    bne  open_menu
    ldrb r0, [r6, #10]
    cmp  r0, #0
    beq  no_reopen
    add  r0, r0, #1
    strb r0, [r6, #10]
    cmp  r0, #32
    bhs  open_menu
no_reopen:
    mov  r0, r8
    mov  r1, r9
    mov  r2, r10
    mov  r3, r11
    bl   {ORIG_UPDATE:#x}
    b    ret

open_menu:
    mov  r0, #0
    strb r0, [r6, #10]
    mov  r0, #1
    strb r0, [r6, #6]
    strb r0, [r6, #7]
    mov  r0, #0
    strb r0, [r6, #9]
    ldr  r1, =0x04000242
    ldrb r0, [r1]
    strb r0, [r6, #8]
    ldrh r0, [r6, #0]
    ldr  r1, ={n}
    cmp  r0, r1
    movhs r0, #0
    strh r0, [r6, #0]
    ldrh r1, [r6, #2]
    cmp  r0, r1
    movlo r1, r0
    add  r2, r1, #{ROWS}
    cmp  r0, r2
    subhs r1, r0, #{ROWS - 1}
    strh r1, [r6, #2]
    bl   setup_display
    bl   redraw
    mvn  r0, #1
    b    ret

menu:
    bl   setup_display
    tst  r7, #2
    bne  close_menu
    tst  r7, #1
    bne  launch
    tst  r7, #8
    beq  no_start
    ldrb r0, [r6, #11]
    add  r0, r0, #1
    cmp  r0, #3
    movge r0, #0
    strb r0, [r6, #11]
    mov  r0, #1
    strb r0, [r6, #7]
no_start:
    mov  r4, #0
    ldrb r2, [r6, #9]
    tst  r5, #0xc0
    addne r2, r2, #1
    moveq r2, #0
    cmp  r2, #200
    movhi r2, #100
    strb r2, [r6, #9]
    tst  r7, #0x40
    subne r4, r4, #1
    tst  r7, #0x80
    addne r4, r4, #1
    cmp  r2, #18
    blt  norep
    tst  r2, #3
    bne  norep
    tst  r5, #0x40
    subne r4, r4, #1
    tst  r5, #0x80
    addne r4, r4, #1
norep:
    tst  r7, #0x20
    subne r4, r4, #{ROWS}
    tst  r7, #0x10
    addne r4, r4, #{ROWS}
    tst  r7, #0x100
    bne  sect_next
    tst  r7, #0x200
    bne  sect_prev
    cmp  r4, #0
    beq  nomove
    ldrh r0, [r6, #0]
    add  r0, r0, r4
    ldr  r1, ={n}
wrap_lo:
    cmp  r0, #0
    addlt r0, r0, r1
    blt  wrap_lo
wrap_hi:
    cmp  r0, r1
    subge r0, r0, r1
    bge  wrap_hi
    strh r0, [r6, #0]
    ldrh r1, [r6, #2]
    cmp  r0, r1
    movlt r1, r0
    add  r2, r1, #{ROWS}
    cmp  r0, r2
    subge r1, r0, #{ROWS - 1}
    strh r1, [r6, #2]
    mov  r0, #1
    strb r0, [r6, #7]
    b    nomove
sect_next:
    ldrh r0, [r6, #0]
    ldr  r1, =sections
    ldr  r2, ={{nsect}}
    mov  r3, #0
sn_loop:
    cmp  r3, r2
    bge  sn_wrap
    add  r12, r1, r3, lsl #1
    ldrh r12, [r12]
    cmp  r12, r0
    bgt  set_idx
    add  r3, r3, #1
    b    sn_loop
sn_wrap:
    ldrh r12, [r1]
    b    set_idx
sect_prev:
    ldrh r0, [r6, #0]
    ldr  r1, =sections
    ldr  r2, ={{nsect}}
    sub  r3, r2, #1
sp_loop:
    cmp  r3, #0
    blt  sp_wrap
    add  r12, r1, r3, lsl #1
    ldrh r12, [r12]
    cmp  r12, r0
    blt  set_idx
    sub  r3, r3, #1
    b    sp_loop
sp_wrap:
    add  r12, r1, r2, lsl #1
    ldrh r12, [r12, #-2]
set_idx:
    strh r12, [r6, #0]
    strh r12, [r6, #2]
    mov  r0, #1
    strb r0, [r6, #7]
nomove:
    ldrb r0, [r6, #7]
    cmp  r0, #0
    beq  no_redraw
    bl   redraw
no_redraw:
    mvn  r0, #1
    b    ret

close_menu:
    bl   restore_vram
    mov  r0, #{RETURN_SCENE:#x}
    b    ret

launch:
    bl   restore_vram
    sub  r8, r6, #0x128
    ldrh r0, [r6, #0]
    ldr  r9, =battle_table
    add  r9, r9, r0, lsl #6
    mov  r0, r8
    bl   {CLEAR:#x}
    ldrb r10, [r9, #32]
    mov  r11, #0
addloop:
    cmp  r11, r10
    bge  added
    add  r1, r9, #36
    add  r1, r1, r11, lsl #1
    ldrh r1, [r1]
    mov  r0, r8
    mov  r2, #0
    bl   {ADD3:#x}
    add  r11, r11, #1
    b    addloop
added:
    add  r1, r8, #0x100
    ldrb r0, [r9, #33]
    cmp  r0, #0xff
    moveq r0, #0
    strh r0, [r1, #0x3c]
    ldrb r0, [r9, #34]
    cmp  r0, #0xff
    ldreq r0, =0xffff
    strh r0, [r1, #0x3e]
    ldrb r0, [r9, #35]
    ldrh r2, [r1, #0x42]
    orr  r2, r2, r0
    strh r2, [r1, #0x42]
    ldrb r0, [r9, #56]
    str  r0, [r1, #0x50]
    ldr  r3, =0xffff
    ldrh r0, [r9, #52]
    cmp  r0, r3
    strhne r0, [r1, #0x54]
    ldrh r0, [r9, #54]
    cmp  r0, r3
    strhne r0, [r1, #0x56]
    ldrh r0, [r9, #58]
    cmp  r0, r3
    strhne r0, [r1, #0x40]
    ldrb r0, [r6, #11]
    cmp  r0, #0
    beq  no_styler
    ldr  r1, =styler_table
    add  r1, r1, r0, lsl #2
    ldrh r2, [r1]
    str  r2, [r8, #0x6c]
    ldrb r2, [r1, #2]
    strb r2, [r8, #0x75]
    strb r2, [r8, #0x76]
no_styler:
    mov  r0, #1
    strb r0, [r6, #10]
    mov  r0, #{RETURN_SCENE:#x}
    str  r0, [r8, #0x144]
    mov  r0, #2
ret:
    pop  {{r4-r11, pc}}

restore_vram:
    ldrb r0, [r6, #8]
    ldr  r1, =0x04000242
    strb r0, [r1]
    mov  r0, #0
    strb r0, [r6, #6]
    bx   lr

setup_display:
    ldr  r0, =0x04000242
    mov  r1, #0x89
    strb r1, [r0]
    mov  r1, #0
    ldr  r0, =0x0400006c
    strh r1, [r0]
    ldr  r0, =0x0400106c
    strh r1, [r0]
    ldr  r0, =0x04000050
    strh r1, [r0]
    ldr  r0, =0x04001050
    strh r1, [r0]
    ldr  r0, =0x04000000
    ldr  r1, =0x00010805
    str  r1, [r0]
    ldr  r1, =0x4884
    strh r1, [r0, #0xe]
    mov  r1, #0x100
    strh r1, [r0, #0x30]
    strh r1, [r0, #0x36]
    mov  r1, #0
    strh r1, [r0, #0x32]
    strh r1, [r0, #0x34]
    str  r1, [r0, #0x38]
    str  r1, [r0, #0x3c]
    strh r1, [r0, #0x50]
    strh r1, [r0, #0x6c]
    ldr  r0, =0x04001000
    mov  r1, #0x10000
    str  r1, [r0]
    ldr  r0, =0x05000400
    ldr  r1, ={C_BG:#x}
    strh r1, [r0]
    bx   lr

fill_rows:
    ldr  r3, ={VRAM:#x}
    add  r3, r3, r0, lsl #12
    mov  r1, r1, lsl #10
fr_loop:
    str  r2, [r3], #4
    subs r1, r1, #1
    bne  fr_loop
    bx   lr

redraw:
    push {{r4-r11, lr}}
    mov  r0, #0
    strb r0, [r6, #7]
    mov  r0, #0
    mov  r1, #24
    ldr  r2, ={C_BG | (C_BG << 16):#x}
    bl   fill_rows
    mov  r0, #0
    mov  r1, #0
    ldr  r2, =str_title
    ldr  r3, ={C_HEAD:#x}
    ldr  r12, ={C_BG:#x}
    bl   draw_text
    mov  r0, #23
    mov  r1, #0
    ldr  r2, =styler_names
    ldrb r3, [r6, #11]
    add  r2, r2, r3, lsl #3
    ldr  r3, ={C_FG:#x}
    ldr  r12, ={C_BG:#x}
    bl   draw_text
    mov  r0, #0
    mov  r1, #23
    ldr  r2, =str_foot
    ldr  r3, ={C_HEAD:#x}
    ldr  r12, ={C_BG:#x}
    bl   draw_text
    sub  sp, sp, #16
    ldrh r0, [r6, #0]
    add  r0, r0, #1
    mov  r1, sp
    bl   fmt3
    mov  r0, #0x2f
    strb r0, [r1], #1
    ldr  r0, ={n}
    bl   fmt3
    mov  r0, #0
    strb r0, [r1]
    mov  r0, #25
    mov  r1, #23
    mov  r2, sp
    ldr  r3, ={C_FG:#x}
    ldr  r12, ={C_BG:#x}
    bl   draw_text
    add  sp, sp, #16
    ldrh r4, [r6, #2]
    mov  r5, #0
row_loop:
    cmp  r5, #{ROWS}
    bge  rows_done
    add  r7, r4, r5
    ldr  r8, ={n}
    cmp  r7, r8
    bge  rows_done
    ldrh r9, [r6, #0]
    ldr  r10, ={C_BG:#x}
    cmp  r7, r9
    bne  no_hl
    ldr  r10, ={C_HI:#x}
    add  r0, r5, #2
    mov  r1, #1
    orr  r2, r10, r10, lsl #16
    bl   fill_rows
no_hl:
    mov  r0, #0
    add  r1, r5, #2
    ldr  r2, =battle_table
    add  r2, r2, r7, lsl #6
    ldr  r3, ={C_FG:#x}
    mov  r12, r10
    bl   draw_text
    add  r5, r5, #1
    b    row_loop
rows_done:
    pop  {{r4-r11, pc}}

fmt3:
    mov  r2, #0x30
f100:
    cmp  r0, #100
    subge r0, r0, #100
    addge r2, r2, #1
    bge  f100
    strb r2, [r1], #1
    mov  r2, #0x30
f10:
    cmp  r0, #10
    subge r0, r0, #10
    addge r2, r2, #1
    bge  f10
    strb r2, [r1], #1
    add  r2, r0, #0x30
    strb r2, [r1], #1
    bx   lr

draw_text:
    push {{r4-r11, lr}}
    mov  r11, r12
    ldr  r10, =font
dt_loop:
    cmp  r0, #32
    bge  dt_end
    ldrb r4, [r2], #1
    cmp  r4, #0
    beq  dt_end
    sub  r4, r4, #32
    cmp  r4, #95
    movhi r4, #0
    add  r4, r10, r4, lsl #3
    ldr  r5, ={VRAM:#x}
    add  r5, r5, r1, lsl #12
    add  r5, r5, r0, lsl #4
    mov  r6, #0
glyph_row:
    ldrb r7, [r4, r6]
    mov  r8, #0
glyph_bit:
    tst  r7, #0x80
    movne r9, r3
    moveq r9, r11
    strh r9, [r5, r8]
    mov  r7, r7, lsl #1
    add  r8, r8, #2
    cmp  r8, #16
    blt  glyph_bit
    add  r5, r5, #512
    add  r6, r6, #1
    cmp  r6, #8
    blt  glyph_row
    add  r0, r0, #1
    b    dt_loop
dt_end:
    pop  {{r4-r11, pc}}

    .ltorg
str_title:
    .asciz "CAPTURE SELECT  STYLER:"
    .align 2
str_foot:
    .asciz "L/R:SECTION START:STYLER"
    .align 2
styler_names:
    .ascii "NORMAL"
    .byte 0, 0
    .ascii "STRONG"
    .byte 0, 0
    .ascii "MAX"
    .byte 0, 0, 0, 0, 0
styler_table:
    .short 0
    .byte 0, 0
    .short {STYLER_PRESETS[1][0]}
    .byte {STYLER_PRESETS[1][1]}, 0
    .short {STYLER_PRESETS[2][0]}
    .byte {STYLER_PRESETS[2][1]}, 0
sections:
{{sections_asm}}
    .align 2
font:
    .space 768
battle_table:
"""
    asm = asm.replace("{nsect}", str(nsect)).replace("{sections_asm}", sections_asm)
    ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code, _ = ks.asm(asm, cave)
    code = bytearray(code)
    fnt = font_bytes()
    assert len(fnt) == 96 * 8 and len(code) % 4 == 0
    code[-len(fnt):] = fnt                      # fill the .space reserved for the font
    head = bytes(code)
    # Keystone mis-assembles some conditional BL to forward labels as a
    # branch-to-self; refuse any branch whose target is its own address.
    try:
        from capstone import CS_ARCH_ARM as _A, CS_MODE_ARM as _M, Cs as _Cs
        _dis = _Cs(_A, _M).disasm(head[:len(head) - len(fnt)], cave)
    except ImportError:                          # optional sanity check
        _dis = []
    for ins in _dis:
        if ins.mnemonic.startswith("b") and ins.op_str.startswith("#"):
            if int(ins.op_str[1:], 16) == ins.address:
                raise SystemExit(f"assembler produced a self-branch at {ins.address:#x}: {ins.mnemonic}")
    table = bytearray()
    # record: text[32] | count u8 @32 | bgm u8 @33 | arena u8 @34 | flags u8 @35 |
    #         ids u16[8] @36 | +0x154 u16 @52 | +0x156 u16 @54 | +0x150 u8 @56 | +0x140 u16 @58
    for i, e in enumerate(blist):
        rec = bytearray(64)
        txt = entry_text(i, e["desc"], e["label"]).encode("ascii")
        rec[:len(txt)] = txt
        rec[32:36] = bytes([len(e["ids"]), e["bgm"] & 0xFF, e["arena"] & 0xFF, e["flags"]])
        for k, rid in enumerate(e["ids"]):
            struct.pack_into("<H", rec, 36 + 2 * k, rid)
        struct.pack_into("<HHBxH", rec, 52, e["v154"], e["v156"], e["s150"], e["v140"])
        table += rec
    cave_bytes = head + bytes(table)

    patches = [{"target": f"ov{OV:03d}", "append_after_bss": cave_bytes.hex(),
                "comment": f"Capture Select menu cave at {cave:#010x} ({len(head)} code, {n} battles)"}]
    for a in VT_SLOT2:
        patches.append({"target": f"ov{OV:03d}", "addr": f"{a:#010x}",
                        "expect": struct.pack('<I', ORIG_UPDATE).hex(),
                        "hex": struct.pack("<I", cave).hex(),
                        "comment": "Update -> Capture Select wrapper"})
    patches += title_button_patches(ks, cave + len(cave_bytes))
    patches += skip_browser_patches(ks)
    out = ROOT / "work/capture_select"
    out.mkdir(parents=True, exist_ok=True)
    (out / "capture_select_patch.json").write_text(json.dumps(patches, indent=1))
    with open(out / "capture_select_list.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "menu_text", "ranger_ids", "names", "bgm", "arena", "flags", "capture_script", "v154", "v156", "v140", "map", "arena_from"])
        for i, e in enumerate(blist):
            w.writerow([i, entry_text(i, e["desc"], e["label"]), " ".join(map(str, e["ids"])),
                        " | ".join(ranger_ids.name_of(x) for x in e["ids"]), e["bgm"], e["arena"],
                        e["flags"], e["s150"], e["v154"], e["v156"], e["v140"], e["map"], e["arena_from"]])
    end = cave + len(cave_bytes)
    print(f"cave {cave:#010x}-{end:#010x}: {len(head) - len(fnt)} bytes code+strings, font {len(fnt)}, {n} battles")
    assert end < 0x0212CFC0, "cave would overlap the heap"
    print(f"wrote {out/'capture_select_patch.json'} and capture_select_list.csv")


# Title menu (CDemoMenuState, ov28): the third button (selection 2) was
# "Ranger Net" (scene 0x2B; the online service is closed). Its handler at
# 0x020D96B8 is replaced with: set the reopen counter (STATE+10 = 1) and
# reload the title scene (next scene = 0x2C, like New Game sets 0x1C), so the
# fresh title opens the menu ~32 frames later, exactly as after a battle.
# (Opening it in place left the title's fade-out darkening the screen.) The label is changed in the text archive by
# play_capture_select.sh / tools/capture_select/relabel_title_button.sh.
RANGER_NET_HANDLER = 0x020D96B8
RANGER_NET_BYTES = bytes.fromhex("d00195e5000050e32b00a0b3d00185b5")
MENU_STATE_DONE = 0x020D972C


def title_button_patches(ks, at):
    image = OV_FILE.read_bytes()
    off = RANGER_NET_HANDLER - 0x020D1B80
    assert image[off:off + 16] == RANGER_NET_BYTES, "unexpected Ranger Net handler"
    code, _ = ks.asm(f"""
        ldr   r1, ={STATE:#x}
        mov   r0, #1
        strb  r0, [r1, #10]
        ldr   r0, [r5, #0x1d0]
        cmp   r0, #0
        movlt r0, #{RETURN_SCENE:#x}
        strlt r0, [r5, #0x1d0]
        bx    lr
    """, at)
    hook, _ = ks.asm(f"bl {at:#x}\nb {MENU_STATE_DONE:#x}", RANGER_NET_HANDLER)
    return [
        {"target": f"ov{OV:03d}", "append_after_bss": bytes(code).hex(),
         "comment": f"title-menu Capture Select button handler ({at:#010x})"},
        {"target": f"ov{OV:03d}", "addr": f"{RANGER_NET_HANDLER:#010x}", "expect": RANGER_NET_BYTES[:8].hex(),
         "hex": bytes(hook).hex(), "comment": "Ranger Net button -> Capture Select"},
    ]


def skip_browser_patches(ks):
    """Menu battles must not register into the Browser (save data): in the
    CCaptureScene state switch, turn a request for AddBrowser (10) or
    CheckRelease (11) into exit (7) when the capture's return scene
    (request block 0x020B7AB8 + 8 = CaptureSetup+0x144) is the title (0x2C).
    Only Capture Select sets that return scene; field captures use 0x1B.
    State numbers were read from the singletons' vptrs in the emulator
    (docs/scene_system.md section 10)."""
    ovt = OVT.read_bytes()
    _id, ram, size, bss = struct.unpack_from("<4I", ovt, 32 * OV3)
    image = OV3_FILE.read_bytes()
    assert image[STATE_LOAD - ram:STATE_LOAD - ram + 4] == STATE_LOAD_BYTES
    cave = ram + size + bss
    code, _ = ks.asm(f"""
        ldr  r5, [r2, #0x14]
        cmp  r5, #10
        cmpne r5, #11
        bxne lr
        ldr  r12, [r1, #8]
        cmp  r12, #{RETURN_SCENE:#x}
        moveq r5, #7
        bx   lr
    """, cave)
    bl, _ = ks.asm(f"bl {cave:#x}", STATE_LOAD)
    return [
        {"target": f"ov{OV3:03d}", "append_after_bss": bytes(code).hex(),
         "comment": f"skip AddBrowser/CheckRelease for menu battles (cave {cave:#010x})"},
        {"target": f"ov{OV3:03d}", "addr": f"{STATE_LOAD:#010x}", "expect": STATE_LOAD_BYTES.hex(),
         "hex": bytes(bl).hex(), "comment": "state load -> skip-browser check"},
    ]


if __name__ == "__main__":
    main()
