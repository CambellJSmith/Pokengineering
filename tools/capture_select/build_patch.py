#!/usr/bin/env python3
"""Build the Capture Select ROM patch: an on-screen battle menu on the title screen.

On the title / demo screen:
    SELECT          open the Capture Select menu
    (or the title menu's "Capture Select" button, which replaces Ranger Net)
    UP / DOWN       move (hold to repeat)
    LEFT / RIGHT    page by one screen (11 rows)
    L / R           previous / next section (Story & Quests, Tutorials, Sky,
                    Co-op, Wild Pokemon, Extras)
    START           styler preset (Lv.1 / Lv.25 / Lv.50)
    A               start the highlighted battle (fades out)
    B               close the menu (fades out, title reloads)
After a battle (or B) the game returns to the title/demo scene (0x25).

Battles (one menu entry each), built from research/capture/capture_database.csv:
  * every scripted field capture sequence (all its targets and options;
    shown as e.g. "Sunkern x6" tagged "Quest 1", or "Raikou" tagged "Story")
  * the 7 capture tutorials (capture scripts 1506-1512)
  * every sky capture: scripted (1C10) and free-flight sky enemies (SPKD)
  * every co-op capture Pokemon (MPCP)
  * every remaining wild Ranger ID ("Wild Pokemon" section)
  * EXTRA: every other Ranger ID with capture data but no known trigger
    (e.g. Palkia, Heatran, Giratina), so every species/variant is selectable

Implementation (docs/scene_system.md section 10):
  * ov28 is grown: BSS materialised, code cave appended at 0x020EEA00.
  * Update (vtable slot 2) of CDemoScene / CGameTitleScene -> `wrapper`.
    Closed: call the original Update unless SELECT is newly pressed.
    Open: skip the title logic, keep the bottom-screen engine (A) in mode 5
    with BG3 as a 256x192 direct-colour bitmap in VRAM bank C (mapped to main
    BG at 0x06020000; C is unused on the title), handle input, and redraw
    when needed. The look follows the title screen: sky-blue gradient, navy
    header with the logo's yellow/orange rules, a cloud-white rounded list
    panel, yellow highlight bar, drop-shadowed proportional text (Lat15-VGA8
    glyphs trimmed to their width, plus arrow / e-acute / multiply glyphs),
    a per-section list with scrollbar, and MASTER_BRIGHT fades.
  * A: CaptureSetup_Clear + CaptureSetup_Add3 per target, BGM (+0x13C),
    arena (+0x13E), return scene (+0x144), restore VRAMCNT_C, return scene 2.
  * Menu state lives at CaptureSetup+0x128 (unused tail of player record 3,
    which only multiplayer uses and Clear doesn't touch), so all 8 entry
    slots are free for targets:
      +0 u16 index  +2 u16 top  +4 u16 previous keys  +6 u8 open  +7 u8 dirty
      +8 u8 saved VRAMCNT_C  +9 u8 key-repeat counter  +10 reopen counter
      +11 styler preset
    Fade and current-section bytes live in the cave itself (`vars`, reset
    when ov28 reloads), so the use of player record 3 isn't extended past
    the bytes already verified.
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
MENU_EXIT_SCENE = 0x00   # B / title button: CStartScene (ov0), as at boot, so ov28 reloads fresh
                         # (re-creating a title scene from inside ov28 leaves stale ov28 state)
RETURN_SCENE = 0x25   # CDemoScene. Not 0x2C: creating CGameTitleScene directly reads a
                      # null message string (bank 232 #9) and data-aborts on hardware/melonDS.
VRAM = 0x06020000
FONT_FILE = Path("/usr/share/consolefonts/Lat15-VGA8.psf.gz")
MAX_TARGETS = 8
STATE = 0x020B797C + 0x128   # unused tail of player record 3 (multiplayer only), not touched by Clear
ROWS = 11                    # list rows on screen (12 px each)
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
# Styler presets (START in the menu): styler levels. The field copies the player's
# styler from the save (CFieldToCaptureState::Enter, ov2 0x020DF760): level -> player
# record +0x74 (CaptureSetup+0x74), power -> +0x70 and max energy -> +0x76 from the
# level table 0x020BD41C (getter 0x0205F3C4: +4 energy, +6 power; loaded on the title
# screen), plus 5 per upgrade. The menu does the same lookup at launch, so a preset is a
# real styler of that level (Lv.50: 104 energy, power 205; Lv.1 keeps Clear's 10/10).
STYLER_LEVELS = [1, 25, 50, 99]
LEVEL_TABLE, LEVEL_GET = 0x020BD41C, 0x0205F3C4
TUTORIAL_CHAPTER = {2: 3, 3: 5, 4: 6, 5: 11, 7: 19}   # tutorial n is first started in chapter C0xx
# Tutorial 1 (capture script 1506, never started by the story) is a stub: it
# runs the shared tutorial intro and starts the capture without adding a
# Pokemon (3C03/3C05). Count 0 gives a one-slot target array whose slot 0 is
# NULL, and the opening capture state (ov3 0x020F9AEC) reads that slot's
# species ([NULL+0x1E6]): a data abort on hardware/melonDS. The menu adds this
# target itself instead (the tutorial Pikachu that tutorials 2 and 7 use).
TUTORIAL_MENU_TARGET = {1: 386}
# ov3 hook: skip Browser registration / release check for menu battles
OV3 = 3
OV3_FILE = ROOT / "work/code_analysis/executables/overlays/overlay_003.bin"
STATE_LOAD = 0x020D05D8          # "ldr r5, [r2, #0x14]" in the CCaptureScene state switch 0x020D05C4
STATE_LOAD_BYTES = bytes.fromhex("145092e5")   # verified outdoor arena (sand + grass), used when a battle has no map

def rgb(r, g, b):
    """24-bit colour -> DS direct-colour pixel (BGR555 + opaque bit 15)."""
    return 0x8000 | (b >> 3) << 10 | (g >> 3) << 5 | r >> 3


# Palette sampled from the title screen (sky gradient, clouds, logo yellow/orange),
# so the menu reads as part of the title rather than a debug console.
SKY_TOP, SKY_BOTTOM = (16, 64, 184), (64, 136, 228)
C_HEADER = rgb(12, 40, 120)       # deep navy band
C_YELLOW = rgb(255, 207, 12)      # "POKEMON" logo yellow: highlight bar, header accents
C_ORANGE = rgb(215, 125, 28)      # "GUARDIAN SIGNS" orange: cursor, highlight edge
C_WHITE = rgb(255, 255, 255)
C_SHADOW = rgb(8, 24, 72)         # text drop shadow (like "Please tap the Touch Screen!")
C_BORDER = rgb(16, 48, 128)       # list panel outline
C_PANEL = rgb(236, 242, 255)      # cloud white list panel
C_TEXT = rgb(20, 36, 84)          # list text
C_MUTED = rgb(96, 116, 168)       # list tags
C_TRACK = rgb(196, 212, 244)      # scrollbar track
C_THUMB = rgb(40, 96, 208)        # scrollbar thumb
C_PALE = rgb(200, 220, 255)       # counter
C_SUB_BACKDROP = rgb(20, 77, 207)  # top screen while the menu is open (title sky blue)
FIXED = 0x10000                   # draw_text colour flag: ignore inline colour codes
CODE_COLORS = [C_WHITE, C_YELLOW, C_TEXT, C_MUTED]   # inline codes \x01..\x04

# Layout (pixels, bottom screen 256x192)
PANEL = (6, 38, 244, 136)         # list panel x, y, w, h (outline; inside is 1 px in)
ROW_Y0, ROW_H = 41, 12
TRACK = (237, 41, 4, 130)         # scrollbar x, y, w, h
THUMB_H = 16
NAME_X, TAG_RIGHT, NAME_MAX_PX = 22, 230, 160
FADE_FRAMES = 8                   # fade in on open, fade out on B / A (MASTER_BRIGHT)

# Extra glyphs after ASCII 32..127 (8x8, bit 7 = leftmost column)
EXTRA_GLYPHS = {
    0x80: [0x04, 0x0C, 0x1C, 0x3C, 0x1C, 0x0C, 0x04, 0x00],   # left arrow
    0x81: [0x20, 0x30, 0x38, 0x3C, 0x38, 0x30, 0x20, 0x00],   # right arrow
    0x82: [0x18, 0x30, 0x78, 0xCC, 0xFC, 0xC0, 0x78, 0x00],   # e acute (Pokemon)
    0x83: [0x00, 0x00, 0x66, 0x3C, 0x18, 0x3C, 0x66, 0x00],   # multiplication sign
    0x84: [0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00],   # middle dot
}
NGLYPH = 96 + len(EXTRA_GLYPHS)


def font_bytes() -> bytes:
    """ASCII 32..127 (Lat15-VGA8) followed by EXTRA_GLYPHS (codes 0x80..)."""
    vendored = Path(__file__).with_name("font8x8.bin")   # ASCII 32..127 from Lat15-VGA8
    if vendored.exists():
        base = vendored.read_bytes()
    else:
        d = gzip.open(FONT_FILE).read()
        if d[:2] != b"\x36\x04" or d[3] != 8:
            raise SystemExit("expected an 8x8 PSF1 font")
        base = d[4 + 32 * 8:4 + 128 * 8]   # ASCII 32..127
    assert sorted(EXTRA_GLYPHS) == list(range(0x80, 0x80 + len(EXTRA_GLYPHS)))
    return base + b"".join(bytes(EXTRA_GLYPHS[c]) for c in sorted(EXTRA_GLYPHS))


def glyph_metrics(font: bytes) -> bytes:
    """Per glyph: (leading empty columns << 4) | width, for proportional text."""
    out = bytearray()
    for g in range(NGLYPH):
        cols = 0
        for row in font[g * 8:g * 8 + 8]:
            cols |= row
        if g == 0 or not cols:              # space (and blank glyphs): 3 px
            out.append(3)
            continue
        used = [c for c in range(8) if cols & (0x80 >> c)]
        out.append(used[0] << 4 | (used[-1] - used[0] + 1))
    return bytes(out)


def glyph_index(ch: int) -> int:
    return ch - 32 if 32 <= ch < 128 else (96 + ch - 0x80 if 0x80 <= ch < 0x80 + len(EXTRA_GLYPHS) else 0)


def text_px(s: bytes, metrics: bytes) -> int:
    """Pixel width of a menu string as draw_text renders it (codes < 8 take no space)."""
    w = sum((metrics[glyph_index(c)] & 15) + 1 for c in s if c >= 8)
    return max(0, w - 1)


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
        n = int(label[-1])
        menu_ids = [TUTORIAL_MENU_TARGET[n]] if n in TUTORIAL_MENU_TARGET else []
        shown = ids or menu_ids
        desc = "Tutorial %s: %s" % (n, describe(shown)) if shown else "Tutorial %s" % n
        chap = TUTORIAL_CHAPTER.get(n)
        e = entry(ids, "", opts(r["params"]), desc=desc, map_name=chapters.get(chap, ""))
        # count stays 0 when the tutorial's capture script adds its own targets
        e["ids"] = menu_ids
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


# Section headings shown above the list (L/R jumps between them)
SECTION_NAMES = {"event": "Story & Quests", "tutorial": "Tutorials", "SKY": "Sky Captures",
                 "CO-OP": "Co-op Captures", "WILD": "Wild Pok\x82mon", "EXTRA": "Extras"}


def species_text(ids, metrics, max_px=None):
    """Player-facing target list: "Beldum ×8", "Buizel & Croagunk", "Aipom & 2 more"."""
    counts = collections.OrderedDict()
    for i in ids:
        n = ranger_ids.name_of(i)
        counts[n] = counts.get(n, 0) + 1
    parts = [n if c == 1 else f"{n} \x83{c}" for n, c in counts.items()]
    for s in (" & ".join(parts) if len(parts) <= 2 else None,
              " & ".join(counts) if len(parts) == 2 else None,          # drop the counts
              f"{parts[0]} & {len(parts) - 1} more" if len(parts) > 1 else parts[0] if parts else None):
        if s and len(s) < 21 and text_px(s.encode("latin-1"), metrics) <= (max_px or NAME_MAX_PX):
            return s
    return parts[0]


def menu_labels(blist, metrics):
    """(name, tag) per entry: species on the left, the kind of battle as a muted
    tag on the right (Story / Quest 12 / Tutorial 3), "Var. n" for repeats
    of the same species within a section. No script IDs or map codes."""
    out = []
    for e in blist:
        sec = section_of(e)
        lab = e["label"]
        if sec == "tutorial":
            n = e["desc"].split(":")[0].split()[-1]
            m = re.match(r"Tutorial \d+: (.*)", e["desc"])
            name = m.group(1).replace(" x", " \x83") if m else "Capture basics"
            tag = f"Tutorial {n}"
        else:
            tag = ""
            if sec == "event":
                q = re.match(r"MQ(\d+)", lab)
                tag = f"Quest {int(q.group(1))}" if q else "Story" if re.match(r"C\d", lab) else "Event"
            room = TAG_RIGHT - NAME_X - 6 - (text_px(tag.encode("latin-1"), metrics) if tag else 0)
            name = species_text(e["ids"], metrics, min(NAME_MAX_PX, room))
        out.append([name, tag, sec])
    # number repeats of the same name within a section (WILD Delibird, EXTRA variants)
    seen = collections.Counter((s, n) for n, _t, s in out)
    k = collections.Counter()
    for row in out:
        name, tag, sec = row
        if not tag and seen[(sec, name)] > 1:
            k[(sec, name)] += 1
            row[1] = f"Var. {k[(sec, name)]}"
    return [(n, t) for n, t, _s in out]


def entry_text(i, desc, label):
    """Plain-ASCII list line for capture_select_list.csv."""
    return f"{desc}  [{label}]" if label else desc


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
    fnt = font_bytes()
    metrics = glyph_metrics(fnt)
    labels = menu_labels(blist, metrics)
    assert FADE_FRAMES == 8, "fade code uses level = remaining * 2"

    # sections: start, length, scrollbar multiplier (16.16, 0 = list fits), heading
    starts, keys, prev = [], [], None
    for i, e in enumerate(blist):
        cat = section_of(e)
        if cat != prev:
            starts.append(i)
            keys.append(cat)
            prev = cat
    nsect = len(starts)
    sect_bin = bytearray()
    for s, (st, key) in enumerate(zip(starts, keys)):
        ln = (starts[s + 1] if s + 1 < nsect else n) - st
        mul = 0 if ln <= ROWS else ((TRACK[3] - THUMB_H) << 16) // (ln - 1)
        name = f"\x80 {SECTION_NAMES[key]} \x81".encode("latin-1")
        assert len(name) < 24
        sect_bin += struct.pack("<HHI", st, ln, mul) + name.ljust(24, b"\0")

    def lerp(a, b, t):
        return tuple(round(x + (y - x) * t) for x, y in zip(a, b))
    grad = b"".join(struct.pack("<H", rgb(*lerp(SKY_TOP, SKY_BOTTOM, y / 191))) for y in range(192))

    def data(b: bytes) -> str:
        return "\n".join("    .byte " + ", ".join(str(x) for x in b[i:i + 32]) for i in range(0, len(b), 32))

    def cstr(s: str) -> str:
        return data(s.encode("latin-1") + b"\0")

    title = "Capture Select"
    foot = "\x02A\x01 Go  \x02B\x01 Back  \x02L/R\x01 Jump  \x02START\x01 Styler"
    assert 8 + text_px(foot.encode("latin-1"), metrics) <= 248, "footer too wide"
    styler_names = [b"Styler Lv.%d" % lv for lv in STYLER_LEVELS]
    assert all(1 <= lv <= 99 for lv in STYLER_LEVELS) and len(STYLER_LEVELS) <= 8
    px, py, pw, ph = PANEL
    tx, ty, tw, th = TRACK
    # gradient margins beside the list panel, stored as whole words (2 px each)
    g_regs = ["r0", "r1", "r2", "r3", "r10", "r11", "r12", "lr"]
    margin_l, margin_r = px, 256 - (px + pw)
    assert margin_l % 2 == 0 and margin_r % 2 == 0 and 2 <= margin_l <= 16 and 2 <= margin_r <= 16
    G_LEFT = "{" + ", ".join(g_regs[:margin_l // 2]) + "}"
    G_RIGHT = "{" + ", ".join(g_regs[:margin_r // 2]) + "}"
    C = dict(C_HEADER=C_HEADER, C_YELLOW=C_YELLOW, C_ORANGE=C_ORANGE, C_WHITE=C_WHITE, C_BORDER=C_BORDER,
             C_PANEL=C_PANEL, C_TEXT=C_TEXT, C_MUTED=C_MUTED, C_TRACK=C_TRACK, C_THUMB=C_THUMB, C_PALE=C_PALE)
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
    strb r0, [r6, #9]
    ldr  r12, =vars
    strb r0, [r12, #1]
    mov  r0, #1
    strb r0, [r6, #6]
    strb r0, [r6, #7]
    mov  r0, #{FADE_FRAMES}
    ldr  r12, =vars
    strb r0, [r12, #0]
    ldr  r1, =0x04000242
    ldrb r0, [r1]
    strb r0, [r6, #8]
    ldrh r0, [r6, #0]
    ldr  r1, ={n}
    cmp  r0, r1
    movhs r0, #0
    strh r0, [r6, #0]
    bl   fix_top
    bl   setup_display
    bl   redraw
    ldr  r0, =0x8010               @ start black, fade in
    ldr  r1, =0x0400006c
    strh r0, [r1]
    ldr  r1, =0x0400106c
    strh r0, [r1]
    mvn  r0, #1
    b    ret

menu:
    bl   setup_display
    ldr  r12, =vars
    ldrb r0, [r12, #0]             @ fade frames left
    cmp  r0, #0
    beq  menu_input
    sub  r0, r0, #1
    ldr  r12, =vars
    strb r0, [r12, #0]
    ldr  r12, =vars
    ldrb r1, [r12, #1]             @ 0 fade in, 1 fade out + close, 2 fade out + launch
    mov  r2, r0, lsl #1
    cmp  r1, #0
    rsbne r2, r2, #16
    orr  r2, r2, #0x8000           @ MASTER_BRIGHT: darken by r2/16
    ldr  r3, =0x0400006c
    strh r2, [r3]
    ldr  r3, =0x0400106c
    strh r2, [r3]
    cmp  r0, #0
    bne  nomove
    cmp  r1, #1
    beq  close_menu
    cmp  r1, #2
    beq  launch
    b    nomove

menu_input:
    tst  r7, #2
    bne  start_close
    tst  r7, #1
    bne  start_launch
    tst  r7, #8
    beq  no_start
    ldrb r0, [r6, #11]
    add  r0, r0, #1
    cmp  r0, #{len(STYLER_LEVELS)}
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
    ldrh r9, [r6, #2]                @ old top
    ldr  r12, =vars
    ldrb r10, [r12, #2]              @ old section
    strh r0, [r6, #0]
    bl   fix_top
    ldrh r0, [r6, #2]
    ldr  r12, =vars
    ldrb r1, [r12, #2]
    cmp  r0, r9
    moveq r0, #4                     @ same page: just the two rows
    movne r0, #2                     @ scrolled: the list
    cmp  r1, r10
    movne r0, #1                     @ new section: everything (heading)
    ldrb r2, [r6, #7]
    orr  r0, r0, r2
    strb r0, [r6, #7]
    b    nomove
sect_next:
    ldr  r12, =vars
    ldrb r0, [r12, #2]
    add  r0, r0, #1
    cmp  r0, #{nsect}
    movge r0, #0
    b    set_sect
sect_prev:
    ldr  r12, =vars
    ldrb r0, [r12, #2]
    subs r0, r0, #1
    movlt r0, #{nsect - 1}
set_sect:
    ldr  r1, =sections
    add  r1, r1, r0, lsl #5
    ldrh r12, [r1]
    strh r12, [r6, #0]
    strh r12, [r6, #2]
    bl   fix_top
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

start_close:
    mov  r1, #1
    b    start_fade
start_launch:
    mov  r1, #2
start_fade:
    ldr  r12, =vars
    strb r1, [r12, #1]
    mov  r0, #{FADE_FRAMES}
    ldr  r12, =vars
    strb r0, [r12, #0]
    b    nomove

close_menu:
    bl   restore_vram
    mov  r0, #{MENU_EXIT_SCENE:#x}
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
    ldrb r0, [r6, #11]               @ styler preset -> level
    cmp  r0, #{len(STYLER_LEVELS)}
    movhs r0, #0
    ldr  r1, =styler_table
    ldrb r1, [r1, r0]
    strb r1, [r8, #0x74]
    ldr  r0, ={LEVEL_TABLE:#x}
    bl   {LEVEL_GET:#x}                @ level record, or 0 if the table isn't loaded
    cmp  r0, #0
    beq  no_styler
    ldrh r1, [r0, #4]                @ max energy, start full
    strb r1, [r8, #0x75]
    strb r1, [r8, #0x76]
    ldrh r1, [r0, #6]                @ power
    strh r1, [r8, #0x70]
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
    .ltorg

@ r0 = battle index -> r0 = section number, r1 = its 32-byte record
find_section:
    ldr  r1, =sections
    mov  r2, #{nsect - 1}
fs_loop:
    add  r3, r1, r2, lsl #5
    ldrh r3, [r3]
    cmp  r3, r0
    bls  fs_done
    subs r2, r2, #1
    bne  fs_loop
fs_done:
    add  r1, r1, r2, lsl #5
    mov  r0, r2
    bx   lr

@ keep the selection visible; the list only shows the current section
fix_top:
    push {{r4, r5, lr}}
    ldrh r4, [r6, #0]
    mov  r0, r4
    bl   find_section
    ldr  r12, =vars
    strb r0, [r12, #2]
    ldrh r2, [r1]
    ldrh r3, [r1, #2]
    add  r3, r2, r3
    ldrh r5, [r6, #2]
    cmp  r5, r2
    movlo r5, r2
    cmp  r4, r5
    movlo r5, r4
    add  r0, r5, #{ROWS}
    cmp  r4, r0
    subhs r5, r4, #{ROWS - 1}
    add  r0, r5, #{ROWS}
    cmp  r0, r3
    subhi r5, r3, #{ROWS}
    cmp  r5, r2
    movlt r5, r2
    strh r5, [r6, #2]
    pop  {{r4, r5, pc}}

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
    ldr  r0, =0x020dd700           @ title/demo context pointer
    ldr  r0, [r0]
    cmp  r0, #0
    beq  no_dual3d
    ldr  r1, [r0, #0x1c8]
    bic  r1, r1, #4                @ stop the dual-screen 3D screen flip (as ov28 0x020D8418)
    str  r1, [r0, #0x1c8]
    mov  r1, #0
    str  r1, [r0, #0x65c]
no_dual3d:
    ldr  r0, =0x04000304
    ldrh r1, [r0]
    bic  r1, r1, #0x8000           @ POWCNT1: engine A on the bottom screen
    strh r1, [r0]
    ldr  r0, =0x04000064           @ DISPCAPCNT off: no display capture over the menu
    mov  r1, #0
    str  r1, [r0]
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
    ldr  r1, ={C_SUB_BACKDROP:#x}
    strh r1, [r0]
    bx   lr
    .ltorg

@ rect(r0 x, r1 y, r2 w >= 1, r3 h >= 1, r12 colour); keeps r0-r2, r12.
@ 8 px per stmia (the full-repaint hot spot), then words, then a last pixel.
rect:
    push {{r4-r9, lr}}
    ldr  r4, ={VRAM:#x}
    add  r4, r4, r1, lsl #9
    add  r4, r4, r0, lsl #1
    mov  r5, r12, lsl #16
    orr  r5, r5, r5, lsr #16         @ colour in both halves: 2 px per word
    mov  r8, r5
    mov  r9, r5
    mov  lr, r5
rect_row:
    mov  r6, r4
    mov  r7, r2
    tst  r6, #2
    strhne r12, [r6], #2
    subne r7, r7, #1
    subs r7, r7, #8
    blt  rect_tail
rect_8:
    stmia r6!, {{r5, r8, r9, lr}}
    subs r7, r7, #8
    bge  rect_8
rect_tail:
    adds r7, r7, #8                  @ 0..7 px left
    beq  rect_next
rect_words:
    subs r7, r7, #2
    strge r5, [r6], #4
    bgt  rect_words
    cmn  r7, #1
    strheq r12, [r6]
rect_next:
    add  r4, r4, #512
    subs r3, r3, #1
    bne  rect_row
    pop  {{r4-r9, pc}}

@ rect with the four corner pixels left out (h >= 3): the body without its
@ first and last rows, then those two rows 1 px in from each side
rrect:
    push {{r0-r3, lr}}
    add  r1, r1, #1
    sub  r3, r3, #2
    bl   rect
    ldm  sp, {{r0-r3}}
    add  r0, r0, #1
    sub  r2, r2, #2
    mov  r3, #1
    bl   rect
    ldm  sp, {{r0-r3}}
    add  r0, r0, #1
    sub  r2, r2, #2
    add  r1, r1, r3
    sub  r1, r1, #1
    mov  r3, #1
    bl   rect
    add  sp, sp, #16
    pop  {{pc}}

@ draw_text(r0 x, r1 y, r2 string, r3 colour) -> r0 = end x.
@ Proportional, transparent. Bytes 1..4 switch colour (code_colors) unless
@ r3 has bit 16 set (used for the drop shadow pass).
draw_text:
    push {{r4-r11, lr}}
    ldr  r10, =font
    ldr  r11, =widths
dt_loop:
    ldrb r4, [r2], #1
    cmp  r4, #0
    beq  dt_end
    cmp  r4, #8
    bhs  dt_glyph
    tst  r3, #0x10000
    bne  dt_loop
    ldr  r5, =code_colors
    sub  r4, r4, #1
    add  r5, r5, r4, lsl #1
    ldrh r3, [r5]
    b    dt_loop
dt_glyph:
    sub  r4, r4, #32
    cmp  r4, #{NGLYPH - 1}
    movhi r4, #0
    ldrb r9, [r11, r4]
    add  r4, r10, r4, lsl #3
    ldr  r5, ={VRAM:#x}
    add  r5, r5, r1, lsl #9
    add  r5, r5, r0, lsl #1
    mov  r12, r9, lsr #4
    add  r12, r12, #24               @ glyph row byte -> top of the word, minus its left blank
    and  r9, r9, #15
    add  r0, r0, r9                  @ advance x now; r9 is free in the row loop
    add  r0, r0, #1
    mvn  lr, #0
    mvn  lr, lr, lsr r9              @ mask: the glyph's width in the top bits
    mov  r6, #0
dt_row:
    ldrb r7, [r4, r6]
    ands r7, lr, r7, lsl r12
    beq  dt_rowend
dt_bit:                              @ one iteration per set pixel
    clz  r8, r7
    mov  r9, r8, lsl #1
    strh r3, [r5, r9]
    mov  r9, #0x80000000
    bics r7, r7, r9, lsr r8
    bne  dt_bit
dt_rowend:
    add  r5, r5, #512
    add  r6, r6, #1
    cmp  r6, #8
    blt  dt_row
    b    dt_loop
dt_end:
    pop  {{r4-r11, pc}}

@ text_width(r2 string) -> r0 pixels (r2 preserved)
text_width:
    push {{r2, r4, r11, lr}}
    ldr  r11, =widths
    mov  r0, #0
tw_loop:
    ldrb r4, [r2], #1
    cmp  r4, #0
    beq  tw_end
    cmp  r4, #8
    blo  tw_loop
    sub  r4, r4, #32
    cmp  r4, #{NGLYPH - 1}
    movhi r4, #0
    ldrb r4, [r11, r4]
    and  r4, r4, #15
    add  r0, r0, r4
    add  r0, r0, #1
    b    tw_loop
tw_end:
    cmp  r0, #0
    subne r0, r0, #1
    pop  {{r2, r4, r11, pc}}

@ text with a 1 px drop shadow
text_s:
    push {{r0-r3, lr}}
    add  r0, r0, #1
    add  r1, r1, #1
    ldr  r3, ={C_SHADOW | FIXED:#x}
    bl   draw_text
    ldm  sp, {{r0-r3}}
    bl   draw_text
    add  sp, sp, #16
    pop  {{pc}}

@ right-aligned at r0 (plain / with shadow)
text_r:
    push {{r0-r3, lr}}
    bl   text_width
    ldr  r1, [sp]
    sub  r0, r1, r0
    ldr  r1, [sp, #4]
    ldr  r3, [sp, #12]
    bl   draw_text
    add  sp, sp, #16
    pop  {{pc}}
text_rs:
    push {{r0-r3, lr}}
    bl   text_width
    ldr  r1, [sp]
    sub  r0, r1, r0
    ldr  r1, [sp, #4]
    ldr  r3, [sp, #12]
    bl   text_s
    add  sp, sp, #16
    pop  {{pc}}

@ fmtn(r0 value 0..999, r1 buffer) -> r1 advanced; no leading zeros
fmtn:
    push {{r4, lr}}
    mov  r4, #0
    mov  r2, #0x30
fn100:
    cmp  r0, #100
    subge r0, r0, #100
    addge r2, r2, #1
    bge  fn100
    cmp  r2, #0x30
    strbne r2, [r1], #1
    movne r4, #1
    mov  r2, #0x30
fn10:
    cmp  r0, #10
    subge r0, r0, #10
    addge r2, r2, #1
    bge  fn10
    cmp  r4, #0
    cmpeq r2, #0x30
    strbne r2, [r1], #1
    add  r2, r0, #0x30
    strb r2, [r1], #1
    pop  {{r4, pc}}
    .ltorg

@ redraw by dirty level ([r6, #7], cleared here):
@   bit 0 everything; bit 1 the list (rows, counter, scrollbar);
@   bit 2 only the previously and currently highlighted rows (+ counter, scrollbar).
@ Cursor moves within a page use bit 2, so holding UP/DOWN stays at 60 fps.
redraw:
    push {{r4-r11, lr}}
    ldrb r11, [r6, #7]
    mov  r0, #0
    strb r0, [r6, #7]
    ldr  r12, =vars
    ldrb r0, [r12, #2]
    ldr  r1, =sections
    add  r8, r1, r0, lsl #5          @ r8 = current section record
    tst  r11, #1
    beq  rd_partial
    @ sky gradient (one colour per scanline). Rows crossing the list panel only
    @ get the margins left and right of it: the panel border and interior
    @ (drawn below) cover the rest.
    ldr  r4, ={VRAM:#x}
    ldr  r5, =grad
    mov  r7, #192
g_row:
    ldrh r0, [r5], #2
    orr  r0, r0, r0, lsl #16
    mov  r1, r0
    mov  r2, r0
    mov  r3, r0
    mov  r10, r0
    mov  r11, r0
    mov  r12, r0
    mov  lr, r0
    rsb  r9, r7, #192                @ y
    cmp  r9, #{py + 1}
    blo  g_full
    cmp  r9, #{py + ph - 2}
    bhi  g_full
    stmia r4, {G_LEFT}
    add  r9, r4, #{(px + pw) * 2}
    stmia r9, {G_RIGHT}
    add  r4, r4, #512
    b    g_next
g_full:
    mov  r9, #16
g_px:
    stmia r4!, {{r0-r3, r10, r11, r12, lr}}
    subs r9, r9, #1
    bne  g_px
g_next:
    subs r7, r7, #1
    bne  g_row
    @ header band: navy, logo-yellow and orange rules
    mov  r0, #0
    mov  r1, #0
    mov  r2, #256
    mov  r3, #20
    ldr  r12, ={C['C_HEADER']:#x}
    bl   rect
    mov  r0, #0
    mov  r1, #20
    mov  r2, #256
    mov  r3, #2
    ldr  r12, ={C['C_YELLOW']:#x}
    bl   rect
    mov  r0, #0
    mov  r1, #22
    mov  r2, #256
    mov  r3, #1
    ldr  r12, ={C['C_ORANGE']:#x}
    bl   rect
    mov  r0, #8
    mov  r1, #6
    ldr  r2, =str_title
    ldr  r3, ={C['C_WHITE']:#x}
    bl   text_s
    ldrb r0, [r6, #11]
    ldr  r2, =styler_names
    add  r2, r2, r0, lsl #4
    mov  r0, #248
    mov  r1, #6
    ldr  r3, ={C['C_YELLOW']:#x}
    bl   text_rs
    @ section heading
    mov  r0, #8
    mov  r1, #27
    add  r2, r8, #8
    ldr  r3, ={C['C_WHITE']:#x}
    bl   text_s
    @ list panel outline: a 1 px rounded border plus the interior's four
    @ corner pixels (the interior rrect below leaves those out), i.e. exactly
    @ what a filled outline rrect under the interior would leave visible
    ldr  r12, ={C['C_BORDER']:#x}
    mov  r0, #{px + 1}
    mov  r1, #{py}
    mov  r2, #{pw - 2}
    mov  r3, #1
    bl   rect
    mov  r1, #{py + ph - 1}
    mov  r3, #1
    bl   rect
    mov  r0, #{px}
    mov  r1, #{py + 1}
    mov  r2, #1
    mov  r3, #{ph - 2}
    bl   rect
    mov  r0, #{px + pw - 1}
    mov  r3, #{ph - 2}
    bl   rect
    mov  r0, #{px + 1}
    mov  r3, #1
    bl   rect
    mov  r0, #{px + pw - 2}
    mov  r3, #1
    bl   rect
    mov  r1, #{py + ph - 2}
    mov  r3, #1
    bl   rect
    mov  r0, #{px + 1}
    mov  r3, #1
    bl   rect
    mov  r0, #8
    mov  r1, #180
    ldr  r2, =str_foot
    ldr  r3, ={C['C_WHITE']:#x}
    bl   text_s
    mov  r11, #2
rd_partial:
    tst  r11, #2
    beq  rd_rows
    @ the list: panel interior and every visible row
    mov  r0, #{px + 1}
    mov  r1, #{py + 1}
    mov  r2, #{pw - 2}
    mov  r3, #{ph - 2}
    ldr  r12, ={C['C_PANEL']:#x}
    bl   rrect
    mov  r10, #0
    ldrh r4, [r6, #2]
    mov  r5, #0
rl_loop:
    cmp  r5, #{ROWS}
    bge  rd_common
    add  r7, r4, r5
    bl   draw_row
    add  r5, r5, #1
    b    rl_loop
rd_rows:
    mov  r10, #1
    ldr  r12, =vars
    ldrh r7, [r12, #4]
    bl   draw_row
    ldrh r7, [r6, #0]
    bl   draw_row
rd_common:
    bl   draw_counter
    bl   draw_scroll
    ldr  r12, =vars
    ldrh r0, [r6, #0]
    strh r0, [r12, #4]
    pop  {{r4-r11, pc}}
    .ltorg

@ draw_row(r7 battle index, r10 = 1 to clear the row first; r6 state, r8 section).
@ Does nothing for an index that isn't on screen.
draw_row:
    push {{r4-r11, lr}}
    ldrh r4, [r6, #2]
    subs r5, r7, r4
    bmi  dr_out
    cmp  r5, #{ROWS}
    bge  dr_out
    ldrh r0, [r8]
    ldrh r1, [r8, #2]
    add  r0, r0, r1
    cmp  r7, r0
    bge  dr_out
    mov  r11, r5, lsl #2
    add  r11, r11, r5, lsl #3
    add  r11, r11, #{ROW_Y0}
    cmp  r10, #0
    beq  dr_noclear
    mov  r0, #8
    mov  r1, r11
    mov  r2, #228
    mov  r3, #{ROW_H}
    ldr  r12, ={C['C_PANEL']:#x}
    bl   rect
dr_noclear:
    ldrh r0, [r6, #0]
    cmp  r7, r0
    bne  dr_text
    mov  r0, #9
    mov  r1, r11
    mov  r2, #226
    mov  r3, #{ROW_H}
    ldr  r12, ={C['C_YELLOW']:#x}
    bl   rrect
    mov  r0, #10
    add  r1, r11, #{ROW_H - 1}
    mov  r2, #224
    mov  r3, #1
    ldr  r12, ={C['C_ORANGE']:#x}
    bl   rect
    mov  r0, #12
    add  r1, r11, #2
    ldr  r2, =str_cursor
    ldr  r3, ={C['C_ORANGE']:#x}
    bl   draw_text
dr_text:
    ldr  r2, =battle_table
    add  r2, r2, r7, lsl #6
    mov  r0, #{NAME_X}
    add  r1, r11, #2
    ldr  r3, ={C['C_TEXT']:#x}
    bl   draw_text
    ldr  r2, =battle_table
    add  r2, r2, r7, lsl #6
    add  r2, r2, #21
    mov  r0, #{TAG_RIGHT}
    add  r1, r11, #2
    ldr  r3, ={C['C_MUTED']:#x}
    bl   text_r
dr_out:
    pop  {{r4-r11, pc}}

@ position within the section ("34/189"), right-aligned on the section bar;
@ its background is restored from the gradient first
draw_counter:
    push {{r4, r5, lr}}
    ldr  r5, =grad
    add  r5, r5, #52
    mov  r4, #26
dc_clear:
    ldrh r12, [r5], #2
    mov  r0, #176
    mov  r1, r4
    mov  r2, #80
    mov  r3, #1
    bl   rect
    add  r4, r4, #1
    cmp  r4, #37
    blt  dc_clear
    sub  sp, sp, #16
    ldrh r0, [r6, #0]
    ldrh r1, [r8]
    sub  r0, r0, r1
    add  r0, r0, #1
    mov  r1, sp
    bl   fmtn
    mov  r0, #0x2f
    strb r0, [r1], #1
    ldrh r0, [r8, #2]
    bl   fmtn
    mov  r0, #0
    strb r0, [r1]
    mov  r0, #248
    mov  r1, #27
    mov  r2, sp
    ldr  r3, ={C['C_PALE']:#x}
    bl   text_rs
    add  sp, sp, #16
    pop  {{r4, r5, pc}}

@ scrollbar (only when the section doesn't fit on one screen)
draw_scroll:
    push {{r4, r5, lr}}
    ldr  r4, [r8, #4]
    cmp  r4, #0
    beq  ds_out
    mov  r0, #{tx}
    mov  r1, #{ty}
    mov  r2, #{tw}
    mov  r3, #{th}
    ldr  r12, ={C['C_TRACK']:#x}
    bl   rect
    ldrh r0, [r6, #0]
    ldrh r5, [r8]
    sub  r0, r0, r5
    mul  r1, r0, r4
    mov  r1, r1, lsr #16
    add  r1, r1, #{ty}
    mov  r0, #{tx}
    mov  r2, #{tw}
    mov  r3, #{THUMB_H}
    ldr  r12, ={C['C_THUMB']:#x}
    bl   rect
ds_out:
    pop  {{r4, r5, pc}}
    .ltorg

    .align 2
@ menu-only scratch (reset whenever ov28 reloads): +0 fade frames left,
@ +1 fade action (0 in, 1 close, 2 launch), +2 current section,
@ +4 u16 index highlighted by the last redraw
vars:
    .byte 0, 0, 0, 0, 0, 0, 0, 0
code_colors:
{data(b"".join(struct.pack("<H", c) for c in CODE_COLORS))}
    .align 2
str_title:
{cstr(title)}
str_foot:
{cstr(foot)}
str_cursor:
{cstr(chr(0x81))}
    .align 2
styler_names:
{data(b"".join(s.ljust(16, b"\0") for s in styler_names))}
styler_table:
    .byte {", ".join(str(lv) for lv in STYLER_LEVELS)}
    .align 2
sections:
{data(bytes(sect_bin))}
grad:
{data(grad)}
font:
{data(fnt)}
widths:
{data(metrics)}
    .align 2
battle_table:
"""
    ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code, _ = ks.asm(asm, cave)
    code = bytearray(code)
    assert len(code) % 4 == 0
    head = bytes(code)
    # Keystone mis-assembles some conditional BL to forward labels as a
    # branch-to-self; refuse any B/BL whose offset is -2 words (to itself).
    for off in range(0, len(head), 4):
        w = struct.unpack_from("<I", head, off)[0]
        if (w & 0x0E000000) == 0x0A000000 and (w & 0xFFFFFF) == 0xFFFFFE and (w >> 28) != 0xF:
            raise SystemExit(f"assembler produced a self-branch at {cave + off:#x}: {w:#010x}")
    table = bytearray()
    # record: name[21] | tag[11] @21 | count u8 @32 | bgm u8 @33 | arena u8 @34 | flags u8 @35 |
    #         ids u16[8] @36 | +0x154 u16 @52 | +0x156 u16 @54 | +0x150 u8 @56 | +0x140 u16 @58
    for i, e in enumerate(blist):
        rec = bytearray(64)
        name, tag = (s.encode("latin-1") for s in labels[i])
        assert len(name) < 21 and len(tag) < 11, (name, tag)
        assert text_px(name, metrics) <= NAME_MAX_PX and NAME_X + text_px(name, metrics) + 6 + text_px(tag, metrics) <= TAG_RIGHT, (name, tag)
        rec[:len(name)] = name
        rec[21:21 + len(tag)] = tag
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
            w.writerow([i, entry_text(i, *(t.replace("\x83", "x").replace("\x82", "e") for t in labels[i])),
                        " ".join(map(str, e["ids"])),
                        " | ".join(ranger_ids.name_of(x) for x in e["ids"]), e["bgm"], e["arena"],
                        e["flags"], e["s150"], e["v154"], e["v156"], e["v140"], e["map"], e["arena_from"]])
    end = cave + len(cave_bytes)
    print(f"cave {cave:#010x}-{end:#010x}: {len(head) - len(fnt)} bytes code+strings, font {len(fnt)}, {n} battles")
    assert end < 0x0212CFC0, "cave would overlap the heap"
    print(f"wrote {out/'capture_select_patch.json'} and capture_select_list.csv")


# Title menu (CDemoMenuState, ov28): the third button (selection 2) was
# "Ranger Net" (scene 0x2B; the online service is closed). Its handler at
# 0x020D96B8 is replaced with: set the reopen counter (STATE+10 = 1) and
# reload the title/demo scene (next scene = 0x25, like New Game sets 0x1C), so the
# fresh title opens the menu ~32 frames later, exactly as after a battle.
# (Opening it in place left the title's fade-out darkening the screen.) The label is changed in the text archive by
# play_capture_select.sh / tools/capture_select/relabel_title_button.sh.
ORIG_DRAW = 0x020D21C0                          # CDemoScene / CGameTitleScene vtable slot 3
RANGER_NET_HANDLER = 0x020D96B8
RANGER_NET_BYTES = bytes.fromhex("d00195e5000050e32b00a0b3d00185b5")
MENU_STATE_DONE = 0x020D972C


def title_button_patches(ks, at):
    image = OV_FILE.read_bytes()
    off = RANGER_NET_HANDLER - 0x020D1B80
    assert image[off:off + 16] == RANGER_NET_BYTES, "unexpected Ranger Net handler"
    # Draw (vtable slot 3) wrapper: while the menu is open, skip the title's
    # Draw (3D render + SwapBuffers + dual-screen capture), so nothing but the
    # menu touches the display regardless of emulator timing.
    draw, _ = ks.asm(f"""
        ldr   r12, ={STATE:#x}
        ldrb  r12, [r12, #6]
        cmp   r12, #0
        bxne  lr
        b     {ORIG_DRAW:#x}
    """, at)
    draw = bytes(draw)
    draw_at = at
    at += len(draw)
    code, _ = ks.asm(f"""
        ldr   r1, ={STATE:#x}
        mov   r0, #1
        strb  r0, [r1, #10]
        ldr   r0, [r5, #0x1d0]
        cmp   r0, #0
        movlt r0, #{MENU_EXIT_SCENE:#x}
        strlt r0, [r5, #0x1d0]
        bx    lr
    """, at)
    hook, _ = ks.asm(f"bl {at:#x}\nb {MENU_STATE_DONE:#x}", RANGER_NET_HANDLER)
    return [
        {"target": f"ov{OV:03d}", "append_after_bss": draw.hex(),
         "comment": f"Draw wrapper: skip title Draw while the menu is open ({draw_at:#010x})"},
        {"target": f"ov{OV:03d}", "append_after_bss": bytes(code).hex(),
         "comment": f"title-menu Capture Select button handler ({at:#010x})"},
    ] + [
        {"target": f"ov{OV:03d}", "addr": f"{a + 4:#010x}", "expect": struct.pack('<I', ORIG_DRAW).hex(),
         "hex": struct.pack("<I", draw_at).hex(), "comment": "Draw -> menu-aware wrapper"}
        for a in VT_SLOT2
    ] + [
        {"target": f"ov{OV:03d}", "addr": f"{RANGER_NET_HANDLER:#010x}", "expect": RANGER_NET_BYTES[:8].hex(),
         "hex": bytes(hook).hex(), "comment": "Ranger Net button -> Capture Select"},
    ]


def skip_browser_patches(ks):
    """Menu battles must not register into the Browser (save data): in the
    CCaptureScene state switch, turn a request for AddBrowser (10) or
    CheckRelease (11) into exit (7) when the capture's return scene
    (request block 0x020B7AB8 + 8 = CaptureSetup+0x144) is the title/demo scene (RETURN_SCENE).
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
