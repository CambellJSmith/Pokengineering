#!/usr/bin/env python3
"""Sweep every script stream for FIELD-side capture setup commands (group 3).

Field VM command group 3 is registered by CFieldScene (ov2 0x020D2F80) with
table ov2:0x02125860 (handler = table[index]). Handlers 0xA2..0xB2 manipulate
the resident capture-setup struct at 0x020B797C (see docs/scene_system.md):

  0x0CA2 CAP_CLEAR            0x020418D4(setup)
  0x0CA5 CAP_ADD(id)          0x02041998(setup, id, 0, 0, 0)
  0x0CA6 CAP_ADD2(id, a)      0x020419D0(setup, id, a)  -> entry.u16 +6 = a
  0x0CA7 CAP_BGM(v)           setup+0x13C = v   (BGM kind 0..10, ov3 0x020D351C)
  0x0CA8 CAP_FLAG2            setup+0x142 |= 2
  0x0CA9 CAP_156(v)           setup+0x156 = v
  0x0CAA CAP_154(v)           setup+0x154 = v
  0x0CAB CAP_FLAG1            setup+0x142 |= 1
  0x0CAC CAP_150(v)           setup+0x150 = v
  0x0CAD CAP_START            field -> state singleton 0x02128C10
  0x0CAE CAP_START_F(v)       setup+0x142 |= 1, same start, field+0x232C = v
  0x0CAF CAP_RESULT           returns setup+0x15C
  0x0CB0 CAP_ARENA(v)         setup+0x13E = v
  0x0CB1 CAP_140(v)           setup+0x140 = v
  0x0CB2 CAP_FLAG4            setup+0x142 |= 4

Arguments: the VM pops args so args[0] is the LAST value pushed
(PUSH a; PUSH b; CALL argc=2 -> handler sees args = (b, a)). This script prints
args in handler order.
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import analyze_capture_scripts as acs  # noqa: E402

NAMES = {
    0x0CA2: "CAP_CLEAR", 0x0CA5: "CAP_ADD", 0x0CA6: "CAP_ADD2", 0x0CA7: "CAP_BGM",
    0x0CA8: "CAP_FLAG2", 0x0CA9: "CAP_156", 0x0CAA: "CAP_154", 0x0CAB: "CAP_FLAG1",
    0x0CAC: "CAP_150", 0x0CAD: "CAP_START", 0x0CAE: "CAP_START_F", 0x0CAF: "CAP_RESULT",
    0x0CB0: "CAP_ARENA", 0x0CB1: "CAP_140", 0x0CB2: "CAP_FLAG4",
}


B40 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_-/"
NAME_FILE = ROOT / "work" / "localization" / "json" / "0268.json"


def b40_word(v):
    out = ""
    for _ in range(6):
        c = v % 40
        v //= 40
        out = ("" if c == 0 else B40[c - 1]) + out
    return out


def symbols(decoded):
    """Script symbol table: [u32 code_end, u32 hdr+8) of {u32 k0, u32 k1, u32 addr/4}.

    Names are base-40 packed 6 chars per word (ARM9 0x020667E0); case is lost
    (the game maps a-z and A-Z to the same values)."""
    start, end = acs.u32(decoded, 4), acs.u32(decoded, 8)
    out = []
    if not (0 < start <= end <= len(decoded)) or (end - start) % 12:
        return out
    for off in range(start, end, 12):
        k0, k1, addr = struct.unpack_from("<III", decoded, off)
        out.append((addr * 4, b40_word(k0) + b40_word(k1)))
    return sorted(out)


def label_for(syms, off):
    best = ""
    for addr, name in syms:
        if addr <= off:
            best = name
        else:
            break
    return best


def pokemon_names():
    if NAME_FILE.exists():
        return {int(k): v for k, v in json.loads(NAME_FILE.read_text()).items() if k.isdigit()}
    return {}


def fmt_args(call):
    if call["args"] is None:
        return "?"
    return ",".join("?" if a is None else str(a) for a in call["args"])


def build_sequences(calls):
    """Group CAP_* calls between a CAP_CLEAR and the next CAP_START*."""
    seqs, cur = [], None
    for c in calls:
        sel = c["selector"]
        if sel not in NAMES:
            continue
        if sel == 0x0CA2:
            cur = {"clear_off": c["off"], "calls": [c]}
            continue
        if cur is None:
            cur = {"clear_off": None, "calls": []}
        cur["calls"].append(c)
        if sel in (0x0CAD, 0x0CAE):
            seqs.append(cur)
            cur = None
    if cur and cur["calls"]:
        seqs.append(cur)
    return seqs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "capture" / "generated")
    args = ap.parse_args()

    acf, meta = acs.load_acf(None)
    print(meta["source"])
    scripts = acs.scan(acf, meta, 500)
    print(f"script streams: {len(scripts)}")

    names = pokemon_names()
    if not names:
        print("note: run tools/extract_localization.sh to add Pokemon names (file 0268)")

    def name_targets(q):
        out = []
        for c in q["calls"]:
            if c["selector"] not in (0x0CA5, 0x0CA6) or not c["args"]:
                continue
            pid = c["args"][0]
            out.append(f"{pid}:{names.get(pid, '?')}" if names else str(pid))
        return " | ".join(out)

    rows, seq_rows = [], []
    for s in scripts:
        caps = [c for c in s["all_calls"] if c["selector"] in NAMES]
        if not caps:
            continue
        decoded, _ = acs.lz10(acf, s["acf_offset"], len(acf))
        syms = symbols(decoded)
        for c in caps:
            rows.append({
                "script": s["script_number"], "acf_offset": f"0x{s['acf_offset']:X}",
                "insn_off": f"0x{c['off']:X}", "label": label_for(syms, c["off"]), "selector": f"0x{c['selector']:04X}",
                "name": NAMES[c["selector"]], "argc": c["argc"], "args": fmt_args(c),
            })
        for q in build_sequences(s["all_calls"]):
            params = {NAMES[c["selector"]]: fmt_args(c) for c in q["calls"]
                      if c["selector"] not in (0x0CA5, 0x0CA6, 0x0CA2)}
            started = any(c["selector"] in (0x0CAD, 0x0CAE) for c in q["calls"])
            seq_rows.append({
                "script": s["script_number"], "acf_offset": f"0x{s['acf_offset']:X}",
                "label": label_for(syms, q["calls"][-1]["off"]),
                "start_off": f"0x{q['calls'][-1]['off']:X}", "started": started,
                "targets": name_targets(q),
                "params": " ".join(f"{k}={v}" for k, v in params.items()),
            })

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "field_capture_calls.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["script"])
        w.writeheader(); w.writerows(rows)
    with open(args.out / "field_capture_sequences.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(seq_rows[0]) if seq_rows else ["script"])
        w.writeheader(); w.writerows(seq_rows)

    from collections import Counter
    cnt = Counter(r["name"] for r in rows)
    print("field capture command counts:", dict(sorted(cnt.items())))
    print(f"scripts using group-3 capture commands: {len({r['script'] for r in rows})}")
    print(f"setup sequences: {len(seq_rows)}  (started: {sum(r['started'] for r in seq_rows)})")
    print(f"wrote {args.out/'field_capture_calls.csv'} and field_capture_sequences.csv")


if __name__ == "__main__":
    main()
