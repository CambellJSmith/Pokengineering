#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path
from typing import Final

from extract_nitrofs_file import parse_file_ids
from rebuild_nds import (
    ARM7_OFFSET_FIELD,
    ARM7_SIZE_FIELD,
    ARM9_OFFSET_FIELD,
    ARM9_OVT_OFFSET_FIELD,
    ARM9_OVT_SIZE_FIELD,
    ARM9_SIZE_FIELD,
    BANNER_OFFSET_FIELD,
    DEVICE_CAPACITY_FIELD,
    FAT_ENTRY_SIZE,
    FAT_OFFSET_FIELD,
    FAT_SIZE_FIELD,
    FNT_OFFSET_FIELD,
    FNT_SIZE_FIELD,
    HEADER_CRC_END,
    HEADER_CRC_FIELD,
    HEADER_SIZE_FIELD,
    USED_ROM_SIZE_FIELD,
    cartridge_capacity,
    crc16_nintendo,
    read_u32,
)


def read_range(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as source:
        source.seek(start)
        data: bytes = source.read(end - start)
    if len(data) != end - start:
        raise ValueError(f"ROM range 0x{start:x}-0x{end:x} is truncated")
    return data


def parse_fat_bytes(data: bytes) -> list[tuple[int, int]]:
    if len(data) % FAT_ENTRY_SIZE != 0:
        raise ValueError("ROM FAT size is not divisible by eight")
    return [struct.unpack_from("<II", data, offset) for offset in range(0, len(data), FAT_ENTRY_SIZE)]


def parse_expected(raw_values: list[str], file_ids: dict[int, str]) -> dict[int, Path]:
    path_to_id: dict[str, int] = {path.replace("\\", "/").lstrip("/"): file_id for file_id, path in file_ids.items()}
    expected: dict[int, Path] = {}
    for raw_value in raw_values:
        if "=" not in raw_value:
            raise ValueError(f"expected file assertion must use NITRO_PATH=FILE syntax: {raw_value!r}")
        raw_path, raw_source = raw_value.split("=", 1)
        nitro_path: str = raw_path.replace("\\", "/").lstrip("/")
        if nitro_path not in path_to_id:
            raise ValueError(f"NitroFS path is not present in _file_IDs.txt: {nitro_path!r}")
        source: Path = Path(raw_source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"expected replacement file does not exist: {source}")
        expected[path_to_id[nitro_path]] = source
    return expected


def validate_component(rom: Path, component: Path, offset: int) -> None:
    expected: bytes = component.read_bytes()
    actual: bytes = read_range(rom, offset, offset + len(expected))
    if actual != expected:
        raise ValueError(f"ROM component does not match {component.name} at 0x{offset:x}")


def parse_args() -> argparse.Namespace:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Validate a Guardian Signs Nintendo DS image rebuilt from Pokengineering components.")
    parser.add_argument("rom", type=Path)
    parser.add_argument("--components", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expect", action="append", default=[], metavar="NITRO_PATH=FILE")
    return parser.parse_args()


def main() -> int:
    args: argparse.Namespace = parse_args()
    rom: Path = args.rom.expanduser().resolve()
    root: Path = args.components.expanduser().resolve()
    if not rom.is_file():
        raise FileNotFoundError(f"ROM does not exist: {rom}")
    header_source: Path = root / "header.bin"
    file_ids_source: Path = root / "_file_IDs.txt"
    original_fat_source: Path = root / "fat.bin"
    for path in (header_source, file_ids_source, original_fat_source):
        if not path.is_file():
            raise FileNotFoundError(f"missing validation component: {path}")
    original_header: bytes = header_source.read_bytes()
    header_size: int = read_u32(original_header, HEADER_SIZE_FIELD)
    header: bytes = read_range(rom, 0, header_size)
    stored_crc: int = struct.unpack_from("<H", header, HEADER_CRC_FIELD)[0]
    calculated_crc: int = crc16_nintendo(header[:HEADER_CRC_END])
    if stored_crc != calculated_crc:
        raise ValueError(f"header CRC mismatch: stored 0x{stored_crc:04x}, calculated 0x{calculated_crc:04x}")
    used_size: int = read_u32(header, USED_ROM_SIZE_FIELD)
    rom_size: int = rom.stat().st_size
    capacity: int = cartridge_capacity(header)
    if used_size > rom_size:
        raise ValueError("header used-ROM size extends beyond the image")
    if rom_size not in (used_size, capacity):
        raise ValueError(f"ROM size {rom_size} is neither trimmed used size {used_size} nor cartridge capacity {capacity}")
    if header[DEVICE_CAPACITY_FIELD] != original_header[DEVICE_CAPACITY_FIELD]:
        raise ValueError("device-capacity byte changed unexpectedly")
    component_specs: tuple[tuple[str, int], ...] = (
        ("arm9.bin", read_u32(header, ARM9_OFFSET_FIELD)),
        ("a9ovr.bin", read_u32(header, ARM9_OVT_OFFSET_FIELD)),
        ("a9ovr_data.bin", read_u32(header, ARM9_OVT_OFFSET_FIELD) + read_u32(header, ARM9_OVT_SIZE_FIELD)),
        ("arm7.bin", read_u32(header, ARM7_OFFSET_FIELD)),
        ("fnt.bin", read_u32(header, FNT_OFFSET_FIELD)),
        ("itl.bin", read_u32(header, BANNER_OFFSET_FIELD)),
    )
    for name, offset in component_specs:
        component: Path = root / name
        if not component.is_file():
            raise FileNotFoundError(f"missing validation component: {component}")
        validate_component(rom, component, offset)
    if read_u32(header, ARM9_SIZE_FIELD) != read_u32(original_header, ARM9_SIZE_FIELD):
        raise ValueError("ARM9 executable size changed unexpectedly")
    if read_u32(header, ARM7_SIZE_FIELD) != read_u32(original_header, ARM7_SIZE_FIELD):
        raise ValueError("ARM7 executable size changed unexpectedly")
    if read_u32(header, FNT_SIZE_FIELD) != read_u32(original_header, FNT_SIZE_FIELD):
        raise ValueError("FNT size changed unexpectedly")
    fat_offset: int = read_u32(header, FAT_OFFSET_FIELD)
    fat_size: int = read_u32(header, FAT_SIZE_FIELD)
    fat: list[tuple[int, int]] = parse_fat_bytes(read_range(rom, fat_offset, fat_offset + fat_size))
    original_fat: list[tuple[int, int]] = parse_fat_bytes(original_fat_source.read_bytes())
    file_ids: dict[int, str] = parse_file_ids(file_ids_source, len(fat))
    if not file_ids:
        raise ValueError("no NitroFS file IDs are mapped")
    first_nitro_id: int = min(file_ids)
    if fat[:first_nitro_id] != original_fat[:first_nitro_id]:
        raise ValueError("one or more overlay FAT entries changed")
    physical_ids: list[int] = sorted(file_ids, key=lambda file_id: (fat[file_id][0], fat[file_id][1], file_id))
    previous_end: int = read_u32(header, BANNER_OFFSET_FIELD) + (root / "itl.bin").stat().st_size
    for file_id in physical_ids:
        start, end = fat[file_id]
        if start < previous_end or end < start or end > used_size:
            raise ValueError(f"NitroFS FAT file ID 0x{file_id:x} has an invalid rebuilt physical range")
        previous_end = end
    expected: dict[int, Path] = parse_expected(args.expect, file_ids)
    for file_id, source in expected.items():
        start, end = fat[file_id]
        if read_range(rom, start, end) != source.read_bytes():
            raise ValueError(f"replacement verification failed for FAT file ID 0x{file_id:x} ({file_ids[file_id]})")
    print(f"validated Nintendo DS image: {rom}")
    print(f"header CRC: 0x{stored_crc:04x}")
    print(f"used ROM size: {used_size} bytes")
    print(f"physical ROM size: {rom_size} bytes")
    print(f"overlay FAT entries preserved: {first_nitro_id}")
    print(f"NitroFS entries validated: {len(file_ids)}")
    print(f"replacement assertions passed: {len(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
