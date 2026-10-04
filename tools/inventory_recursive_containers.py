#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from catalog_game_acf import identify_format, load_filelist, parse_index

ACF_MAGIC: Final[bytes] = b"acf\x00"
NARC_MAGIC: Final[bytes] = b"NARC"
DEFAULT_MAX_DEPTH: Final[int] = 64


class ContainerFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ContainerEntry:
    index: int
    state: str
    data: bytes | None
    warning: str = ""


@dataclass(frozen=True)
class PayloadInspection:
    detected_format: str
    magic_offset: int | None
    decoded_format: str
    decoded_size: int | None
    container_kind: str
    container_data: bytes | None
    decode_error: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decompress_lz10(data: bytes) -> bytes:
    if len(data) < 4 or data[0] != 0x10:
        raise ContainerFormatError("payload is not Nintendo LZ10")

    output_size = int.from_bytes(data[1:4], "little")
    source_offset = 4
    if output_size == 0:
        if len(data) < 8:
            raise ContainerFormatError("extended LZ10 header is truncated")
        output_size = int.from_bytes(data[4:8], "little")
        source_offset = 8
    if output_size <= 0:
        raise ContainerFormatError("LZ10 output size is zero")

    output = bytearray()
    while len(output) < output_size:
        if source_offset >= len(data):
            raise ContainerFormatError("LZ10 flag byte is truncated")
        flags = data[source_offset]
        source_offset += 1

        for bit in range(7, -1, -1):
            if len(output) >= output_size:
                break
            if flags & (1 << bit):
                if source_offset + 2 > len(data):
                    raise ContainerFormatError("LZ10 back-reference is truncated")
                first = data[source_offset]
                second = data[source_offset + 1]
                source_offset += 2
                length = (first >> 4) + 3
                displacement = (((first & 0x0F) << 8) | second) + 1
                if displacement > len(output):
                    raise ContainerFormatError("LZ10 back-reference exceeds decoded prefix")
                for _ in range(length):
                    output.append(output[-displacement])
                    if len(output) >= output_size:
                        break
            else:
                if source_offset >= len(data):
                    raise ContainerFormatError("LZ10 literal byte is truncated")
                output.append(data[source_offset])
                source_offset += 1

    return bytes(output)


def parse_acf(data: bytes) -> list[ContainerEntry]:
    if len(data) < 0x20:
        raise ContainerFormatError("ACF header is truncated")
    if data[:4] != ACF_MAGIC:
        raise ContainerFormatError("ACF magic is invalid")

    header_size, data_start, num_files = struct.unpack_from("<III", data, 4)
    if header_size < 0x20 or header_size > len(data):
        raise ContainerFormatError("ACF header size is invalid")

    fat_end = header_size + num_files * 12
    if fat_end > len(data):
        raise ContainerFormatError("ACF FAT exceeds archive size")
    if data_start < fat_end or data_start > len(data):
        raise ContainerFormatError("ACF data start is invalid")

    entries: list[ContainerEntry] = []
    for index in range(num_files):
        relative_offset, output_size, input_size = struct.unpack_from("<III", data, header_size + index * 12)
        if relative_offset == 0xFFFFFFFF:
            entries.append(ContainerEntry(index=index, state="unused", data=None))
            continue

        data_offset = data_start + relative_offset
        stored_size = input_size if input_size > 0 else output_size
        data_end = data_offset + stored_size
        if data_offset > len(data) or data_end > len(data):
            raise ContainerFormatError(f"ACF entry {index} exceeds archive size")

        stored = data[data_offset:data_end]
        if input_size == 0:
            entries.append(ContainerEntry(index=index, state="acf-raw", data=stored))
            continue

        if stored.startswith(b"\x10"):
            try:
                decoded = decompress_lz10(stored)
            except ContainerFormatError as error:
                entries.append(
                    ContainerEntry(
                        index=index,
                        state="acf-raw-fallback",
                        data=stored,
                        warning=f"LZ10 decode failed: {error}",
                    )
                )
            else:
                entries.append(ContainerEntry(index=index, state="acf-compressed", data=decoded))
            continue

        entries.append(
            ContainerEntry(
                index=index,
                state="acf-raw-fallback",
                data=stored,
                warning="ACF input_size is non-zero but payload is not LZ10",
            )
        )

    return entries


def parse_narc(data: bytes) -> list[ContainerEntry]:
    if len(data) < 0x10:
        raise ContainerFormatError("NARC header is truncated")

    magic, _byte_order, _version, declared_size, header_size, block_count = struct.unpack_from("<4sHHIHH", data, 0)
    if magic != NARC_MAGIC:
        raise ContainerFormatError("NARC magic is invalid")
    if header_size < 0x10 or header_size > len(data):
        raise ContainerFormatError("NARC header size is invalid")
    if declared_size < header_size or declared_size > len(data):
        raise ContainerFormatError("NARC declared size is invalid")

    blocks: dict[bytes, bytes] = {}
    offset = header_size
    for _ in range(block_count):
        if offset + 8 > declared_size:
            raise ContainerFormatError("NARC block header is truncated")
        block_magic, block_size = struct.unpack_from("<4sI", data, offset)
        if block_size < 8 or offset + block_size > declared_size:
            raise ContainerFormatError("NARC block size is invalid")
        blocks[block_magic] = data[offset + 8 : offset + block_size]
        offset += block_size

    fat = blocks.get(b"BTAF")
    image = blocks.get(b"GMIF")
    if fat is None or image is None:
        raise ContainerFormatError("NARC is missing BTAF or GMIF")
    if len(fat) < 4:
        raise ContainerFormatError("NARC BTAF is truncated")

    file_count = int.from_bytes(fat[:2], "little")
    table_size = 4 + file_count * 8
    if table_size > len(fat):
        raise ContainerFormatError("NARC BTAF file table is truncated")

    entries: list[ContainerEntry] = []
    for index in range(file_count):
        start, end = struct.unpack_from("<II", fat, 4 + index * 8)
        if start > end or end > len(image):
            raise ContainerFormatError(f"NARC entry {index} exceeds GMIF data")
        entries.append(ContainerEntry(index=index, state="narc-raw", data=image[start:end]))
    return entries


def plausible_lz10_header(data: bytes) -> bool:
    if len(data) < 4 or data[0] != 0x10:
        return False
    output_size = int.from_bytes(data[1:4], "little")
    header_size = 4
    if output_size == 0:
        if len(data) < 8:
            return False
        output_size = int.from_bytes(data[4:8], "little")
        header_size = 8
    if output_size <= 0:
        return False
    maximum_literal_size = header_size + output_size + ((output_size + 7) // 8) + 4
    return len(data) <= maximum_literal_size or output_size >= len(data) - header_size


def inspect_payload(data: bytes) -> PayloadInspection:
    detected_format, magic_offset = identify_format(data)
    decoded_format = ""
    decoded_size: int | None = None
    decoded_data: bytes | None = None
    decode_error = ""

    if detected_format == "Nintendo LZ10" or plausible_lz10_header(data):
        try:
            decoded_data = decompress_lz10(data)
        except ContainerFormatError as error:
            decode_error = str(error)
        else:
            decoded_size = len(decoded_data)
            decoded_format, _ = identify_format(decoded_data)
            detected_format = "Nintendo LZ10"
            magic_offset = 0

    candidate = decoded_data if decoded_data is not None else data
    if candidate.startswith(ACF_MAGIC):
        container_kind = "ACF"
        container_data = candidate
    elif candidate.startswith(NARC_MAGIC):
        container_kind = "NARC"
        container_data = candidate
    else:
        container_kind = ""
        container_data = None

    return PayloadInspection(
        detected_format=detected_format,
        magic_offset=magic_offset,
        decoded_format=decoded_format,
        decoded_size=decoded_size,
        container_kind=container_kind,
        container_data=container_data,
        decode_error=decode_error,
    )


def build_inventory(archive_dir: Path, output_dir: Path, max_depth: int = DEFAULT_MAX_DEPTH) -> dict[str, Any]:
    archive_dir = archive_dir.resolve()
    output_dir = output_dir.resolve()
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")

    filelist_path = archive_dir / "filelist.json"
    if not filelist_path.is_file():
        raise FileNotFoundError(f"missing acftool metadata: {filelist_path}")

    top_level_entries = load_filelist(filelist_path)
    rows: list[dict[str, Any]] = []

    def walk_entry(
        *,
        index: int,
        state: str,
        data: bytes | None,
        parent_path: str,
        parent_container: str,
        depth: int,
        entry_warning: str = "",
        ancestor_containers: frozenset[str] = frozenset(),
    ) -> None:
        segment = f"{parent_container.lower()}:{index:04d}"
        logical_path = f"{parent_path}/{segment}" if parent_path else segment

        if data is None:
            rows.append(
                {
                    "logical_path": logical_path,
                    "parent_path": parent_path,
                    "depth": depth,
                    "parent_container": parent_container,
                    "entry_index": f"{index:04d}",
                    "state": state,
                    "size": 0,
                    "sha256": "",
                    "first_16_hex": "",
                    "detected_format": "unused",
                    "magic_offset": "",
                    "decoded_format": "",
                    "decoded_size": "",
                    "effective_format": "unused",
                    "container_kind": "",
                    "child_count": 0,
                    "parse_status": "unused",
                    "entry_warning": entry_warning,
                    "decode_error": "",
                    "parse_error": "",
                }
            )
            return

        digest = sha256_bytes(data)
        inspection = inspect_payload(data)
        effective_format = inspection.decoded_format or inspection.detected_format
        row: dict[str, Any] = {
            "logical_path": logical_path,
            "parent_path": parent_path,
            "depth": depth,
            "parent_container": parent_container,
            "entry_index": f"{index:04d}",
            "state": state,
            "size": len(data),
            "sha256": digest,
            "first_16_hex": data[:16].hex(),
            "detected_format": inspection.detected_format,
            "magic_offset": "" if inspection.magic_offset is None else inspection.magic_offset,
            "decoded_format": inspection.decoded_format,
            "decoded_size": "" if inspection.decoded_size is None else inspection.decoded_size,
            "effective_format": effective_format,
            "container_kind": inspection.container_kind,
            "child_count": 0,
            "parse_status": "leaf",
            "entry_warning": entry_warning,
            "decode_error": inspection.decode_error,
            "parse_error": "",
        }
        rows.append(row)

        if not inspection.container_kind or inspection.container_data is None:
            return
        if depth >= max_depth:
            row["parse_status"] = "max-depth"
            return

        container_digest = sha256_bytes(inspection.container_data)
        if container_digest in ancestor_containers:
            row["parse_status"] = "cycle"
            row["parse_error"] = "container payload repeats an ancestor container"
            return

        try:
            if inspection.container_kind == "ACF":
                children = parse_acf(inspection.container_data)
            else:
                children = parse_narc(inspection.container_data)
        except ContainerFormatError as error:
            row["parse_status"] = "error"
            row["parse_error"] = str(error)
            return

        row["parse_status"] = "parsed"
        row["child_count"] = len(children)
        next_ancestors = ancestor_containers | {container_digest}
        for child in children:
            walk_entry(
                index=child.index,
                state=child.state,
                data=child.data,
                parent_path=logical_path,
                parent_container=inspection.container_kind,
                depth=depth + 1,
                entry_warning=child.warning,
                ancestor_containers=next_ancestors,
            )

    for filename, compressed_state in top_level_entries.items():
        index = parse_index(filename)
        if index is None:
            raise ValueError(f"top-level ACF filename has no stable four-digit index: {filename}")
        if compressed_state is None:
            walk_entry(index=index, state="unused", data=None, parent_path="", parent_container="ACF", depth=1)
            continue

        entry_path = archive_dir / filename
        if not entry_path.is_file():
            raise FileNotFoundError(f"missing extracted top-level ACF entry: {entry_path}")
        state = "acf-compressed" if compressed_state else "acf-raw"
        walk_entry(index=index, state=state, data=entry_path.read_bytes(), parent_path="", parent_container="ACF", depth=1)

    output_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = output_dir / "recursive_catalog.csv"
    fieldnames = [
        "logical_path",
        "parent_path",
        "depth",
        "parent_container",
        "entry_index",
        "state",
        "size",
        "sha256",
        "first_16_hex",
        "detected_format",
        "magic_offset",
        "decoded_format",
        "decoded_size",
        "effective_format",
        "container_kind",
        "child_count",
        "parse_status",
        "entry_warning",
        "decode_error",
        "parse_error",
    ]
    with catalog_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    real_rows = [row for row in rows if row["state"] != "unused"]
    effective_formats = Counter(str(row["effective_format"]) for row in real_rows)
    detected_formats = Counter(str(row["detected_format"]) for row in real_rows)
    decoded_formats = Counter(str(row["decoded_format"]) for row in real_rows if row["decoded_format"])
    containers = Counter(str(row["container_kind"]) for row in real_rows if row["container_kind"])
    parsed_containers = Counter(
        str(row["container_kind"])
        for row in real_rows
        if row["container_kind"] and row["parse_status"] == "parsed"
    )
    states = Counter(str(row["state"]) for row in rows)
    depths = Counter(int(row["depth"]) for row in rows)

    summary: dict[str, Any] = {
        "top_level_slots": len(top_level_entries),
        "top_level_real_entries": sum(1 for state in top_level_entries.values() if state is not None),
        "inventory_rows": len(rows),
        "real_entries": len(real_rows),
        "unused_entries": len(rows) - len(real_rows),
        "total_real_bytes": sum(int(row["size"]) for row in real_rows),
        "max_depth": max(depths, default=0),
        "depth_counts": {str(depth): count for depth, count in sorted(depths.items())},
        "states": dict(sorted(states.items())),
        "containers": dict(sorted(containers.items())),
        "parsed_containers": dict(sorted(parsed_containers.items())),
        "container_parse_errors": sum(1 for row in rows if row["parse_status"] == "error"),
        "cycle_stops": sum(1 for row in rows if row["parse_status"] == "cycle"),
        "max_depth_stops": sum(1 for row in rows if row["parse_status"] == "max-depth"),
        "decoded_lz10_entries": sum(1 for row in real_rows if row["decoded_format"]),
        "recognized_entries": sum(count for label, count in effective_formats.items() if label != "unknown"),
        "unknown_entries": effective_formats.get("unknown", 0),
        "detected_formats": dict(sorted(detected_formats.items(), key=lambda item: (-item[1], item[0]))),
        "decoded_formats": dict(sorted(decoded_formats.items(), key=lambda item: (-item[1], item[0]))),
        "effective_formats": dict(sorted(effective_formats.items(), key=lambda item: (-item[1], item[0]))),
    }
    summary_path = output_dir / "recursive_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"recursive inventory rows: {summary['inventory_rows']} ({summary['real_entries']} real)")
    print(f"recursive inventory maximum depth: {summary['max_depth']}")
    print(f"parsed ACF containers: {parsed_containers.get('ACF', 0)}")
    print(f"parsed NARC containers: {parsed_containers.get('NARC', 0)}")
    print(f"container parse errors: {summary['container_parse_errors']}")
    print(f"LZ10 entries decoded for inner classification: {summary['decoded_lz10_entries']}")
    print(f"recursive catalogue: {catalog_path}")
    print(f"recursive summary: {summary_path}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Recursively inventory ACF and NARC containers extracted from Guardian Signs.")
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    args = parser.parse_args()

    build_inventory(args.archive_dir, args.output_dir, args.max_depth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
