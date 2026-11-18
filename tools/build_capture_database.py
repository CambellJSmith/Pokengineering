#!/usr/bin/env python3
"""Merge every known capture source into one database CSV.

Sources (tracked snapshots, regenerate with the named tools):
  sky      research/capture/capture_candidates_2026-10-04.csv   (analyze_capture_scripts.py)
  scripted research/capture/field_capture_sequences_2026-11-17.csv (analyze_field_captures.py)
  wild     research/capture/wild_spawns_2026-11-17.csv          (extract_wild_spawns.py)

One row per capture TARGET per trigger. `definition_key` groups rows that
capture the same Ranger ID (Ranger ID -> Dex via tools/ranger_ids.py); scripted rows whose label is Mnn_ss_* are
linked to wild placements on map mNNN_SS with the same ID ("linked_wild").
"""
from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ranger_ids  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "research" / "capture"


def read(name):
    with open(CAP / name, newline="") as fh:
        return list(csv.DictReader(fh))


ACF = ROOT / "work" / "game_acf" / "source_data_game_us.acf"
MPPS = ROOT / "work" / "game_acf" / "archive" / "2482.MPPS"


def script_maps():
    """ACF byte offset of a script -> set of single-player maps whose map script
    it is. Map script resource = MPPS rec+0x0A + 8 (ov2 0x020D6800;
    multiplayer uses + 0xEE). Resource ID == ACF entry index."""
    import struct
    if not (ACF.exists() and MPPS.exists()):
        return {}
    d = ACF.read_bytes()
    base, n = struct.unpack_from("<II", d, 8)
    entry_off = {}
    for i in range(n):
        o = struct.unpack_from("<I", d, 0x20 + 12 * i)[0]
        if o != 0xFFFFFFFF:
            entry_off[i] = base + o
    m = MPPS.read_bytes()
    rs, cnt = struct.unpack_from("<II", m, 4)
    out = collections.defaultdict(set)
    for i in range(cnt):
        r = m[0x10 + rs * i:0x10 + rs * (i + 1)]
        v = struct.unpack_from("<H", r, 0xA)[0]
        if v != 0xFFFF and (v + 8) in entry_off:
            out[entry_off[v + 8]].add(f"m{r[1]:03d}_{r[2]:02d}")
    return out


def chapter_start_maps():
    """chapter number -> start map, from 2483.CHPT (resource 0x9B3 -> 0x020BD3F4):
    12-byte records {u16 mppsIndex, u8, u8, s16 x, s16 z, u8 chapter, ...};
    the field builds script label "c%03d_start" from +8 (ov2 0x020E3850)."""
    import struct
    chpt = ROOT / "work" / "game_acf" / "archive" / "2483.CHPT"
    if not (chpt.exists() and MPPS.exists()):
        return {}
    c, m = chpt.read_bytes(), MPPS.read_bytes()
    rs, n = struct.unpack_from("<II", c, 4)
    mrs = struct.unpack_from("<I", m, 4)[0]
    out = {}
    for i in range(n):
        idx, _, _, _, _, chap = struct.unpack_from("<HBBhhB", c, 0x10 + rs * i)
        r = m[0x10 + mrs * idx:0x10 + mrs * (idx + 1)]
        out.setdefault(chap, f"m{r[1]:03d}_{r[2]:02d}")
    return out


def label_map(label):
    m = re.match(r"^M(\d+)_(\d+)_", label or "")
    return f"m{int(m.group(1)):03d}_{int(m.group(2)):02d}" if m else ""


ARCHIVE = ROOT / "work" / "game_acf" / "archive"


def _table(name):
    """Standard Guardian Signs data table: magic, u32 recsize, u32 count, pad."""
    import struct
    p = ARCHIVE / name
    if not p.exists():
        return 0, []
    d = p.read_bytes()
    rs, n = struct.unpack_from("<II", d, 4)
    return rs, [d[0x10 + rs * i:0x10 + rs * (i + 1)] for i in range(n)]


def extra_sources(nm):
    """Capture sources outside the field scripts / map placements.

    sky_enemy : 9529.SPKD (resource 0x2539 -> 0x020BD494), 16-byte records,
                +4 = Ranger ID. Spawned by sky command 1C76(actor, spkdIndex, ...)
                (ov3 0x02103D64); the sky object adds itself to the sky capture
                list via 0x02111C24 -> 0x02116774.
    coop      : 2488.MPCP (resource 0x9B8 -> 0x020BD4C0), 48-byte records,
                +0 = Ranger ID: multiplayer/co-op capture Pokemon (ov26/ov3).
    tutorial  : capture scripts 0x5E1 + n (ACF 1506-1512), started by field
                scripts with CAP_CLEAR; CAP_150=n; CAP_START. CCaptureContext::Init
                (ov3 0x020D20BC) loads them when CaptureSetup+0x150 > 0; they
                run "The Capture tutorial has begun." and spawn their own targets.
    """
    import struct
    rows = []
    _, spkd = _table("9529.SPKD")
    for i, r in enumerate(spkd):
        rid = struct.unpack_from("<H", r, 4)[0]
        rows.append({"source": "sky_enemy", "ranger_id": rid, "name": nm(rid), "map": "",
                     "label": "SKY", "trigger": f"SPKD #{i}", "x": "", "z": "",
                     "params": "", "note": "free-flight sky enemy (1C76)"})
    _, mpcp = _table("2488.MPCP")
    for i, r in enumerate(mpcp):
        rid = struct.unpack_from("<H", r, 0)[0]
        rows.append({"source": "coop", "ranger_id": rid, "name": nm(rid), "map": "",
                     "label": "CO-OP", "trigger": f"MPCP #{i}", "x": "", "z": "",
                     "params": "", "note": "multiplayer capture data"})
    for n in range(1, 8):
        rows.append({"source": "tutorial", "ranger_id": "", "name": f"Capture tutorial {n}",
                     "map": "", "label": f"TUTORIAL{n}", "trigger": f"capture script {0x5E1 + n}",
                     "x": "", "z": "", "params": f"CAP_150={n}",
                     "note": "count 0; the capture script spawns the targets"})
    return rows


def main():
    nm = ranger_ids.name_of

    out = []
    for r in read("capture_candidates_2026-10-04.csv"):
        args = [int(a.strip(), 0) for a in r["setup_args"].split(",")]
        # handler order: 1C12(id, b, c, x, z) / 1C54(actor, id, b) -> writer 0x02116774
        rid = args[0] if r["setup"] == "0x1C12" else args[1]
        out.append({
            "source": "sky_1C10", "ranger_id": rid, "name": nm(rid),
            "map": "", "trigger": f"script@{r['acf_offset']}+{r['launch_offset']}",
            "label": "", "x": "", "z": "",
            "params": f"{r['setup']}({r['setup_args']}) 1C35({r['1c35_args']}) 1C36({r['1c36_args']})",
            "note": "sky capture via 1C10 -> CSkyCaptureBeforeState",
        })

    smaps = script_maps()
    chapters = chapter_start_maps()
    wild = read("wild_spawns_2026-11-17.csv")
    wild_index = collections.defaultdict(list)
    by_id = collections.defaultdict(list)
    for w in wild:
        by_id[int(w["ranger_id"])].append(w)
    for w in wild:
        for m in (w["map"] or "").split():
            wild_index[(m, int(w["ranger_id"]))].append(w)

    for r in read("field_capture_sequences_2026-11-17.csv"):
        if r["started"] != "True":
            continue
        for t in filter(None, r["targets"].split(" | ")):
            rid = int(t.split(":")[0].split(",")[0])
            mp = label_map(r["label"])
            owner = smaps.get(int(r["acf_offset"], 16), set())
            if not mp and len(owner) == 1:
                mp = next(iter(owner))      # the script is this map's map script
            chap_map = ""
            mc = re.match(r"^C(\d+)_", r["label"] or "")
            if mc:
                chap_map = chapters.get(int(mc.group(1)), "")
            linked = wild_index.get((mp, rid), [])
            how = "same_map"
            if not linked:
                # An exact Ranger ID placed on
                # exactly one single-player map gives a CANDIDATE map only.
                cands = [w for w in by_id.get(rid, []) if w["set"] == "single" and w["map"]]
                maps = {w["map"] for w in cands}
                if len(maps) == 1:
                    # weak: IDs are reused across maps, so only a candidate
                    linked, how = cands, "unique_id"
            out.append({
                "source": "field_script", "ranger_id": rid, "name": nm(rid),
                "map": mp, "candidate_map": linked[0]["map"] if linked and how == "unique_id" else "",
                "chapter_start_map": chap_map,
                "trigger": f"script@{r['acf_offset']}+{r['start_off']}",
                "label": r["label"],
                "x": linked[0]["x"] if linked else "", "z": linked[0]["z"] if linked else "",
                "params": r["params"],
                "note": f"linked_wild={len(linked)} ({how})" if linked else "",
            })

    for w in wild:
        rid = int(w["ranger_id"])
        out.append({
            "source": "wild_placement", "ranger_id": rid, "name": nm(rid),
            "map": w["map"], "trigger": f"placement entry {w['acf_entry']}#{w['index']}",
            "label": "", "x": w["x"], "z": w["z"],
            "params": f"f2={w['f2']} f3={w['f3']} f8..f15={','.join(w[f'f{k}'] for k in range(8, 16))}",
            "note": "" if w["map"] else f"{w['set']} placement set (map from runtime quest data)",
        })

    out.extend(extra_sources(nm))

    for row in out:
        row["definition_key"] = f"id{row['ranger_id']}" if row["ranger_id"] != "" else "unresolved"
    for row in out:
        row["dex"] = ranger_ids.dex_of(row["ranger_id"]) if row["ranger_id"] != "" else ""
    for row in out:
        row.setdefault("candidate_map", "")
        row.setdefault("chapter_start_map", "")
    fields = ["definition_key", "source", "ranger_id", "dex", "name", "map", "candidate_map", "chapter_start_map", "label", "trigger", "x", "z", "params", "note"]
    path = CAP / "capture_database.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(out, key=lambda r: (r["source"], str(r["map"]), str(r["ranger_id"]))))

    by_src = collections.Counter(r["source"] for r in out)
    ids = {r["ranger_id"] for r in out if r["ranger_id"] != ""}
    dex = {r["dex"] for r in out if isinstance(r["dex"], int) and r["dex"] < 900}
    print(f"rows: {len(out)} {dict(by_src)}")
    print(f"distinct Ranger IDs: {len(ids)}; distinct species (National Dex): {len(dex)}")
    same = sum(1 for r in out if "(same_map)" in r["note"])
    cand = sum(1 for r in out if "(unique_id)" in r["note"])
    print(f"scripted targets linked to a placement on their labelled map: {same}; weak candidate maps: {cand}")
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
