#!/usr/bin/env python3
"""Merge every known capture source into one database CSV.

Sources (tracked snapshots, regenerate with the named tools):
  sky      research/capture/capture_candidates_2026-10-04.csv   (analyze_capture_scripts.py)
  scripted research/capture/field_capture_sequences_2026-11-17.csv (analyze_field_captures.py)
  wild     research/capture/wild_spawns_2026-11-17.csv          (extract_wild_spawns.py)

One row per capture TARGET per trigger. `definition_key` groups rows that
capture the same Ranger Pokemon ID; scripted rows whose label is Mnn_ss_* are
linked to wild placements on map mNNN_SS with the same ID ("linked_wild").
"""
from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "research" / "capture"
NAMES = ROOT / "work" / "localization" / "json" / "0268.json"


def read(name):
    with open(CAP / name, newline="") as fh:
        return list(csv.DictReader(fh))


def label_map(label):
    m = re.match(r"^M(\d+)_(\d+)_", label or "")
    return f"m{int(m.group(1)):03d}_{int(m.group(2)):02d}" if m else ""


def main():
    names = {}
    if NAMES.exists():
        names = {int(k): v for k, v in json.loads(NAMES.read_text()).items() if k.isdigit()}
    nm = lambda i: names.get(i, "") if i is not None and i <= 496 else ("(Ranger-specific)" if i else "")

    out = []
    for r in read("capture_candidates_2026-10-04.csv"):
        out.append({
            "source": "sky_1C10", "ranger_id": "", "name": "",
            "map": "", "trigger": f"script@{r['acf_offset']}+{r['launch_offset']}",
            "label": "", "x": "", "z": "",
            "params": f"{r['setup']}({r['setup_args']}) 1C35({r['1c35_args']}) 1C36({r['1c36_args']})",
            "note": "sky capture via 1C10 -> CSkyCaptureBeforeState; target id not yet resolved",
        })

    wild = read("wild_spawns_2026-11-17.csv")
    wild_index = collections.defaultdict(list)
    for w in wild:
        for m in (w["map"] or "").split():
            wild_index[(m, int(w["dex"]))].append(w)

    for r in read("field_capture_sequences_2026-11-17.csv"):
        if r["started"] != "True":
            continue
        for t in filter(None, r["targets"].split(" | ")):
            rid = int(t.split(":")[0].split(",")[0])
            mp = label_map(r["label"])
            linked = wild_index.get((mp, rid), [])
            out.append({
                "source": "field_script", "ranger_id": rid, "name": nm(rid),
                "map": mp, "trigger": f"script@{r['acf_offset']}+{r['start_off']}",
                "label": r["label"],
                "x": linked[0]["x"] if linked else "", "z": linked[0]["z"] if linked else "",
                "params": r["params"],
                "note": f"linked_wild={len(linked)}" if linked else "",
            })

    for w in wild:
        rid = int(w["dex"])
        out.append({
            "source": "wild_placement", "ranger_id": rid, "name": nm(rid),
            "map": w["map"], "trigger": f"placement entry {w['acf_entry']}#{w['index']}",
            "label": "", "x": w["x"], "z": w["z"],
            "params": f"f2={w['f2']} f3={w['f3']} f8..f15={','.join(w[f'f{k}'] for k in range(8, 16))}",
            "note": "" if w["map"] else "package not referenced by MPPS",
        })

    for row in out:
        row["definition_key"] = f"id{row['ranger_id']}" if row["ranger_id"] != "" else "unresolved"
    fields = ["definition_key", "source", "ranger_id", "name", "map", "label", "trigger", "x", "z", "params", "note"]
    path = CAP / "capture_database.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(out, key=lambda r: (r["source"], str(r["map"]), str(r["ranger_id"]))))

    by_src = collections.Counter(r["source"] for r in out)
    ids = {r["ranger_id"] for r in out if r["ranger_id"] != ""}
    dex = {i for i in ids if i <= 493}
    print(f"rows: {len(out)} {dict(by_src)}")
    print(f"distinct Ranger IDs: {len(ids)} (National Dex 1-493: {len(dex)}, Ranger-specific: {len(ids) - len(dex)})")
    linked = sum(1 for r in out if r["note"].startswith("linked_wild"))
    print(f"scripted targets linked to a wild placement on the same map: {linked}")
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
