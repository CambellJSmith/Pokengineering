#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Final

MAGIC_FORMATS: Final[dict[bytes, str]] = {
    b"NARC": "NARC archive",
    b"RGCN": "NCGR graphics",
    b"RLCN": "NCLR palette",
    b"RCSN": "NSCR screen",
    b"RECN": "NCER cell",
    b"RNAN": "NANR animation",
    b"BMD0": "NSBMD model",
    b"BTX0": "NSBTX texture",
    b"BCA0": "NSBCA animation",
    b"BTA0": "NSBTA texture animation",
    b"BTP0": "NSBTP palette animation",
    b"BMA0": "NSBMA material animation",
    b"BVA0": "NSBVA visibility animation",
    b"SDAT": "SDAT sound archive",
    b"SSEQ": "SSEQ sequence",
    b"SBNK": "SBNK sound bank",
    b"SWAR": "SWAR wave archive",
    b"STRM": "STRM audio stream",
    b"acf\x00": "ACF archive",
    b"RIFF": "RIFF container",
    b"OggS": "Ogg stream",
    b"\x89PNG": "PNG image",
}

COMPRESSED_TYPES: Final[dict[int, str]] = {
    0x10: "Nintendo LZ10",
    0x11: "Nintendo LZ11",
    0x20: "Nintendo Huffman",
    0x30: "Nintendo RLE",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    size = len(data)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    printable = sum(1 for value in data if value in (9, 10, 13) or 0x20 <= value <= 0x7E)
    return printable / len(data)


def parse_index(name: str) -> int | None:
    prefix = name.split(".", 1)[0]
    return int(prefix) if len(prefix) == 4 and prefix.isdigit() else None


def compression_label(state: bool | None) -> str:
    if state is None:
        return "unused"
    return "acf-compressed" if state else "acf-raw"


def ascii_magic(data: bytes) -> str:
    prefix = data[:4]
    if len(prefix) == 4 and all(0x20 <= value <= 0x7E for value in prefix):
        return prefix.decode("ascii")
    return ""


def identify_format(data: bytes) -> tuple[str, int | None]:
    for magic, label in MAGIC_FORMATS.items():
        if data.startswith(magic):
            return label, 0
    if data and data[0] in COMPRESSED_TYPES:
        return COMPRESSED_TYPES[data[0]], 0
    scan = data[:64]
    matches: list[tuple[int, str]] = []
    for magic, label in MAGIC_FORMATS.items():
        offset = scan.find(magic)
        if offset > 0:
            matches.append((offset, label))
    if matches:
        offset, label = min(matches)
        return f"embedded {label}", offset
    return "unknown", None


def cluster_key(data: bytes, detected_format: str) -> str:
    if detected_format != "unknown":
        return f"known:{detected_format}"
    prefix = data[:2].hex() if data else "empty"
    alignment = len(data) % 4
    return f"unknown:{prefix}:mod4={alignment}"


def load_filelist(path: Path) -> dict[str, bool | None]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("filelist.json must contain a JSON object")
    result: dict[str, bool | None] = {}
    for name, state in raw.items():
        if not isinstance(name, str) or state not in (True, False, None):
            raise ValueError("filelist.json contains an unsupported entry")
        result[name] = state
    return result


def write_clusters(rows: list[dict[str, Any]], output_path: Path) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["detected_format"] == "unknown" and row["state"] != "unused":
            grouped[row["cluster_key"]].append(row)

    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(
            destination,
            fieldnames=["cluster_key", "count", "total_bytes", "min_size", "max_size", "example_indices", "example_headers"],
        )
        writer.writeheader()
        ranked = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        for key, members in ranked:
            if len(members) < 2:
                continue
            sizes = [int(member["size"]) for member in members]
            writer.writerow(
                {
                    "cluster_key": key,
                    "count": len(members),
                    "total_bytes": sum(sizes),
                    "min_size": min(sizes),
                    "max_size": max(sizes),
                    "example_indices": " ".join(str(member["index"]) for member in members[:12]),
                    "example_headers": " ".join(str(member["first_16_hex"]) for member in members[:4]),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Catalogue and classify extracted Guardian Signs data_game_us.acf entries.")
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    archive_dir = args.archive_dir.resolve()
    output_dir = args.output_dir.resolve()
    filelist_path = archive_dir / "filelist.json"
    if not filelist_path.is_file():
        raise FileNotFoundError(f"missing acftool metadata: {filelist_path}")

    entries = load_filelist(filelist_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    format_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    real_entries = 0

    for name, state in entries.items():
        index = parse_index(name)
        entry_path = archive_dir / name
        exists = state is not None and entry_path.is_file()
        data = entry_path.read_bytes() if exists else b""
        detected_format, magic_offset = identify_format(data)
        state_label = compression_label(state)
        if exists:
            real_entries += 1
            format_counts[detected_format] += 1
        state_counts[state_label] += 1
        row: dict[str, Any] = {
            "index": "" if index is None else f"{index:04d}",
            "filename": name,
            "state": state_label,
            "size": len(data),
            "sha256": sha256_file(entry_path) if exists else "",
            "entropy": f"{shannon_entropy(data):.4f}" if exists else "",
            "printable_ratio": f"{printable_ratio(data):.4f}" if exists else "",
            "first_16_hex": data[:16].hex(),
            "ascii_magic": ascii_magic(data),
            "detected_format": detected_format if exists else "unused",
            "magic_offset": "" if magic_offset is None else magic_offset,
            "u16_le_0": int.from_bytes(data[:2], "little") if len(data) >= 2 else "",
            "u32_le_0": int.from_bytes(data[:4], "little") if len(data) >= 4 else "",
            "size_mod_4": len(data) % 4 if exists else "",
            "size_mod_16": len(data) % 16 if exists else "",
            "cluster_key": cluster_key(data, detected_format) if exists else "unused",
        }
        rows.append(row)

    catalog_path = output_dir / "catalog.csv"
    with catalog_path.open("w", encoding="utf-8", newline="") as destination:
        fieldnames = list(rows[0].keys()) if rows else ["index", "filename"]
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    clusters_path = output_dir / "unknown_clusters.csv"
    write_clusters(rows, clusters_path)

    summary = {
        "archive_entries": len(entries),
        "real_entries": real_entries,
        "unused_entries": len(entries) - real_entries,
        "total_real_bytes": sum(int(row["size"]) for row in rows if row["state"] != "unused"),
        "states": dict(sorted(state_counts.items())),
        "formats": dict(sorted(format_counts.items(), key=lambda item: (-item[1], item[0]))),
        "recognized_entries": sum(count for label, count in format_counts.items() if label != "unknown"),
        "unknown_entries": format_counts.get("unknown", 0),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"catalogued {len(entries)} archive entries ({real_entries} real)")
    print(f"recognized entries: {summary['recognized_entries']}")
    print(f"unknown entries: {summary['unknown_entries']}")
    print(f"catalog: {catalog_path}")
    print(f"unknown clusters: {clusters_path}")
    print(f"summary: {output_dir / 'summary.json'}")
    for label, count in format_counts.most_common(12):
        print(f"format {label}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
