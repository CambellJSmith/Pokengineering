#!/usr/bin/env python3
"""Bulk capture-script analyzer for Pokemon Ranger: Guardian Signs (US/B3RE).

This tool scans the canonical raw NitroFS data_game_us.acf (FAT file ID 0x22),
decodes embedded LZ10 script streams on VM instruction boundaries, and reports
all proven script-side requests for state 3 -> CSkyCaptureBeforeState.

Important: do not trust a convenient local data/data_game_us.acf blindly. During
research a same-sized, byte-different representation produced the false result
"280 scripts / 0 capture transitions". By default this script extracts the raw
ACF directly from fat.bin + fat_data.bin + _file_IDs.txt and validates the known
Spearow stream signature at ACF +0xF844C before scanning.
"""
from __future__ import annotations

import argparse
import csv
import json
import mmap
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from decode_script_vm import decode, direct_call_args, describe
from extract_nitrofs_file import (
    find_file_id,
    infer_payload_base,
    parse_fat,
    parse_file_ids,
)

ACF_NITRO_PATH = "data/data_game_us.acf"
ACF_FAT_ID = 0x22
SPEAROW_ACF_OFFSET = 0xF844C
SPEAROW_LZ10_HEADER = bytes.fromhex("10 b1 27 00")

KNOWN = {
    0x1C10: "REQUEST_SKY_CAPTURE_BEFORE_STATE",
    0x1C11: "POLL_SKY_CAPTURE_BEFORE_PENDING",
    0x1C12: "CAPTURE_BEFORE_RECORD_A",
    0x1C30: "CAPTURE_BEFORE_INDEX_CONFIG",
    0x1C35: "CAPTURE_BEFORE_MANAGER_CONFIG",
    0x1C36: "ASSOCIATED_ASYNC_OPERATION",
    0x1C54: "CAPTURE_BEFORE_RECORD_B",
}
SETUP = {0x1C12, 0x1C54}
CONFIG = {0x1C30, 0x1C35}
INTERESTING = set(KNOWN)


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def fmt(v):
    if v is None:
        return "?"
    if -9 <= v <= 9:
        return str(v)
    return f"0x{v & 0xffffffff:X}"


def lz10(data, start, limit):
    if start + 4 > limit or data[start] != 0x10:
        return None
    size = data[start + 1] | (data[start + 2] << 8) | (data[start + 3] << 16)
    if not (0x20 <= size <= 0x400000):
        return None
    pos = start + 4
    out = bytearray()
    try:
        while len(out) < size:
            if pos >= limit:
                return None
            flags = data[pos]
            pos += 1
            for bit in range(7, -1, -1):
                if len(out) >= size:
                    break
                if not (flags & (1 << bit)):
                    if pos >= limit:
                        return None
                    out.append(data[pos])
                    pos += 1
                else:
                    if pos + 2 > limit:
                        return None
                    b1, b2 = data[pos], data[pos + 1]
                    pos += 2
                    length = (b1 >> 4) + 3
                    disp = (((b1 & 0x0F) << 8) | b2) + 1
                    if disp > len(out):
                        return None
                    for _ in range(length):
                        out.append(out[-disp])
                        if len(out) >= size:
                            break
    except (IndexError, ValueError):
        return None
    return bytes(out), pos - start


def looks_like_script(decoded):
    if len(decoded) < 0x20:
        return False
    try:
        a, b, c, d = [u32(decoded, x) for x in (0, 4, 8, 12)]
    except struct.error:
        return False
    return a == 0x20 and a <= b <= c <= d <= len(decoded) and b > a


def validate_acf(data, source):
    end = SPEAROW_ACF_OFFSET + len(SPEAROW_LZ10_HEADER)
    if end > len(data):
        raise SystemExit(f"ACF is too small for known Spearow signature: {source}")
    got = data[SPEAROW_ACF_OFFSET:end]
    if got != SPEAROW_LZ10_HEADER:
        raise SystemExit(
            "Refusing to scan an unvalidated data_game_us.acf representation.\n"
            f"Source: {source}\n"
            f"Expected at +0x{SPEAROW_ACF_OFFSET:X}: {SPEAROW_LZ10_HEADER.hex(' ')}\n"
            f"Actual: {got.hex(' ')}\n"
            "Omit the ACF argument to extract the canonical raw FAT file ID 0x22."
        )


def load_acf(explicit):
    if explicit:
        p = explicit.resolve()
        data = p.read_bytes()
        validate_acf(data, str(p))
        return data, {"source": str(p), "rom_start": None}

    fat_path = ROOT / "fat.bin"
    ids_path = ROOT / "_file_IDs.txt"
    payload_path = ROOT / "fat_data.bin"
    for p in (fat_path, ids_path, payload_path):
        if not p.exists():
            raise SystemExit(f"Missing required repository input: {p}")

    fat = parse_fat(fat_path)
    ids = parse_file_ids(ids_path, len(fat))
    file_id = find_file_id(ids, ACF_NITRO_PATH)
    if file_id != ACF_FAT_ID:
        raise SystemExit(
            f"Expected {ACF_NITRO_PATH} at FAT ID 0x{ACF_FAT_ID:X}; got 0x{file_id:X}"
        )

    with payload_path.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            base, sig_score, bounds_score = infer_payload_base(mm, fat, ids)
            rom_start, rom_end = fat[file_id]
            start, end = rom_start - base, rom_end - base
            if not (0 <= start <= end <= len(mm)):
                raise SystemExit("Computed raw ACF slice is outside fat_data.bin")
            data = bytes(mm[start:end])

    source = (
        f"fat_data.bin FAT ID 0x{file_id:X} ({ACF_NITRO_PATH}); "
        f"payload base 0x{base:X}; {sig_score} signatures / {bounds_score} mapped files"
    )
    validate_acf(data, source)
    return data, {"source": source, "rom_start": rom_start}


def get_calls(insns):
    calls = []
    for i, ins in enumerate(insns):
        if ins["op"] != 0x01:
            continue
        selector = ins["raw16"]
        argc = ins["sub"]
        calls.append(
            {
                "insn_index": i,
                "off": ins["off"],
                "selector": selector,
                "group": (selector >> 10) & 0x3F,
                "command_index": selector & 0x3FF,
                "argc": argc,
                "args": direct_call_args(insns, i, argc),
                "name": KNOWN.get(selector, f"CALL_{selector:04X}"),
            }
        )
    return calls


def branch_target(ins):
    return ins["off"] + 4 + ins["imm16"] * 4


def poll_loop(call, insns):
    i = call["insn_index"]
    for j in range(i + 1, min(len(insns), i + 6)):
        ins = insns[j]
        if ins["op"] != 0x08 or ins["sub"] != 3:
            continue
        prev = insns[i + 1 : j]
        target = branch_target(ins)
        if any(x["op"] == 0x12 for x in prev) and call["off"] - 8 <= target <= call["off"]:
            return {
                "call_off": call["off"],
                "branch_off": ins["off"],
                "target_off": target,
            }
    return None


def analyze_sequences(insns, calls):
    results = []
    launches = [c for c in calls if c["selector"] == 0x1C10]
    for launch in launches:
        previous_launches = [c for c in launches if c["insn_index"] < launch["insn_index"]]
        lower = previous_launches[-1]["insn_index"] if previous_launches else launch["insn_index"] - 160
        block = [
            c for c in calls
            if lower < c["insn_index"] < launch["insn_index"]
            and c["selector"] in (SETUP | CONFIG)
        ]
        setups = [c for c in block if c["selector"] in SETUP]
        configs = [c for c in block if c["selector"] in CONFIG]
        after = [
            c for c in calls
            if launch["insn_index"] < c["insn_index"] <= launch["insn_index"] + 48
        ]
        async_call = next((c for c in after if c["selector"] == 0x1C36), None)
        poll_call = next((c for c in after if c["selector"] == 0x1C11), None)
        loop = poll_loop(poll_call, insns) if poll_call else None

        score = 45
        reasons = ["1C10 requests state 3 -> CSkyCaptureBeforeState"]
        if setups:
            score += 25
            reasons.append("capture-before setup present")
        if configs:
            score += 10
            reasons.append("capture-manager config present")
        if async_call:
            score += 10
            reasons.append("1C36 associated operation present")
        if loop:
            score += 10
            reasons.append("1C11 pending-state poll loop present")
        score = min(score, 100)
        confidence = "complete" if score >= 95 else "high" if score >= 80 else "medium"

        lo = max(0, launch["insn_index"] - 22)
        hi = min(len(insns), launch["insn_index"] + 30)
        context = [
            {
                "off": insns[i]["off"],
                "text": describe(insns[i], insns, i),
                "launch": i == launch["insn_index"],
            }
            for i in range(lo, hi)
        ]
        results.append(
            {
                "launch": launch,
                "setup_block": block,
                "setups": setups,
                "configs": configs,
                "async_1c36": async_call,
                "poll_1c11": poll_call,
                "poll_loop": loop,
                "score": score,
                "confidence": confidence,
                "reasons": reasons,
                "context": context,
            }
        )
    return results


def scan(acf, meta, progress):
    scripts = []
    pos = 0
    number = 0
    while pos < len(acf) - 4:
        if acf[pos] != 0x10:
            pos += 1
            continue
        res = lz10(acf, pos, len(acf))
        if res is None:
            pos += 1
            continue
        decoded, consumed = res
        if not looks_like_script(decoded):
            pos += 1
            continue
        try:
            code_start, code_end, insns = decode(decoded)
        except Exception:
            pos += max(consumed, 1)
            continue
        number += 1
        if progress and number % progress == 0:
            print(f"  decoded {number} script streams...")
        calls = get_calls(insns)
        sequences = analyze_sequences(insns, calls)
        setup_only = any(c["selector"] in SETUP for c in calls) and not sequences
        scripts.append(
            {
                "script_number": number,
                "acf_offset": pos,
                "rom_offset": None if meta["rom_start"] is None else meta["rom_start"] + pos,
                "compressed_size": consumed,
                "decoded_size": len(decoded),
                "sections": [u32(decoded, x) for x in (0, 4, 8, 12)],
                "code_start": code_start,
                "code_end": code_end,
                "instruction_count": len(insns),
                "call_count": len(calls),
                "interesting_calls": [c for c in calls if c["selector"] in INTERESTING],
                "capture_sequences": sequences,
                "setup_only": setup_only,
                "all_calls": calls,
            }
        )
        pos += max(consumed, 1)
    return scripts


def argtext(call):
    if not call or call["args"] is None:
        return "?"
    return ", ".join(fmt(x) for x in call["args"])


def calltext(call):
    if not call:
        return ""
    return f"0x{call['selector']:04X}@+0x{call['off']:X}({argtext(call)})"


def write_outputs(out, meta, scripts):
    out.mkdir(parents=True, exist_ok=True)
    candidates = [(s, q) for s in scripts for q in s["capture_sequences"]]
    setup_only = [s for s in scripts if s["setup_only"]]
    selector_counts = Counter(c["selector"] for s in scripts for c in s["all_calls"])

    payload = {
        "meta": meta,
        "known_semantics": {
            "1C10": "requests state 3 -> CSkyCaptureBeforeState",
            "1C11": "tests whether state-3 request is still pending",
            "1C12/1C54": "capture-before record setup",
            "1C30/1C35": "capture-before configuration",
            "1C36": "associated async/state operation; not capture-specific alone",
        },
        "summary": {
            "script_count": len(scripts),
            "scripts_with_capture_transition": sum(bool(s["capture_sequences"]) for s in scripts),
            "capture_transition_count": len(candidates),
            "setup_only_script_count": len(setup_only),
        },
        "scripts": scripts,
    }
    (out / "capture_analysis.json").write_text(json.dumps(payload, indent=2) + "\n")

    with (out / "script_index.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["script", "acf_offset", "rom_offset", "decoded_size", "instructions", "calls", "capture_transitions", "setup_only"])
        for s in scripts:
            w.writerow([
                s["script_number"], f"0x{s['acf_offset']:X}",
                "" if s["rom_offset"] is None else f"0x{s['rom_offset']:X}",
                s["decoded_size"], s["instruction_count"], s["call_count"],
                len(s["capture_sequences"]), int(s["setup_only"]),
            ])

    with (out / "all_script_calls.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["script", "acf_offset", "call_offset", "selector", "name", "argc", "args"])
        for s in scripts:
            for c in s["all_calls"]:
                w.writerow([
                    s["script_number"], f"0x{s['acf_offset']:X}", f"0x{c['off']:X}",
                    f"0x{c['selector']:04X}", c["name"], c["argc"], argtext(c),
                ])

    with (out / "capture_candidates.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["script", "acf_offset", "rom_offset", "launch_offset", "score", "confidence", "setup_block", "1c36_args", "poll_loop"])
        for s, q in candidates:
            w.writerow([
                s["script_number"], f"0x{s['acf_offset']:X}",
                "" if s["rom_offset"] is None else f"0x{s['rom_offset']:X}",
                f"0x{q['launch']['off']:X}", q["score"], q["confidence"],
                "; ".join(calltext(c) for c in q["setup_block"]),
                argtext(q["async_1c36"]), int(q["poll_loop"] is not None),
            ])

    md = [
        "# Capture Script Bulk Analysis", "",
        "## Proven semantic bridge", "",
        "`1C10` requests state `3`, which resolves to `CSkyCaptureBeforeState`. Therefore an aligned decoded `1C10` is the primary script-side transition marker for this capture path.", "",
        "## Summary", "",
        f"- ACF source: `{meta['source']}`",
        f"- Script-like LZ10 streams: **{len(scripts)}**",
        f"- Scripts with `1C10` transitions: **{sum(bool(s['capture_sequences']) for s in scripts)}**",
        f"- Total `1C10` transitions: **{len(candidates)}**",
        f"- Setup-only scripts (`1C12`/`1C54` without `1C10`): **{len(setup_only)}**",
        "", "## Capture transition candidates", "",
    ]
    for n, (s, q) in enumerate(candidates, 1):
        md += [
            f"### {n}. Script #{s['script_number']} — ACF +0x{s['acf_offset']:X}, launch +0x{q['launch']['off']:X} — {q['confidence']} ({q['score']}/100)", "",
            "- Full pre-launch configuration block: " + ("; ".join(f"`{calltext(c)}`" for c in q["setup_block"]) or "none"),
        ]
        if q["async_1c36"]:
            md.append(f"- `1C36` args=({argtext(q['async_1c36'])})")
        if q["poll_loop"]:
            p = q["poll_loop"]
            md.append(f"- `1C11` poll loop: +0x{p['call_off']:X}, branch +0x{p['branch_off']:X} -> +0x{p['target_off']:X}")
        md += ["- Evidence: " + "; ".join(q["reasons"]), "", "```text"]
        for row in q["context"]:
            md.append(f"{'>>' if row['launch'] else '  '} +0x{row['off']:04X}  {row['text']}")
        md += ["```", ""]

    md += ["## Most frequent command selectors", "", "| Selector | Calls | Known semantic |", "|---:|---:|---|"]
    for selector, count in selector_counts.most_common(80):
        md.append(f"| `0x{selector:04X}` | {count} | {KNOWN.get(selector, '')} |")
    md += [
        "", "## Notes", "",
        "- Calls are found only on VM instruction boundaries; raw selector bytes in data are ignored.",
        "- Constant arguments are recovered conservatively. `?` means the value is not an immediate constant sequence.",
        "- This pass covers the proven `CSkyCaptureBeforeState` script path. It is not evidence that ordinary overworld captures use the same launcher.",
        "- Mapping each embedded stream to its map/event/mission owner remains a separate ACF index/reference task.", "",
    ]
    (out / "capture_analysis.md").write_text("\n".join(md))


def main():
    ap = argparse.ArgumentParser(description="Bulk-analyze Guardian Signs capture-script transitions")
    ap.add_argument("acf", nargs="?", type=Path, help="Optional raw data_game_us.acf. Omit to extract canonical FAT ID 0x22 automatically.")
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "capture" / "generated")
    ap.add_argument("--progress-every", type=int, default=250)
    args = ap.parse_args()

    acf, meta = load_acf(args.acf)
    print(f"ACF source: {meta['source']}")
    print(f"ACF bytes : 0x{len(acf):X} ({len(acf):,})")
    print(f"Known Spearow signature verified at +0x{SPEAROW_ACF_OFFSET:X}.")
    print("Scanning embedded LZ10 scripts and decoding VM...")
    scripts = scan(acf, meta, args.progress_every)
    write_outputs(args.out, meta, scripts)

    transitions = sum(len(s["capture_sequences"]) for s in scripts)
    print("Done.")
    print(f"  script-like streams : {len(scripts)}")
    print(f"  capture transitions : {transitions}")
    print(f"  setup-only scripts  : {sum(s['setup_only'] for s in scripts)}")
    print(f"Reports: {args.out}")
    for name in ("capture_analysis.md", "capture_analysis.json", "capture_candidates.csv", "all_script_calls.csv", "script_index.csv"):
        print(f"  {args.out / name}")


if __name__ == "__main__":
    main()
