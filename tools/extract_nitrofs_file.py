#!/usr/bin/env python3
from __future__ import annotations

import argparse  # Parse the requested NitroFS source and destination paths.
import mmap  # Search the large FAT payload without copying it into Python memory.
import struct  # Decode Nintendo DS FAT start/end offsets as little-endian integers.
from pathlib import Path  # Represent repository and output paths safely.
from typing import Final  # Mark format constants that do not change at runtime.

FAT_ENTRY_SIZE: Final[int] = 8  # Each Nintendo DS FAT entry contains a 32-bit start and end offset.
KNOWN_MAGICS: Final[dict[str, bytes]] = {".acf": b"acf\x00", ".sdat": b"SDAT"}  # Use known Guardian Signs container signatures to infer the FAT payload base.
MAX_MAGIC_MATCHES: Final[int] = 256  # Bound signature candidate generation even if a byte sequence occurs frequently.


def parse_fat(path: Path) -> list[tuple[int, int]]:  # Decode every FAT entry from the extracted FAT table.
    data: bytes = path.read_bytes()  # Read the small FAT table into memory once.
    if len(data) % FAT_ENTRY_SIZE != 0:  # Reject truncated or malformed FAT tables.
        raise ValueError(f"FAT size is not divisible by {FAT_ENTRY_SIZE}: {path}")
    return [struct.unpack_from("<II", data, offset) for offset in range(0, len(data), FAT_ENTRY_SIZE)]  # Preserve the original file-ID order.


def parse_file_ids(path: Path, entry_count: int) -> dict[int, str]:  # Read NDSFactory's hexadecimal file-ID mapping while ignoring directory pseudo-IDs.
    result: dict[int, str] = {}  # Map numeric FAT IDs to NitroFS paths.
    for raw_line in path.read_text(encoding="utf-8").splitlines():  # Process one mapping record at a time.
        if ":::" not in raw_line:  # Ignore malformed or empty records.
            continue
        raw_id, nitro_path = raw_line.split(":::", 1)  # Separate the hexadecimal ID from its path.
        try:  # Distinguish real hexadecimal file IDs from non-file records.
            file_id: int = int(raw_id, 16)  # NDSFactory writes file IDs in hexadecimal.
        except ValueError:  # Ignore records that do not contain a hexadecimal ID.
            continue
        if 0 <= file_id < entry_count and nitro_path:  # Keep only IDs that can index the FAT table.
            result[file_id] = nitro_path  # Preserve the named NitroFS path for extraction.
    return result  # Return the usable file-ID map.


def expected_magic(nitro_path: str) -> bytes | None:  # Return a known leading signature for selected container types.
    return KNOWN_MAGICS.get(Path(nitro_path).suffix.lower())  # Match signatures by normalized file extension.


def candidate_bases(payload: mmap.mmap, fat: list[tuple[int, int]], file_ids: dict[int, str]) -> set[int]:  # Derive possible absolute-ROM bases from known container signatures.
    candidates: set[int] = set()  # Deduplicate candidate base addresses from multiple matching files.
    for file_id, nitro_path in file_ids.items():  # Inspect every named file that has a useful signature.
        magic: bytes | None = expected_magic(nitro_path)  # Look up the expected file header.
        if magic is None:  # Skip formats whose first bytes are not known here.
            continue
        start, _ = fat[file_id]  # Read the file's absolute start address from the Nintendo DS FAT.
        search_from: int = 0  # Begin signature scanning at the start of the FAT payload.
        matches: int = 0  # Bound the number of candidates generated for this signature.
        while matches < MAX_MAGIC_MATCHES:  # Search repeated signatures without allowing pathological unbounded work.
            position: int = payload.find(magic, search_from)  # Locate the next matching header in the raw FAT payload.
            if position < 0:  # Stop when no further signature is present.
                break
            base: int = start - position  # Convert the payload-relative match into a possible absolute-ROM base.
            if base >= 0:  # Ignore impossible negative ROM base addresses.
                candidates.add(base)  # Retain the inferred base for cross-validation.
            search_from = position + 1  # Continue after this match so overlapping candidates remain discoverable.
            matches += 1  # Record one processed signature occurrence.
    return candidates  # Return all bases suggested by known files.


def score_base(base: int, payload: mmap.mmap, fat: list[tuple[int, int]], file_ids: dict[int, str]) -> tuple[int, int]:  # Score a base using file bounds and known file signatures.
    payload_size: int = len(payload)  # Cache the mapped payload length for repeated bounds checks.
    signature_score: int = 0  # Count known file headers that line up under this base.
    bounds_score: int = 0  # Count named files whose FAT ranges fit inside the payload.
    for file_id, nitro_path in file_ids.items():  # Validate every mapped file against the candidate base.
        start, end = fat[file_id]  # Read the absolute ROM range for this file.
        relative_start: int = start - base  # Translate the file start into the FAT payload.
        relative_end: int = end - base  # Translate the file end into the FAT payload.
        if relative_start < 0 or relative_end < relative_start or relative_end > payload_size:  # Reject ranges outside the payload.
            continue
        bounds_score += 1  # Reward candidates that cover more mapped files.
        magic: bytes | None = expected_magic(nitro_path)  # Check a known header when this file format has one.
        if magic is not None and payload[relative_start : relative_start + len(magic)] == magic:  # Validate the expected file header exactly.
            signature_score += 1  # Reward correctly aligned known formats strongly.
    return signature_score, bounds_score  # Prefer header agreement first and broad FAT coverage second.


def infer_payload_base(payload: mmap.mmap, fat: list[tuple[int, int]], file_ids: dict[int, str]) -> tuple[int, int, int]:  # Select the most strongly validated FAT payload base.
    candidates: set[int] = candidate_bases(payload, fat, file_ids)  # Generate candidates from known ACF and SDAT headers.
    valid_starts: list[int] = [start for start, end in fat if end >= start and start != 0xFFFFFFFF]  # Collect plausible FAT start addresses for a conservative fallback.
    if valid_starts:  # Include the common case where fat_data.bin begins at the first FAT file.
        candidates.add(min(valid_starts))  # Test the minimum FAT start as an additional candidate.
    if not candidates:  # Refuse to guess if neither signatures nor FAT entries can suggest a base.
        raise ValueError("could not derive any FAT payload base candidates")

    ranked: list[tuple[int, int, int]] = []  # Store signature score, bounds score, and base together for deterministic ranking.
    for base in candidates:  # Validate every candidate against all named FAT entries.
        signature_score, bounds_score = score_base(base, payload, fat, file_ids)  # Measure structural agreement for this base.
        ranked.append((signature_score, bounds_score, base))  # Retain the complete ranking tuple.
    ranked.sort(reverse=True)  # Prefer more matching signatures, then more in-bounds files, then the larger base only as a final deterministic tie-break.
    signature_score, bounds_score, base = ranked[0]  # Select the strongest candidate.
    if signature_score == 0:  # Do not silently extract data when no known file header validates the inferred alignment.
        raise ValueError("could not validate FAT payload alignment with any known ACF or SDAT signature")
    return base, signature_score, bounds_score  # Report both the selected base and its validation strength.


def find_file_id(file_ids: dict[int, str], requested_path: str) -> int:  # Resolve one NitroFS path to its numeric FAT entry.
    normalized: str = requested_path.replace("\\", "/").lstrip("/")  # Normalize user input to the mapping's slash convention.
    matches: list[int] = [file_id for file_id, nitro_path in file_ids.items() if nitro_path.replace("\\", "/").lstrip("/") == normalized]  # Find exact path matches only.
    if len(matches) != 1:  # Require an unambiguous mapping before reading binary data.
        raise ValueError(f"expected one file ID for {requested_path!r}, found {len(matches)}")
    return matches[0]  # Return the unique FAT index.


def extract_file(payload: mmap.mmap, fat: list[tuple[int, int]], file_id: int, base: int, output_path: Path) -> int:  # Copy one correctly aligned FAT range to a standalone file.
    start, end = fat[file_id]  # Read the absolute Nintendo DS ROM offsets for the requested file.
    relative_start: int = start - base  # Translate the start into fat_data.bin coordinates.
    relative_end: int = end - base  # Translate the end into fat_data.bin coordinates.
    if relative_start < 0 or relative_end < relative_start or relative_end > len(payload):  # Protect against corrupt FAT ranges or an incorrect base.
        raise ValueError(f"FAT entry {file_id:#x} falls outside fat_data.bin under base {base:#x}")
    output_path.parent.mkdir(parents=True, exist_ok=True)  # Create the ignored local output directory when necessary.
    output_path.write_bytes(payload[relative_start:relative_end])  # Write exactly the byte range described by the FAT entry.
    return relative_end - relative_start  # Return the extracted size for verification output.


def parse_args() -> argparse.Namespace:  # Define the command-line interface for extracting one named NitroFS file.
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Extract one correctly aligned NitroFS file from NDSFactory FAT data.")  # Create the CLI parser.
    parser.add_argument("fat_data", type=Path)  # Accept the raw FAT payload blob.
    parser.add_argument("fat", type=Path)  # Accept the Nintendo DS FAT table.
    parser.add_argument("file_ids", type=Path)  # Accept NDSFactory's file-ID/path mapping.
    parser.add_argument("nitro_path")  # Accept the exact NitroFS path to extract.
    parser.add_argument("output", type=Path)  # Accept the destination file path.
    return parser.parse_args()  # Parse and return user arguments.


def main() -> int:  # Infer FAT alignment, extract the requested file, and validate its known signature when available.
    args: argparse.Namespace = parse_args()  # Read command-line arguments once.
    fat: list[tuple[int, int]] = parse_fat(args.fat)  # Decode the FAT table.
    file_ids: dict[int, str] = parse_file_ids(args.file_ids, len(fat))  # Decode file IDs using the FAT entry count as a validity bound.
    file_id: int = find_file_id(file_ids, args.nitro_path)  # Resolve the requested path before mapping the large payload.

    with args.fat_data.open("rb") as source:  # Keep the FAT payload file open while it is memory-mapped.
        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as payload:  # Map the large payload read-only for efficient signature scanning and slicing.
            base, signature_score, bounds_score = infer_payload_base(payload, fat, file_ids)  # Find a validated absolute-ROM base for fat_data.bin.
            extracted_size: int = extract_file(payload, fat, file_id, base, args.output)  # Extract exactly the requested FAT entry.

    magic: bytes | None = expected_magic(args.nitro_path)  # Determine whether this output has a known signature to verify.
    if magic is not None and args.output.read_bytes()[: len(magic)] != magic:  # Reject output that does not match its expected container header.
        args.output.unlink(missing_ok=True)  # Remove the invalid generated file rather than leaving misleading data behind.
        raise ValueError(f"extracted {args.nitro_path!r} does not begin with expected magic {magic!r}")

    print(f"fat_data base: 0x{base:08x} ({signature_score} known signatures, {bounds_score} mapped files in bounds)")  # Report how strongly the alignment was validated.
    print(f"extracted file id 0x{file_id:x}: {args.nitro_path} -> {args.output} ({extracted_size} bytes)")  # Report the exact extracted resource and size.
    return 0  # Signal successful extraction.


if __name__ == "__main__":  # Run the command-line entry point only when executed directly.
    raise SystemExit(main())  # Propagate the command's success or failure code to the shell.
