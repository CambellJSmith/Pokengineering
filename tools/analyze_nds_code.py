#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import blz

OVT_ENTRY_SIZE = 32
HEADER_MIN_SIZE = 0x160

ARM9_ROM_OFFSET = 0x20
ARM9_ENTRY = 0x24
ARM9_RAM = 0x28
ARM9_SIZE = 0x2C
ARM7_ROM_OFFSET = 0x30
ARM7_ENTRY = 0x34
ARM7_RAM = 0x38
ARM7_SIZE = 0x3C
FAT_ROM_OFFSET = 0x48
FAT_SIZE = 0x4C
ARM9_OVT_ROM_OFFSET = 0x50
ARM9_OVT_SIZE = 0x54
ARM7_OVT_ROM_OFFSET = 0x58
ARM7_OVT_SIZE = 0x5C


class CodeAnalysisError(ValueError):
    pass


def u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise CodeAnalysisError(f"u32 read outside payload at 0x{offset:X}")
    return struct.unpack_from("<I", data, offset)[0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@dataclass(frozen=True)
class Overlay:
    overlay_id: int
    ram_address: int
    ram_size: int
    bss_size: int
    static_init_start: int
    static_init_end: int
    file_id: int
    compressed_size: int
    flags: int
    compressed: bool
    fat_start: int
    fat_end: int
    physical_size: int
    data_offset: int
    sha256: str

    @property
    def ram_end(self) -> int:
        return self.ram_address + self.ram_size + self.bss_size

    @property
    def file_ram_end(self) -> int:
        return self.ram_address + self.ram_size


def parse_fat(data: bytes) -> list[tuple[int, int]]:
    if len(data) % 8:
        raise CodeAnalysisError(f"fat.bin size {len(data)} is not divisible by 8")
    entries: list[tuple[int, int]] = []
    for offset in range(0, len(data), 8):
        start, end = struct.unpack_from("<II", data, offset)
        if end < start:
            raise CodeAnalysisError(f"FAT entry {offset // 8} has reversed range")
        entries.append((start, end))
    return entries


def parse_overlay_table(
    table: bytes,
    fat: list[tuple[int, int]],
    overlay_region_rom_start: int,
    overlay_region: bytes,
) -> list[Overlay]:
    if len(table) % OVT_ENTRY_SIZE:
        raise CodeAnalysisError(
            f"ARM9 overlay table size {len(table)} is not divisible by {OVT_ENTRY_SIZE}"
        )

    overlays: list[Overlay] = []
    ids: set[int] = set()
    for offset in range(0, len(table), OVT_ENTRY_SIZE):
        (
            overlay_id,
            ram_address,
            ram_size,
            bss_size,
            static_init_start,
            static_init_end,
            file_id,
            packed,
        ) = struct.unpack_from("<8I", table, offset)

        if overlay_id in ids:
            raise CodeAnalysisError(f"duplicate overlay ID {overlay_id}")
        ids.add(overlay_id)
        if file_id >= len(fat):
            raise CodeAnalysisError(
                f"overlay {overlay_id} references FAT file {file_id}, but FAT has {len(fat)} entries"
            )
        if static_init_end < static_init_start:
            raise CodeAnalysisError(f"overlay {overlay_id} has reversed static initializer range")
        if ram_size == 0:
            raise CodeAnalysisError(f"overlay {overlay_id} has zero RAM size")

        fat_start, fat_end = fat[file_id]
        rel_start = fat_start - overlay_region_rom_start
        rel_end = fat_end - overlay_region_rom_start
        if rel_start < 0 or rel_end < rel_start or rel_end > len(overlay_region):
            raise CodeAnalysisError(
                f"overlay {overlay_id} FAT range 0x{fat_start:X}-0x{fat_end:X} "
                "does not fit inside a9ovr_data.bin"
            )
        payload = overlay_region[rel_start:rel_end]
        flags = (packed >> 24) & 0xFF
        compressed_size = packed & 0x00FFFFFF
        overlays.append(
            Overlay(
                overlay_id=overlay_id,
                ram_address=ram_address,
                ram_size=ram_size,
                bss_size=bss_size,
                static_init_start=static_init_start,
                static_init_end=static_init_end,
                file_id=file_id,
                compressed_size=compressed_size,
                flags=flags,
                compressed=bool(flags & 1),
                fat_start=fat_start,
                fat_end=fat_end,
                physical_size=len(payload),
                data_offset=rel_start,
                sha256=sha256(payload),
            )
        )
    return overlays


def decode_overlay(overlay: Overlay, payload: bytes) -> bytes:
    if overlay.compressed:
        try:
            decoded = blz.decompress(payload)
        except blz.BlzError as error:
            raise CodeAnalysisError(
                f"overlay {overlay.overlay_id} BLZ decompression failed: {error}"
            ) from error
    else:
        decoded = payload
    if len(decoded) != overlay.ram_size:
        raise CodeAnalysisError(
            f"overlay {overlay.overlay_id} decodes to {len(decoded)} bytes, "
            f"but overlay table declares RAM size {overlay.ram_size}"
        )
    return decoded


def ascii_strings(data: bytes, minimum: int = 5) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    start: int | None = None
    chars: list[str] = []
    for i, value in enumerate(data + b"\x00"):
        printable = 0x20 <= value <= 0x7E
        if printable:
            if start is None:
                start = i
            chars.append(chr(value))
            continue
        if start is not None and len(chars) >= minimum:
            rows.append((start, "".join(chars)))
        start = None
        chars = []
    return rows


def static_initializer_rows(overlay: Overlay, decoded: bytes) -> list[dict[str, Any]]:
    if not (overlay.ram_address <= overlay.static_init_start <= overlay.file_ram_end):
        return []
    if not (overlay.ram_address <= overlay.static_init_end <= overlay.file_ram_end):
        return []
    if (overlay.static_init_start | overlay.static_init_end) & 3:
        return []

    start = overlay.static_init_start - overlay.ram_address
    end = overlay.static_init_end - overlay.ram_address
    if end > len(decoded):
        return []

    rows: list[dict[str, Any]] = []
    for index, offset in enumerate(range(start, end, 4)):
        target = u32(decoded, offset)
        thumb = bool(target & 1)
        address = target & ~1
        rows.append(
            {
                "overlay_id": overlay.overlay_id,
                "initializer_index": index,
                "table_address": f"0x{overlay.ram_address + offset:08X}",
                "target_raw": f"0x{target:08X}",
                "target_address": f"0x{address:08X}",
                "instruction_set": "THUMB" if thumb else "ARM",
                "inside_overlay_file_ram": overlay.ram_address <= address < overlay.file_ram_end,
                "suggested_name": f"ov{overlay.overlay_id:03d}_static_init_{index:02d}",
            }
        )
    return rows


def overlap_groups(overlays: list[Overlay]) -> list[list[int]]:
    groups: list[set[int]] = []
    for i, left in enumerate(overlays):
        for right in overlays[i + 1:]:
            if left.ram_address < right.ram_end and right.ram_address < left.ram_end:
                touched = [g for g in groups if left.overlay_id in g or right.overlay_id in g]
                if not touched:
                    groups.append({left.overlay_id, right.overlay_id})
                else:
                    merged = {left.overlay_id, right.overlay_id}
                    for group in touched:
                        merged.update(group)
                        groups.remove(group)
                    groups.append(merged)
    return [sorted(group) for group in sorted(groups, key=lambda g: min(g))]


def analyze(root: Path, output: Path, *, extract: bool = True) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    required = {
        "header": root / "header.bin",
        "arm9": root / "arm9.bin",
        "arm7": root / "arm7.bin",
        "fat": root / "fat.bin",
        "a9ovr": root / "a9ovr.bin",
        "a9ovr_data": root / "a9ovr_data.bin",
    }
    for name, path in required.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing {name}: {path}")

    header = required["header"].read_bytes()
    arm9 = required["arm9"].read_bytes()
    arm7 = required["arm7"].read_bytes()
    fat_data = required["fat"].read_bytes()
    table = required["a9ovr"].read_bytes()
    overlay_region = required["a9ovr_data"].read_bytes()

    if len(header) < HEADER_MIN_SIZE:
        raise CodeAnalysisError(f"header.bin is shorter than 0x{HEADER_MIN_SIZE:X} bytes")

    arm9_rom = u32(header, ARM9_ROM_OFFSET)
    arm9_entry = u32(header, ARM9_ENTRY)
    arm9_ram = u32(header, ARM9_RAM)
    arm9_size = u32(header, ARM9_SIZE)
    arm7_rom = u32(header, ARM7_ROM_OFFSET)
    arm7_entry = u32(header, ARM7_ENTRY)
    arm7_ram = u32(header, ARM7_RAM)
    arm7_size = u32(header, ARM7_SIZE)
    fat_rom = u32(header, FAT_ROM_OFFSET)
    fat_size = u32(header, FAT_SIZE)
    a9ovr_rom = u32(header, ARM9_OVT_ROM_OFFSET)
    a9ovr_size = u32(header, ARM9_OVT_SIZE)
    a7ovr_rom = u32(header, ARM7_OVT_ROM_OFFSET)
    a7ovr_size = u32(header, ARM7_OVT_SIZE)

    if arm9_size > len(arm9):
        raise CodeAnalysisError("arm9.bin is shorter than the executable size declared by the header")
    if arm7_size != len(arm7):
        raise CodeAnalysisError("arm7.bin size does not match the header")
    if fat_size != len(fat_data):
        raise CodeAnalysisError("fat.bin size does not match the header")
    if a9ovr_size != len(table):
        raise CodeAnalysisError("a9ovr.bin size does not match the header")

    overlay_region_rom_start = a9ovr_rom + a9ovr_size
    if overlay_region_rom_start + len(overlay_region) != arm7_rom:
        raise CodeAnalysisError(
            "a9ovr_data.bin does not exactly span the ROM region between ARM9 OVT and ARM7"
        )

    fat = parse_fat(fat_data)
    overlays = parse_overlay_table(table, fat, overlay_region_rom_start, overlay_region)

    overlay_rows: list[dict[str, Any]] = []
    initializer_rows: list[dict[str, Any]] = []
    string_rows: list[dict[str, Any]] = []
    ghidra_rows: list[dict[str, Any]] = []

    executable_dir = output / "executables"
    overlay_dir = executable_dir / "overlays"
    if extract:
        overlay_dir.mkdir(parents=True, exist_ok=True)
        (executable_dir / "arm9.bin").write_bytes(arm9[:arm9_size])
        (executable_dir / "arm7.bin").write_bytes(arm7)

    for offset, text in ascii_strings(arm9[:arm9_size]):
        string_rows.append(
            {
                "module": "arm9",
                "overlay_id": "",
                "file_offset": f"0x{offset:X}",
                "ram_address": f"0x{arm9_ram + offset:08X}",
                "text": text,
            }
        )

    ghidra_rows.append(
        {
            "program": "arm9",
            "path": "executables/arm9.bin",
            "load_address": f"0x{arm9_ram:08X}",
            "entry_point": f"0x{arm9_entry:08X}",
            "processor": "ARM:LE:32:v5t",
            "importable": True,
            "notes": "main ARM9 executable; arm9.bin footer excluded",
        }
    )
    ghidra_rows.append(
        {
            "program": "arm7",
            "path": "executables/arm7.bin",
            "load_address": f"0x{arm7_ram:08X}",
            "entry_point": f"0x{arm7_entry:08X}",
            "processor": "ARM:LE:32:v4t",
            "importable": True,
            "notes": "ARM7 executable",
        }
    )

    for overlay in overlays:
        rel_start = overlay.data_offset
        rel_end = rel_start + overlay.physical_size
        payload = overlay_region[rel_start:rel_end]
        decoded = decode_overlay(overlay, payload)
        raw_name = f"overlay_{overlay.overlay_id:03d}.raw.bin"
        decoded_name = f"overlay_{overlay.overlay_id:03d}.bin"
        if extract:
            (overlay_dir / raw_name).write_bytes(payload)
            (overlay_dir / decoded_name).write_bytes(decoded)

        init_rows = static_initializer_rows(overlay, decoded)
        initializer_rows.extend(init_rows)
        for offset, text in ascii_strings(decoded):
            string_rows.append(
                {
                    "module": f"overlay_{overlay.overlay_id:03d}",
                    "overlay_id": overlay.overlay_id,
                    "file_offset": f"0x{offset:X}",
                    "ram_address": f"0x{overlay.ram_address + offset:08X}",
                    "text": text,
                }
            )

        overlap = [
            other.overlay_id
            for other in overlays
            if other.overlay_id != overlay.overlay_id
            and overlay.ram_address < other.ram_end
            and other.ram_address < overlay.ram_end
        ]
        overlay_rows.append(
            {
                "overlay_id": overlay.overlay_id,
                "file_id": overlay.file_id,
                "ram_address": f"0x{overlay.ram_address:08X}",
                "ram_size": overlay.ram_size,
                "bss_size": overlay.bss_size,
                "ram_end": f"0x{overlay.ram_end:08X}",
                "static_init_start": f"0x{overlay.static_init_start:08X}",
                "static_init_end": f"0x{overlay.static_init_end:08X}",
                "static_initializer_count": len(init_rows),
                "fat_start": f"0x{overlay.fat_start:08X}",
                "fat_end": f"0x{overlay.fat_end:08X}",
                "physical_size": overlay.physical_size,
                "decoded_size": len(decoded),
                "compressed_size_field": overlay.compressed_size,
                "flags": f"0x{overlay.flags:02X}",
                "compressed": overlay.compressed,
                "raw_sha256": overlay.sha256,
                "decoded_sha256": sha256(decoded),
                "overlaps_overlay_ids": " ".join(str(value) for value in sorted(overlap)),
                "raw_path": f"executables/overlays/{raw_name}",
                "decoded_path": f"executables/overlays/{decoded_name}",
            }
        )
        ghidra_rows.append(
            {
                "program": f"overlay_{overlay.overlay_id:03d}",
                "path": f"executables/overlays/{decoded_name}",
                "load_address": f"0x{overlay.ram_address:08X}",
                "entry_point": "",
                "processor": "ARM:LE:32:v5t",
                "importable": True,
                "notes": "BLZ-decoded overlay; analyze separately because overlays share RAM windows",
            }
        )

    write_csv(
        output / "overlays.csv",
        overlay_rows,
        [
            "overlay_id", "file_id", "ram_address", "ram_size", "bss_size", "ram_end",
            "static_init_start", "static_init_end", "static_initializer_count", "fat_start",
            "fat_end", "physical_size", "decoded_size", "compressed_size_field", "flags",
            "compressed", "raw_sha256", "decoded_sha256", "overlaps_overlay_ids", "raw_path",
            "decoded_path",
        ],
    )
    write_csv(
        output / "static_initializers.csv",
        initializer_rows,
        [
            "overlay_id", "initializer_index", "table_address", "target_raw", "target_address",
            "instruction_set", "inside_overlay_file_ram", "suggested_name",
        ],
    )
    write_csv(
        output / "strings.csv",
        string_rows,
        ["module", "overlay_id", "file_offset", "ram_address", "text"],
    )
    write_csv(
        output / "ghidra_targets.csv",
        ghidra_rows,
        ["program", "path", "load_address", "entry_point", "processor", "importable", "notes"],
    )

    memory_rows = [
        {
            "module": "arm9",
            "kind": "resident",
            "ram_start": f"0x{arm9_ram:08X}",
            "ram_end": f"0x{arm9_ram + arm9_size:08X}",
            "file_size": arm9_size,
            "bss_size": 0,
        },
        {
            "module": "arm7",
            "kind": "resident",
            "ram_start": f"0x{arm7_ram:08X}",
            "ram_end": f"0x{arm7_ram + arm7_size:08X}",
            "file_size": arm7_size,
            "bss_size": 0,
        },
    ]
    memory_rows.extend(
        {
            "module": f"overlay_{o.overlay_id:03d}",
            "kind": "overlay",
            "ram_start": f"0x{o.ram_address:08X}",
            "ram_end": f"0x{o.ram_end:08X}",
            "file_size": o.ram_size,
            "bss_size": o.bss_size,
        }
        for o in overlays
    )
    write_csv(
        output / "memory_map.csv",
        memory_rows,
        ["module", "kind", "ram_start", "ram_end", "file_size", "bss_size"],
    )

    overlap = overlap_groups(overlays)
    summary = {
        "format": "pokengineering-nds-code-analysis-v2",
        "header": {
            "game_title": header[:12].rstrip(b"\x00").decode("ascii", errors="replace"),
            "game_code": header[12:16].decode("ascii", errors="replace"),
            "arm9_rom_offset": arm9_rom,
            "arm9_entry": arm9_entry,
            "arm9_ram_address": arm9_ram,
            "arm9_executable_size": arm9_size,
            "arm9_extracted_size": len(arm9),
            "arm7_rom_offset": arm7_rom,
            "arm7_entry": arm7_entry,
            "arm7_ram_address": arm7_ram,
            "arm7_size": arm7_size,
            "fat_rom_offset": fat_rom,
            "fat_size": fat_size,
            "arm9_overlay_table_rom_offset": a9ovr_rom,
            "arm9_overlay_table_size": a9ovr_size,
            "arm7_overlay_table_rom_offset": a7ovr_rom,
            "arm7_overlay_table_size": a7ovr_size,
        },
        "arm9_sha256": sha256(arm9[:arm9_size]),
        "arm7_sha256": sha256(arm7),
        "arm9_overlay_count": len(overlays),
        "compressed_arm9_overlays": sum(1 for o in overlays if o.compressed),
        "decoded_arm9_overlays": len(overlays),
        "overlay_static_initializer_entries": len(initializer_rows),
        "ascii_strings_indexed": len(string_rows),
        "overlay_ram_overlap_groups": overlap,
        "ghidra_importable_programs": len(ghidra_rows),
        "notes": [
            "Overlay semantic purpose is not inferred from layout alone.",
            "BLZ overlays are decoded and validated against each overlay table RAM size before analysis.",
            "Each overlay should be analyzed as its own Ghidra program because multiple overlays can occupy the same RAM window at different times.",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"game: {summary['header']['game_title']} ({summary['header']['game_code']})")
    print(f"ARM9 entry: 0x{arm9_entry:08X} @ 0x{arm9_ram:08X}, {arm9_size} bytes")
    print(f"ARM7 entry: 0x{arm7_entry:08X} @ 0x{arm7_ram:08X}, {arm7_size} bytes")
    print(f"ARM9 overlays: {len(overlays)}")
    print(f"compressed ARM9 overlays: {summary['compressed_arm9_overlays']}")
    print(f"successfully decoded ARM9 overlays: {summary['decoded_arm9_overlays']}")
    print(f"static initializer pointers indexed: {len(initializer_rows)}")
    print(f"ASCII strings indexed: {len(string_rows)}")
    print(f"overlay RAM overlap groups: {len(overlap)}")
    print(f"Ghidra-importable programs: {len(ghidra_rows)}")
    print(f"analysis output: {output}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map Guardian Signs ARM executables and ARM9 overlays for reverse engineering."
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="extracted NDS component root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("work/code_analysis"),
        help="analysis output directory",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="write metadata tables without copying executable binaries into the output directory",
    )
    args = parser.parse_args()
    analyze(args.root, args.output, extract=not args.metadata_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
