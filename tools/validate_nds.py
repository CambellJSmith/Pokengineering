#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path

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


def read_range(path: Path, start: int, end: int) -> bytes:  # Read one exact ROM range and reject truncation.
    with path.open("rb") as source:  # Open the ROM only for the bounded range being inspected.
        source.seek(start)  # Move to the requested absolute ROM offset.
        data: bytes = source.read(end - start)  # Read exactly the requested byte count.
    if len(data) != end - start:  # Reject a short read instead of validating incomplete data.
        raise ValueError(f"ROM range 0x{start:x}-0x{end:x} is truncated")  # Report the invalid range.
    return data  # Return the complete verified slice.


def parse_fat_bytes(data: bytes) -> list[tuple[int, int]]:  # Decode a FAT table already read from the ROM.
    if len(data) % FAT_ENTRY_SIZE != 0:  # Require complete start/end pairs.
        raise ValueError("ROM FAT size is not divisible by eight")  # Report malformed FAT metadata.
    return [struct.unpack_from("<II", data, offset) for offset in range(0, len(data), FAT_ENTRY_SIZE)]  # Preserve file-ID ordering.


def parse_expected(raw_values: list[str], file_ids: dict[int, str]) -> dict[int, Path]:  # Resolve NITRO_PATH=FILE verification assertions.
    path_to_id: dict[str, int] = {path.replace("\\", "/").lstrip("/"): file_id for file_id, path in file_ids.items()}  # Build an exact normalized path lookup.
    expected: dict[int, Path] = {}  # Store expected replacement sources by FAT ID.
    for raw_value in raw_values:  # Parse every user-supplied assertion independently.
        if "=" not in raw_value:  # Require both the NitroFS target and local source file.
            raise ValueError(f"expected file assertion must use NITRO_PATH=FILE syntax: {raw_value!r}")  # Explain the accepted syntax.
        raw_path, raw_source = raw_value.split("=", 1)  # Split only the first equals sign.
        nitro_path: str = raw_path.replace("\\", "/").lstrip("/")  # Normalize the in-ROM path.
        if nitro_path not in path_to_id:  # Refuse a target absent from the file-ID map.
            raise ValueError(f"NitroFS path is not present in _file_IDs.txt: {nitro_path!r}")  # Report the unresolved path.
        source: Path = Path(raw_source).expanduser().resolve()  # Resolve the expected source bytes deterministically.
        if not source.is_file():  # Require the expected file to exist before scanning the ROM.
            raise FileNotFoundError(f"expected replacement file does not exist: {source}")  # Report the missing assertion input.
        expected[path_to_id[nitro_path]] = source  # Record the expected bytes under their FAT file ID.
    return expected  # Return all replacement assertions.


def validate_component(rom: Path, component: Path, offset: int) -> None:  # Verify one fixed extracted component survived reconstruction byte-for-byte.
    expected: bytes = component.read_bytes()  # Read the comparatively small fixed component.
    actual: bytes = read_range(rom, offset, offset + len(expected))  # Read the same range from the rebuilt ROM.
    if actual != expected:  # Reject any unexpected modification to executable or metadata regions.
        raise ValueError(f"ROM component does not match {component.name} at 0x{offset:x}")  # Identify the mismatching fixed region.


def parse_args() -> argparse.Namespace:  # Define independent rebuilt-ROM validation options.
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Validate a Guardian Signs Nintendo DS image rebuilt from Pokengineering components.")  # Create the CLI parser.
    parser.add_argument("rom", type=Path)  # Accept the rebuilt .nds image to validate.
    parser.add_argument("--components", type=Path, default=Path(__file__).resolve().parents[1])  # Accept an alternate component directory.
    parser.add_argument("--expect", action="append", default=[], metavar="NITRO_PATH=FILE")  # Allow exact replacement-content assertions.
    return parser.parse_args()  # Parse and return command-line arguments.


def main() -> int:  # Validate header CRC, fixed sections, FAT geometry, and optional replacement bytes.
    args: argparse.Namespace = parse_args()  # Read command-line options once.
    rom: Path = args.rom.expanduser().resolve()  # Normalize the rebuilt ROM path.
    root: Path = args.components.expanduser().resolve()  # Normalize the extracted-component directory.
    if not rom.is_file():  # Require the rebuilt ROM to exist.
        raise FileNotFoundError(f"ROM does not exist: {rom}")  # Report the missing output image.
    header_source: Path = root / "header.bin"  # Resolve the original complete header region.
    file_ids_source: Path = root / "_file_IDs.txt"  # Resolve the NitroFS file-ID mapping.
    original_fat_source: Path = root / "fat.bin"  # Resolve the original FAT so overlay entries can be compared.
    for path in (header_source, file_ids_source, original_fat_source):  # Validate all metadata sources used for comparison.
        if not path.is_file():  # Refuse partial validation when an original metadata source is missing.
            raise FileNotFoundError(f"missing validation component: {path}")  # Report the specific missing file.
    original_header: bytes = header_source.read_bytes()  # Load the original header for fixed-field comparisons.
    header_size: int = read_u32(original_header, HEADER_SIZE_FIELD)  # Read the complete header-region size.
    header: bytes = read_range(rom, 0, header_size)  # Read the reconstructed header region from the ROM.
    stored_crc: int = struct.unpack_from("<H", header, HEADER_CRC_FIELD)[0]  # Read the checksum stored in the rebuilt header.
    calculated_crc: int = crc16_nintendo(header[:HEADER_CRC_END])  # Recalculate the checksum over the defined DS header range.
    if stored_crc != calculated_crc:  # Reject a ROM whose header metadata was changed without a matching checksum update.
        raise ValueError(f"header CRC mismatch: stored 0x{stored_crc:04x}, calculated 0x{calculated_crc:04x}")  # Report both values for debugging.
    used_size: int = read_u32(header, USED_ROM_SIZE_FIELD)  # Read the rebuilt first-unused-byte position.
    rom_size: int = rom.stat().st_size  # Read the physical output file size.
    capacity: int = cartridge_capacity(header)  # Calculate the retail cartridge capacity encoded by the header.
    if used_size > rom_size:  # Ensure the declared used data fits inside the physical output image.
        raise ValueError("header used-ROM size extends beyond the image")  # Report a truncated build.
    if rom_size not in (used_size, capacity):  # Accept either a trimmed image or a full-capacity cartridge image.
        raise ValueError(f"ROM size {rom_size} is neither trimmed used size {used_size} nor cartridge capacity {capacity}")  # Report an unexpected physical size.
    if header[DEVICE_CAPACITY_FIELD] != original_header[DEVICE_CAPACITY_FIELD]:  # Preserve the retail device-capacity metadata.
        raise ValueError("device-capacity byte changed unexpectedly")  # Report unintended cartridge geometry changes.
    component_specs: tuple[tuple[str, int], ...] = (  # Describe every fixed reconstructed region that must remain byte-identical.
        ("arm9.bin", read_u32(header, ARM9_OFFSET_FIELD)),  # Validate ARM9 plus its extracted footer at the original offset.
        ("a9ovr.bin", read_u32(header, ARM9_OVT_OFFSET_FIELD)),  # Validate the ARM9 overlay table.
        ("a9ovr_data.bin", read_u32(header, ARM9_OVT_OFFSET_FIELD) + read_u32(header, ARM9_OVT_SIZE_FIELD)),  # Validate the packed overlay payload region.
        ("arm7.bin", read_u32(header, ARM7_OFFSET_FIELD)),  # Validate ARM7.
        ("fnt.bin", read_u32(header, FNT_OFFSET_FIELD)),  # Validate the NitroFS filename table.
        ("itl.bin", read_u32(header, BANNER_OFFSET_FIELD)),  # Validate the icon/title block.
    )  # Finish the fixed-component specification.
    for name, offset in component_specs:  # Compare every fixed region with its extracted source.
        component: Path = root / name  # Resolve the original component file.
        if not component.is_file():  # Require all fixed sources for meaningful byte comparison.
            raise FileNotFoundError(f"missing validation component: {component}")  # Report the missing component.
        validate_component(rom, component, offset)  # Require an exact byte-for-byte match at the declared ROM offset.
    if read_u32(header, ARM9_SIZE_FIELD) != read_u32(original_header, ARM9_SIZE_FIELD):  # Preserve the ARM9 executable size metadata.
        raise ValueError("ARM9 executable size changed unexpectedly")  # Report unintended header modification.
    if read_u32(header, ARM7_SIZE_FIELD) != read_u32(original_header, ARM7_SIZE_FIELD):  # Preserve the ARM7 executable size metadata.
        raise ValueError("ARM7 executable size changed unexpectedly")  # Report unintended header modification.
    if read_u32(header, FNT_SIZE_FIELD) != read_u32(original_header, FNT_SIZE_FIELD):  # Preserve the filename-table size metadata.
        raise ValueError("FNT size changed unexpectedly")  # Report unintended header modification.
    fat_offset: int = read_u32(header, FAT_OFFSET_FIELD)  # Read the rebuilt FAT location from the header.
    fat_size: int = read_u32(header, FAT_SIZE_FIELD)  # Read the rebuilt FAT byte count from the header.
    fat: list[tuple[int, int]] = parse_fat_bytes(read_range(rom, fat_offset, fat_offset + fat_size))  # Decode the FAT directly from the rebuilt image.
    original_fat: list[tuple[int, int]] = parse_fat_bytes(original_fat_source.read_bytes())  # Decode the original FAT for overlay comparison.
    file_ids: dict[int, str] = parse_file_ids(file_ids_source, len(fat))  # Decode mapped NitroFS paths using the rebuilt FAT entry count.
    if not file_ids:  # Refuse to claim success without a mapped filesystem.
        raise ValueError("no NitroFS file IDs are mapped")  # Report missing file-ID metadata.
    first_nitro_id: int = min(file_ids)  # Locate the boundary after the overlay FAT entries.
    if fat[:first_nitro_id] != original_fat[:first_nitro_id]:  # Ensure overlay locations were never repacked with NitroFS.
        raise ValueError("one or more overlay FAT entries changed")  # Report a dangerous overlay-table mutation.
    previous_end: int = read_u32(header, BANNER_OFFSET_FIELD)  # Start broad ordering checks after the fixed icon/title region.
    for file_id in sorted(file_ids):  # Validate every mapped NitroFS FAT range.
        start, end = fat[file_id]  # Read this file's rebuilt absolute range.
        if start < previous_end or end < start or end > used_size:  # Reject overlap, reversal, or an out-of-bounds endpoint.
            raise ValueError(f"NitroFS FAT file ID 0x{file_id:x} has an invalid rebuilt range")  # Identify the malformed entry.
        previous_end = end  # Advance the monotonic filesystem boundary.
    expected: dict[int, Path] = parse_expected(args.expect, file_ids)  # Resolve any exact replacement-content assertions.
    for file_id, source in expected.items():  # Verify each intentional modification against the final ROM bytes.
        start, end = fat[file_id]  # Read the rebuilt FAT range for this expected replacement.
        if read_range(rom, start, end) != source.read_bytes():  # Require the in-ROM file to equal the replacement source exactly.
            raise ValueError(f"replacement verification failed for FAT file ID 0x{file_id:x} ({file_ids[file_id]})")  # Identify the failed replacement.
    print(f"validated Nintendo DS image: {rom}")  # Report the validated image path.
    print(f"header CRC: 0x{stored_crc:04x}")  # Report the valid recalculated header checksum.
    print(f"used ROM size: {used_size} bytes")  # Report the internally declared used-ROM extent.
    print(f"physical ROM size: {rom_size} bytes")  # Report whether the validated image is trimmed or full-capacity.
    print(f"overlay FAT entries preserved: {first_nitro_id}")  # Report the untouched overlay FAT count.
    print(f"NitroFS entries validated: {len(file_ids)}")  # Report the number of ordered in-bounds filesystem files.
    print(f"replacement assertions passed: {len(expected)}")  # Report how many intentional modded files were compared exactly.
    return 0  # Signal successful independent ROM validation.


if __name__ == "__main__":  # Run validation only when executed as a command-line tool.
    raise SystemExit(main())  # Propagate validation success or failure to the shell.
