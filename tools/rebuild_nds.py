#!/usr/bin/env python3
from __future__ import annotations

import argparse  # Parse component, replacement, output, and trim options.
import mmap  # Access the large original NitroFS payload without copying it into memory.
import struct  # Decode and update little-endian Nintendo DS header and FAT fields.
from pathlib import Path  # Represent component, replacement, and output paths safely.
from typing import BinaryIO, Final  # Type file handles and immutable format constants.

from extract_nitrofs_file import infer_payload_base, parse_fat, parse_file_ids  # Reuse the validated FAT-alignment logic from the previous milestone.

ARM9_OFFSET_FIELD: Final[int] = 0x20  # Nintendo DS header field containing the ARM9 ROM offset.
ARM9_SIZE_FIELD: Final[int] = 0x2C  # Nintendo DS header field containing the ARM9 executable size.
ARM7_OFFSET_FIELD: Final[int] = 0x30  # Nintendo DS header field containing the ARM7 ROM offset.
ARM7_SIZE_FIELD: Final[int] = 0x3C  # Nintendo DS header field containing the ARM7 executable size.
FNT_OFFSET_FIELD: Final[int] = 0x40  # Nintendo DS header field containing the NitroFS name-table offset.
FNT_SIZE_FIELD: Final[int] = 0x44  # Nintendo DS header field containing the NitroFS name-table size.
FAT_OFFSET_FIELD: Final[int] = 0x48  # Nintendo DS header field containing the NitroFS allocation-table offset.
FAT_SIZE_FIELD: Final[int] = 0x4C  # Nintendo DS header field containing the NitroFS allocation-table size.
ARM9_OVT_OFFSET_FIELD: Final[int] = 0x50  # Nintendo DS header field containing the ARM9 overlay-table offset.
ARM9_OVT_SIZE_FIELD: Final[int] = 0x54  # Nintendo DS header field containing the ARM9 overlay-table size.
BANNER_OFFSET_FIELD: Final[int] = 0x68  # Nintendo DS header field containing the icon/title banner offset.
USED_ROM_SIZE_FIELD: Final[int] = 0x80  # Nintendo DS header field containing the used ROM byte count.
HEADER_SIZE_FIELD: Final[int] = 0x84  # Nintendo DS header field containing the full header-region size.
DEVICE_CAPACITY_FIELD: Final[int] = 0x14  # Nintendo DS header byte encoding the cartridge capacity.
HEADER_CRC_FIELD: Final[int] = 0x15E  # Nintendo DS header field containing the CRC over bytes 0x0000-0x015D.
HEADER_CRC_END: Final[int] = 0x15E  # Header CRC input ends immediately before the stored checksum.
COPY_CHUNK_SIZE: Final[int] = 1024 * 1024  # Copy large ROM regions in one-megabyte chunks.
ERASE_BYTE: Final[int] = 0xFF  # Unused Nintendo DS cartridge bytes are conventionally filled with 0xFF.


def read_u32(data: bytes | bytearray, offset: int) -> int:  # Decode one 32-bit little-endian header field.
    return struct.unpack_from("<I", data, offset)[0]  # Return the decoded integer.


def write_u32(data: bytearray, offset: int, value: int) -> None:  # Replace one 32-bit little-endian header field.
    struct.pack_into("<I", data, offset, value)  # Write the integer directly into the mutable header buffer.


def cartridge_capacity(header: bytes | bytearray) -> int:  # Convert the Nintendo DS device-capacity exponent into bytes.
    exponent: int = header[DEVICE_CAPACITY_FIELD]  # Read the cartridge-capacity exponent from the header.
    if exponent > 20:  # Reject implausible values before shifting by an arbitrary amount.
        raise ValueError(f"unsupported Nintendo DS device-capacity exponent: {exponent}")  # Report malformed metadata.
    return (128 * 1024) << exponent  # Nintendo DS capacity is 128 KiB shifted by the encoded exponent.


def crc16_nintendo(data: bytes | bytearray) -> int:  # Calculate the CRC-16 used by the Nintendo DS header.
    crc: int = 0xFFFF  # Nintendo initializes this checksum to all one bits.
    for value in data:  # Fold each input byte into the running checksum.
        crc ^= value  # XOR the next byte into the low CRC byte.
        for _ in range(8):  # Process all eight bits of the input byte.
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1  # Apply the reflected Nintendo polynomial when the low bit is set.
    return crc & 0xFFFF  # Return the final 16-bit checksum.


def parse_replacements(raw_values: list[str], file_ids: dict[int, str]) -> dict[int, Path]:  # Resolve repeated NITRO_PATH=FILE arguments to FAT file IDs.
    path_to_id: dict[str, int] = {path.replace("\\", "/").lstrip("/"): file_id for file_id, path in file_ids.items()}  # Build an exact normalized NitroFS path lookup.
    replacements: dict[int, Path] = {}  # Store one replacement file for each resolved FAT ID.
    for raw_value in raw_values:  # Parse every command-line replacement independently.
        if "=" not in raw_value:  # Require an explicit NitroFS path and local source file.
            raise ValueError(f"replacement must use NITRO_PATH=FILE syntax: {raw_value!r}")  # Explain the accepted syntax.
        raw_nitro_path, raw_source = raw_value.split("=", 1)  # Split only on the first equals sign so local paths may contain additional equals signs.
        nitro_path: str = raw_nitro_path.replace("\\", "/").lstrip("/")  # Normalize the requested in-ROM path.
        if nitro_path not in path_to_id:  # Refuse unknown or ambiguous NitroFS paths.
            raise ValueError(f"NitroFS path is not present in _file_IDs.txt: {nitro_path!r}")  # Report the unresolved path.
        source: Path = Path(raw_source).expanduser().resolve()  # Resolve the local replacement to a deterministic absolute path.
        if not source.is_file():  # Require replacement bytes to exist before starting a large ROM build.
            raise FileNotFoundError(f"replacement file does not exist: {source}")  # Report the missing local file.
        file_id: int = path_to_id[nitro_path]  # Resolve the normalized NitroFS path to its FAT index.
        if file_id in replacements:  # Prevent two arguments from silently competing for the same FAT entry.
            raise ValueError(f"duplicate replacement for FAT file ID 0x{file_id:x}: {nitro_path}")  # Report the duplicate target.
        replacements[file_id] = source  # Record the validated replacement source.
    return replacements  # Return all requested replacements keyed by FAT file ID.


def validate_nitrofs_ranges(
    fat: list[tuple[int, int]],
    file_ids: dict[int, str],
    payload_base: int,
    payload_size: int,
) -> list[int]:  # Validate that the mapped NitroFS files form a complete, non-overlapping tail of the FAT.
    file_id_order: list[int] = sorted(file_ids)  # Preserve the numeric FAT-ID set separately from physical ROM ordering.
    if not file_id_order:  # Refuse to rebuild a ROM without any named NitroFS files.
        raise ValueError("_file_IDs.txt does not contain any NitroFS file IDs")  # Explain why the filesystem cannot be rebuilt.
    expected_ids: list[int] = list(range(file_id_order[0], len(fat)))  # Guardian Signs maps every FAT entry after its overlay files into NitroFS.
    if file_id_order != expected_ids:  # Reject missing IDs because gap ownership would otherwise be ambiguous.
        raise ValueError("mapped NitroFS file IDs are not a contiguous tail of the FAT")  # Require a complete filesystem mapping.
    nitro_ids: list[int] = sorted(file_id_order, key=lambda file_id: (fat[file_id][0], fat[file_id][1], file_id))  # Repack by physical ROM order because late Guardian Signs FAT IDs are not strictly address-ordered.
    previous_end: int = payload_base  # Begin ordering checks at the validated fat_data.bin base.
    for file_id in nitro_ids:  # Validate every mapped file in physical ROM order before writing output.
        start, end = fat[file_id]  # Read the original absolute ROM range.
        if start < previous_end or end < start:  # Reject overlapping or reversed physical FAT ranges.
            raise ValueError(f"FAT file ID 0x{file_id:x} overlaps an earlier physical NitroFS range")  # Identify the invalid entry.
        relative_end: int = end - payload_base  # Translate the absolute end into fat_data.bin coordinates.
        if start < payload_base or relative_end > payload_size:  # Ensure the complete file fits in the raw payload.
            raise ValueError(f"FAT file ID 0x{file_id:x} falls outside fat_data.bin")  # Report a bad range or base.
        previous_end = end  # Advance the monotonic physical range check.
    return nitro_ids  # Return the validated physical NitroFS order for gap-preserving repacking.


def validate_fixed_layout(root: Path, header: bytes, payload_base: int) -> dict[str, tuple[Path, int]]:  # Verify extracted fixed ROM components against their header offsets and sizes.
    header_size: int = read_u32(header, HEADER_SIZE_FIELD)  # Read the header-region size from the original cartridge metadata.
    if len(header) != header_size:  # Require the extracted header blob to cover the complete fixed header region.
        raise ValueError(f"header.bin is {len(header)} bytes but the DS header declares {header_size}")  # Report a truncated or mismatched header.
    arm9_path: Path = root / "arm9.bin"  # Resolve the extracted ARM9 executable and footer.
    arm7_path: Path = root / "arm7.bin"  # Resolve the extracted ARM7 executable.
    fnt_path: Path = root / "fnt.bin"  # Resolve the NitroFS filename table.
    fat_path: Path = root / "fat.bin"  # Resolve the original FAT table.
    a9ovr_path: Path = root / "a9ovr.bin"  # Resolve the ARM9 overlay table.
    a9ovr_data_path: Path = root / "a9ovr_data.bin"  # Resolve the packed ARM9 overlay payload region.
    itl_path: Path = root / "itl.bin"  # Resolve the icon/title banner region.
    for path in (arm9_path, arm7_path, fnt_path, fat_path, a9ovr_path, a9ovr_data_path, itl_path):  # Check every required extracted fixed component.
        if not path.is_file():  # Refuse to emit a partial ROM if any fixed region is missing.
            raise FileNotFoundError(f"missing extracted ROM component: {path}")  # Report the specific required component.
    arm9_offset: int = read_u32(header, ARM9_OFFSET_FIELD)  # Read where ARM9 begins in the ROM.
    arm9_size: int = read_u32(header, ARM9_SIZE_FIELD)  # Read the executable portion size from the header.
    arm9_ovt_offset: int = read_u32(header, ARM9_OVT_OFFSET_FIELD)  # Read where the ARM9 overlay table begins.
    arm9_ovt_size: int = read_u32(header, ARM9_OVT_SIZE_FIELD)  # Read the ARM9 overlay-table byte count.
    arm7_offset: int = read_u32(header, ARM7_OFFSET_FIELD)  # Read where ARM7 begins in the ROM.
    arm7_size: int = read_u32(header, ARM7_SIZE_FIELD)  # Read the ARM7 executable byte count.
    fnt_offset: int = read_u32(header, FNT_OFFSET_FIELD)  # Read where the NitroFS filename table begins.
    fnt_size: int = read_u32(header, FNT_SIZE_FIELD)  # Read the NitroFS filename-table byte count.
    fat_offset: int = read_u32(header, FAT_OFFSET_FIELD)  # Read where the FAT table begins.
    fat_size: int = read_u32(header, FAT_SIZE_FIELD)  # Read the FAT-table byte count.
    banner_offset: int = read_u32(header, BANNER_OFFSET_FIELD)  # Read where the icon/title data begins.
    arm9_length: int = arm9_path.stat().st_size  # Include any extracted ARM9 footer bytes in the written region.
    if arm9_length < arm9_size or arm9_offset + arm9_length > arm9_ovt_offset:  # Require ARM9 plus its footer to fit before the overlay table.
        raise ValueError("arm9.bin does not fit between the declared ARM9 and overlay-table offsets")  # Report inconsistent extraction geometry.
    if a9ovr_path.stat().st_size != arm9_ovt_size:  # Require the overlay table to match the exact header-declared size.
        raise ValueError("a9ovr.bin size does not match the Nintendo DS header")  # Report the overlay-table mismatch.
    overlay_data_offset: int = arm9_ovt_offset + arm9_ovt_size  # Guardian Signs stores overlay payloads immediately after its overlay table.
    if overlay_data_offset + a9ovr_data_path.stat().st_size != arm7_offset:  # Require the extracted overlay payload to end exactly where ARM7 begins.
        raise ValueError("a9ovr_data.bin does not exactly span the overlay-data region before ARM7")  # Report a missing or extra overlay byte range.
    if arm7_path.stat().st_size != arm7_size:  # Require ARM7 bytes to match their declared executable size.
        raise ValueError("arm7.bin size does not match the Nintendo DS header")  # Report the ARM7 mismatch.
    if fnt_path.stat().st_size != fnt_size:  # Require the filename table to match the header.
        raise ValueError("fnt.bin size does not match the Nintendo DS header")  # Report the filename-table mismatch.
    if fat_path.stat().st_size != fat_size:  # Require the FAT table to match the header.
        raise ValueError("fat.bin size does not match the Nintendo DS header")  # Report the FAT-table mismatch.
    if banner_offset + itl_path.stat().st_size > payload_base:  # Prevent icon/title data from colliding with the rebuilt NitroFS payload.
        raise ValueError("itl.bin overlaps the validated NitroFS payload base")  # Report incompatible fixed-region extraction.
    return {  # Return each fixed extracted component and the absolute ROM offset where it belongs.
        "arm9": (arm9_path, arm9_offset),  # Place ARM9 at its header-declared ROM offset.
        "a9ovr": (a9ovr_path, arm9_ovt_offset),  # Place the overlay table at its header-declared offset.
        "a9ovr_data": (a9ovr_data_path, overlay_data_offset),  # Place overlay payloads immediately after the overlay table.
        "arm7": (arm7_path, arm7_offset),  # Place ARM7 at its header-declared ROM offset.
        "fnt": (fnt_path, fnt_offset),  # Place the filename table at its header-declared ROM offset.
        "itl": (itl_path, banner_offset),  # Place the icon/title block at its header-declared ROM offset.
    }  # Complete the validated fixed-layout mapping.


def fill_file(destination: BinaryIO, size: int, value: int) -> None:  # Initialize an output ROM with a deterministic erased-byte pattern.
    block: bytes = bytes([value]) * COPY_CHUNK_SIZE  # Prepare one reusable chunk instead of allocating the complete ROM at once.
    remaining: int = size  # Track the number of bytes still needing initialization.
    while remaining > 0:  # Fill the requested output extent in bounded chunks.
        chunk_size: int = min(remaining, len(block))  # Avoid writing past the requested final size.
        destination.write(block[:chunk_size])  # Append erased bytes to the output image.
        remaining -= chunk_size  # Record the initialized byte count.


def copy_file_at(destination: BinaryIO, source_path: Path, offset: int) -> None:  # Copy one extracted fixed component to its absolute ROM offset.
    destination.seek(offset)  # Position the output stream at the component's declared location.
    with source_path.open("rb") as source:  # Stream the source component without loading it all into memory.
        while chunk := source.read(COPY_CHUNK_SIZE):  # Read bounded chunks until the component is exhausted.
            destination.write(chunk)  # Copy each chunk verbatim into the reconstructed ROM.


def copy_mmap_range(destination: BinaryIO, payload: mmap.mmap, start: int, end: int) -> None:  # Copy one bounded slice from fat_data.bin to the output ROM.
    position: int = start  # Begin at the requested payload-relative byte.
    while position < end:  # Continue until the complete requested range has been copied.
        chunk_end: int = min(end, position + COPY_CHUNK_SIZE)  # Limit each mmap slice to a bounded allocation.
        destination.write(payload[position:chunk_end])  # Write the current raw payload chunk.
        position = chunk_end  # Advance to the next unread payload byte.


def rebuild_filesystem(
    destination: BinaryIO,
    payload: mmap.mmap,
    fat: list[tuple[int, int]],
    nitro_ids: list[int],
    payload_base: int,
    replacements: dict[int, Path],
) -> tuple[list[tuple[int, int]], int]:  # Repack NitroFS while preserving original inter-file gap bytes and updating absolute FAT ranges.
    new_fat: list[tuple[int, int]] = list(fat)  # Preserve overlay FAT entries and mutate only mapped NitroFS entries.
    source_cursor: int = 0  # Track the original payload-relative end of the previously processed physical file.
    output_cursor: int = payload_base  # Track the next absolute ROM position in the rebuilt NitroFS region.
    destination.seek(payload_base)  # Begin writing at the validated original NitroFS base.
    for file_id in nitro_ids:  # Repack each mapped NitroFS file in physical ROM order.
        old_start, old_end = fat[file_id]  # Read the file's original absolute range.
        relative_start: int = old_start - payload_base  # Translate its start into the original raw payload.
        relative_end: int = old_end - payload_base  # Translate its end into the original raw payload.
        copy_mmap_range(destination, payload, source_cursor, relative_start)  # Preserve the exact original padding bytes before this file.
        output_cursor += relative_start - source_cursor  # Advance the absolute output cursor across the preserved gap.
        new_start: int = output_cursor  # Record the replacement or original file's new absolute start.
        if file_id in replacements:  # Substitute user-provided bytes for requested NitroFS paths.
            with replacements[file_id].open("rb") as replacement:  # Stream the local replacement without an unnecessary full-file allocation.
                while chunk := replacement.read(COPY_CHUNK_SIZE):  # Copy the complete replacement in bounded chunks.
                    destination.write(chunk)  # Write the replacement bytes into the rebuilt filesystem.
                    output_cursor += len(chunk)  # Advance by the replacement size rather than the original size.
        else:  # Preserve untouched game files byte-for-byte.
            copy_mmap_range(destination, payload, relative_start, relative_end)  # Copy the original file bytes exactly.
            output_cursor += relative_end - relative_start  # Advance by the original file size.
        new_fat[file_id] = (new_start, output_cursor)  # Store the rebuilt absolute start/end range for this FAT ID.
        source_cursor = relative_end  # Advance the source cursor to the end of the original physical file before preserving its following gap.
    copy_mmap_range(destination, payload, source_cursor, len(payload))  # Preserve the original trailing payload bytes after the final NitroFS file.
    output_cursor += len(payload) - source_cursor  # Include the preserved trailing bytes in the new used-ROM size.
    return new_fat, output_cursor  # Return the updated FAT and the first unused absolute ROM byte.


def encode_fat(entries: list[tuple[int, int]]) -> bytes:  # Serialize updated FAT ranges in their original file-ID order.
    return b"".join(struct.pack("<II", start, end) for start, end in entries)  # Encode each absolute start/end pair consecutively.


def parse_args() -> argparse.Namespace:  # Define the command-line interface for deterministic Nintendo DS ROM reconstruction.
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Rebuild a Pokémon Ranger: Guardian Signs Nintendo DS ROM from extracted components and optional NitroFS replacements.")  # Create the CLI parser.
    parser.add_argument("--components", type=Path, default=Path(__file__).resolve().parents[1], help="directory containing header.bin, FAT/FNT, executables, overlays, itl.bin, fat_data.bin, and _file_IDs.txt")  # Accept an alternate extracted-component directory.
    parser.add_argument("--output", type=Path, required=True, help="destination .nds image")  # Require an explicit output path so the source data cannot be overwritten accidentally.
    parser.add_argument("--replace", action="append", default=[], metavar="NITRO_PATH=FILE", help="replace one NitroFS file; may be supplied multiple times")  # Allow any number of path-based filesystem replacements.
    parser.add_argument("--trim", action="store_true", help="emit only the used ROM region instead of padding to the cartridge capacity")  # Support smaller emulator-oriented output images.
    return parser.parse_args()  # Parse and return the command-line arguments.


def main() -> int:  # Validate extracted components, rebuild NitroFS/FAT, update the header, and emit a deterministic .nds image.
    args: argparse.Namespace = parse_args()  # Read command-line options once.
    root: Path = args.components.expanduser().resolve()  # Normalize the extracted-component directory.
    output_path: Path = args.output.expanduser().resolve()  # Normalize the destination ROM path.
    header_path: Path = root / "header.bin"  # Resolve the complete Nintendo DS header region.
    fat_path: Path = root / "fat.bin"  # Resolve the original file-allocation table.
    fat_data_path: Path = root / "fat_data.bin"  # Resolve the raw NitroFS payload exported by NDSFactory.
    file_ids_path: Path = root / "_file_IDs.txt"  # Resolve the FAT-ID to NitroFS-path mapping.
    for path in (header_path, fat_path, fat_data_path, file_ids_path):  # Validate the core metadata and payload inputs before starting.
        if not path.is_file():  # Refuse to guess when a required extraction component is missing.
            raise FileNotFoundError(f"missing extracted ROM component: {path}")  # Report the exact missing file.
    original_header: bytes = header_path.read_bytes()  # Load the small header region for field parsing and checksum updates.
    fat: list[tuple[int, int]] = parse_fat(fat_path)  # Decode the original FAT ranges.
    file_ids: dict[int, str] = parse_file_ids(file_ids_path, len(fat))  # Decode the complete mapped NitroFS tail.
    replacements: dict[int, Path] = parse_replacements(args.replace, file_ids)  # Resolve requested path replacements to FAT IDs.
    with fat_data_path.open("rb") as source:  # Keep the large raw filesystem payload open while it is mapped and rebuilt.
        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as payload:  # Map fat_data.bin read-only for validation and streaming copies.
            payload_base, signature_score, bounds_score = infer_payload_base(payload, fat, file_ids)  # Reuse the signature-validated FAT base from the localization milestone.
            nitro_ids: list[int] = validate_nitrofs_ranges(fat, file_ids, payload_base, len(payload))  # Require a complete non-overlapping NitroFS mapping before modifying offsets.
            first_nitro_id: int = min(file_ids)  # Record the numeric FAT boundary after the ARM9 overlay entries independently of physical file ordering.
            if any(file_id < first_nitro_id for file_id in replacements):  # Protect overlay FAT entries from path-based replacement.
                raise ValueError("replacement unexpectedly resolved to an overlay FAT entry")  # Refuse a structurally unsafe target.
            fixed_layout: dict[str, tuple[Path, int]] = validate_fixed_layout(root, original_header, payload_base)  # Confirm every fixed ROM component fits the header geometry.
            capacity: int = cartridge_capacity(original_header)  # Preserve the retail cartridge capacity unless the used data no longer fits.
            output_path.parent.mkdir(parents=True, exist_ok=True)  # Create the ignored local output directory when necessary.
            with output_path.open("w+b") as destination:  # Build into a newly truncated output file so the source extraction remains untouched.
                fill_file(destination, capacity, ERASE_BYTE)  # Initialize the complete retail cartridge capacity with erased bytes.
                for source_path, offset in fixed_layout.values():  # Restore every fixed executable, overlay, filename-table, and banner region.
                    copy_file_at(destination, source_path, offset)  # Copy the fixed component verbatim to its original absolute offset.
                new_fat, new_used_size = rebuild_filesystem(destination, payload, fat, nitro_ids, payload_base, replacements)  # Repack NitroFS and calculate updated FAT ranges.
                if new_used_size > capacity:  # Refuse mods that overflow the original retail cartridge capacity.
                    raise ValueError(f"rebuilt used ROM size {new_used_size} exceeds cartridge capacity {capacity}")  # Report how far the build exceeded the available address space.
                header: bytearray = bytearray(original_header)  # Create a mutable copy while preserving all untouched header metadata.
                write_u32(header, USED_ROM_SIZE_FIELD, new_used_size)  # Update the used-ROM byte count after any size-changing replacement.
                struct.pack_into("<H", header, HEADER_CRC_FIELD, crc16_nintendo(header[:HEADER_CRC_END]))  # Recalculate the header checksum after changing the used-ROM size.
                destination.seek(0)  # Return to the start of the cartridge image.
                destination.write(header)  # Write the updated complete header region.
                destination.seek(read_u32(header, FAT_OFFSET_FIELD))  # Seek to the original fixed FAT-table location.
                destination.write(encode_fat(new_fat))  # Replace only FAT offsets/sizes while keeping the table at its original address.
                if args.trim:  # Optionally remove erased cartridge padding after the last used byte.
                    destination.truncate(new_used_size)  # Produce a smaller emulator-friendly ROM without changing any internal addresses.
    print(f"fat_data base: 0x{payload_base:08x} ({signature_score} known signatures, {bounds_score} mapped files in bounds)")  # Report the validated filesystem alignment used for rebuilding.
    print(f"NitroFS begins at FAT file ID 0x{first_nitro_id:x}; preserved {first_nitro_id} overlay FAT entries")  # Report the overlay/NitroFS boundary.
    for file_id, source_path in sorted(replacements.items()):  # Report each intentional filesystem substitution without exposing game contents.
        print(f"replaced FAT file ID 0x{file_id:x} ({file_ids[file_id]}) with {source_path}")  # Identify the exact modded NitroFS target.
    print(f"used ROM size: {new_used_size} bytes")  # Report the internally declared used portion of the rebuilt image.
    print(f"output ROM: {output_path} ({output_path.stat().st_size} bytes)")  # Report the final image path and physical file size.
    return 0  # Signal a successful deterministic ROM rebuild.


if __name__ == "__main__":  # Run the CLI entry point only when the script is executed directly.
    raise SystemExit(main())  # Propagate success or validation failure to the shell.
