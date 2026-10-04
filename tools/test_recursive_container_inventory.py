#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import struct
import tempfile
from pathlib import Path

from inventory_recursive_containers import build_inventory, decompress_lz10, parse_acf, parse_narc


def lz10_literals(payload: bytes) -> bytes:
    header = bytes((0x10, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF, (len(payload) >> 16) & 0xFF))
    encoded = bytearray(header)
    for offset in range(0, len(payload), 8):
        chunk = payload[offset : offset + 8]
        encoded.append(0x00)
        encoded.extend(chunk)
    return bytes(encoded)


def align4(value: int) -> int:
    return (value + 3) & ~3


def build_acf(entries: list[bytes | None | tuple[str, bytes]]) -> bytes:
    header_size = 0x20
    data_start = align4(header_size + len(entries) * 12)
    fat = bytearray()
    payload = bytearray()

    for entry in entries:
        if entry is None:
            fat.extend(struct.pack("<III", 0xFFFFFFFF, 0, 0))
            continue

        if isinstance(entry, tuple):
            mode, decoded = entry
            if mode != "lz10":
                raise ValueError(f"unsupported synthetic ACF mode: {mode}")
            stored = lz10_literals(decoded)
            fat.extend(struct.pack("<III", len(payload), len(decoded), len(stored)))
            payload.extend(stored)
        else:
            fat.extend(struct.pack("<III", len(payload), len(entry), 0))
            payload.extend(entry)

    header = struct.pack("<4sIIIIIII", b"acf\x00", header_size, data_start, len(entries), 1, 0x32, 0, 0)
    padding = b"\x00" * (data_start - len(header) - len(fat))
    return header + bytes(fat) + padding + bytes(payload)


def build_narc(entries: list[bytes]) -> bytes:
    image = bytearray()
    offsets: list[tuple[int, int]] = []
    for entry in entries:
        start = len(image)
        image.extend(entry)
        end = len(image)
        offsets.append((start, end))
        image.extend(b"\x00" * (align4(len(image)) - len(image)))

    fat_payload = struct.pack("<HH", len(entries), 0) + b"".join(struct.pack("<II", start, end) for start, end in offsets)
    btaf = b"BTAF" + struct.pack("<I", 8 + len(fat_payload)) + fat_payload
    btnf = b"BTNF" + struct.pack("<I", 8)
    gmif = b"GMIF" + struct.pack("<I", 8 + len(image)) + bytes(image)
    file_size = 0x10 + len(btaf) + len(btnf) + len(gmif)
    header = struct.pack("<4sHHIHH", b"NARC", 0xFEFF, 0x0100, file_size, 0x10, 3)
    return header + btaf + btnf + gmif


def main() -> int:
    literal_payload = b"RCSNsynthetic-screen"
    if decompress_lz10(lz10_literals(literal_payload)) != literal_payload:
        raise SystemExit("literal-only LZ10 round-trip failed")

    nested_acf = build_acf([None, b"RLCNsynthetic-palette", ("lz10", literal_payload)])
    acf_entries = parse_acf(nested_acf)
    if [entry.state for entry in acf_entries] != ["unused", "acf-raw", "acf-compressed"]:
        raise SystemExit("synthetic ACF states were not parsed correctly")
    if acf_entries[2].data != literal_payload:
        raise SystemExit("synthetic ACF compressed payload was not decoded")

    top_narc = build_narc([b"RGCNsynthetic-tiles", lz10_literals(nested_acf)])
    narc_entries = parse_narc(top_narc)
    if len(narc_entries) != 2 or narc_entries[0].data != b"RGCNsynthetic-tiles":
        raise SystemExit("synthetic NARC entries were not parsed correctly")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        archive_dir = root / "archive"
        output_dir = root / "analysis"
        archive_dir.mkdir()
        (archive_dir / "0000.narc").write_bytes(top_narc)
        (archive_dir / "filelist.json").write_text(
            json.dumps({"0000.narc": False, "0001.bin": None}, indent=2) + "\n",
            encoding="utf-8",
        )

        summary = build_inventory(archive_dir, output_dir)
        if summary["top_level_slots"] != 2 or summary["top_level_real_entries"] != 1:
            raise SystemExit("recursive summary top-level counts are incorrect")
        if summary["inventory_rows"] != 7 or summary["real_entries"] != 5 or summary["unused_entries"] != 2:
            raise SystemExit("recursive summary row counts are incorrect")
        if summary["max_depth"] != 3:
            raise SystemExit("recursive summary depth is incorrect")
        if summary["parsed_containers"] != {"ACF": 1, "NARC": 1}:
            raise SystemExit("recursive summary container counts are incorrect")
        if summary["container_parse_errors"] != 0 or summary["max_depth_stops"] != 0:
            raise SystemExit("synthetic recursive inventory did not fully parse")
        if summary["decoded_lz10_entries"] != 1:
            raise SystemExit("compressed NARC child was not decoded for inner classification")

        catalog_path = output_dir / "recursive_catalog.csv"
        with catalog_path.open("r", encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        by_path = {row["logical_path"]: row for row in rows}
        expected_paths = {
            "acf:0000",
            "acf:0000/narc:0000",
            "acf:0000/narc:0001",
            "acf:0000/narc:0001/acf:0000",
            "acf:0000/narc:0001/acf:0001",
            "acf:0000/narc:0001/acf:0002",
            "acf:0001",
        }
        if set(by_path) != expected_paths:
            raise SystemExit("recursive logical paths are unstable or incomplete")
        if by_path["acf:0000/narc:0001"]["decoded_format"] != "ACF archive":
            raise SystemExit("LZ10-wrapped ACF was not classified after decoding")
        if by_path["acf:0000/narc:0001/acf:0002"]["effective_format"] != "NSCR screen":
            raise SystemExit("nested compressed ACF child was not classified")
        if by_path["acf:0000/narc:0001/acf:0000"]["parse_status"] != "unused":
            raise SystemExit("nested unused ACF slot was not preserved")

    print("recursive container inventory synthetic test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
