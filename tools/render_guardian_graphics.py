#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import render_nitro_graphics as core

# Guardian Signs uses the numeric Nintendo DS texture-format values in the
# NCGR/NCLR depth field for several resources, not only PLTT16/PLTT256.
# 0 and 5 are deliberately absent: NONE and COMP4x4 need different storage.
DEPTH_BPP = {1: 8, 2: 2, 3: 4, 4: 8, 6: 8, 7: 16}
PALETTE_CAPACITY = {1: 32, 2: 4, 3: 16, 4: 256, 6: 8}
DEPTH_NAME = {
    1: "A3I5",
    2: "PLTT4",
    3: "PLTT16",
    4: "PLTT256",
    6: "A5I3",
    7: "DIRECT",
}


def parse_header(data: bytes, expected_magic: bytes | None = None) -> core.NitroHeader:
    if len(data) < 16:
        raise core.NitroFormatError("Nitro file is shorter than the 16-byte common header")
    magic = data[:4]
    if expected_magic is not None and magic != expected_magic:
        raise core.NitroFormatError(f"unexpected file magic {magic!r}; expected {expected_magic!r}")
    marker = core._u16(data, 4, "<")
    if marker == 0xFEFF:
        endian = "<"
    elif marker == 0xFFFE:
        endian = ">"
    else:
        raise core.NitroFormatError(f"unsupported Nitro byte-order marker 0x{marker:04X}")
    version = core._u16(data, 6, endian)
    file_size = core._u32(data, 8, endian)
    header_size = core._u16(data, 12, endian)
    section_count = core._u16(data, 14, endian)
    if file_size < 16:
        raise core.NitroFormatError(f"invalid declared Nitro file size {file_size}")
    if header_size < 16 or header_size > len(data):
        raise core.NitroFormatError(f"invalid Nitro header size {header_size}")
    return core.NitroHeader(magic, endian, marker, version, file_size, header_size, section_count)


def parse_sections(data: bytes, header: core.NitroHeader) -> tuple[core.NitroSection, ...]:
    sections: list[core.NitroSection] = []
    offset = header.header_size
    for index in range(header.section_count):
        if offset + 8 > len(data):
            raise core.NitroFormatError(f"section {index} header extends beyond physical payload")
        magic = data[offset:offset + 4]
        declared_size = core._u32(data, offset + 4, header.endian)
        if declared_size < 8:
            raise core.NitroFormatError(f"section {index} has invalid size {declared_size}")
        remaining = len(data) - offset
        if declared_size > remaining:
            if index != header.section_count - 1:
                raise core.NitroFormatError(
                    f"non-final section {index} extends beyond physical payload"
                )
            # Several Guardian Signs resources carry padded/stale size declarations.
            # The physical end of the final section is unambiguous because there is no
            # following section to locate; clamp only that final section.
            size = remaining
        else:
            size = declared_size
        sections.append(core.NitroSection(magic, offset, size))
        offset += size
    return tuple(sections)


def require_section(data: bytes, header: core.NitroHeader, magic: bytes) -> core.NitroSection:
    for section in parse_sections(data, header):
        if section.magic == magic:
            return section
    raise core.NitroFormatError(f"missing required section {magic!r}")


def bytes_per_tile(depth: int) -> int:
    bpp = DEPTH_BPP[depth]
    return 64 * bpp // 8


def parse_ncgr(data: bytes) -> core.Ncgr:
    header = parse_header(data, b"RGCN")
    section = require_section(data, header, b"RAHC")
    if section.size < 0x20:
        raise core.NitroFormatError("RAHC section is shorter than its fixed header")
    raw_height = core._u16(data, section.start + 8, header.endian)
    raw_width = core._u16(data, section.start + 10, header.endian)
    depth = core._u32(data, section.start + 12, header.endian)
    if depth not in DEPTH_BPP:
        raise core.NitroFormatError(f"unsupported NCGR texture format {depth}")
    unknown_word = core._u32(data, section.start + 16, header.endian)
    tiled_flag = core._u32(data, section.start + 20, header.endian)
    declared_data_size = core._u32(data, section.start + 24, header.endian)
    data_offset = core._u32(data, section.start + 28, header.endian)
    data_start = section.start + 8 + data_offset
    if data_start < section.start + 0x20 or data_start > section.end:
        raise core.NitroFormatError("NCGR graphics data offset is outside RAHC section")
    available = section.end - data_start
    data_size = min(declared_data_size, available)
    bpp = DEPTH_BPP[depth]

    declared_width: int | None = None
    declared_height: int | None = None
    if raw_width != 0xFFFF and raw_height != 0xFFFF and raw_width > 0 and raw_height > 0:
        declared_width = raw_width * 8
        declared_height = raw_height * 8
        row_bits = declared_width * bpp
        if row_bits % 8 == 0:
            row_bytes = row_bits // 8
            if row_bytes and data_size % row_bytes == 0:
                physical_height = data_size // row_bytes
                if 0 < physical_height < declared_height:
                    declared_height = physical_height

    # Preserve only complete pixels. For tile-major storage, preserve complete tiles.
    if (tiled_flag & 0xFF) == 0:
        unit = bytes_per_tile(depth)
    else:
        unit = max(1, bpp // 8) if bpp >= 8 else 1
    data_size -= data_size % unit
    if data_size <= 0:
        raise core.NitroFormatError("NCGR contains no complete graphics data")

    return core.Ncgr(
        header=header,
        section=section,
        depth=depth,
        bpp=bpp,
        raw_height_chars=raw_height,
        raw_width_chars=raw_width,
        unknown_word=unknown_word,
        tiled_flag=tiled_flag,
        tiled=(tiled_flag & 0xFF) == 0,
        data=data[data_start:data_start + data_size],
        data_offset=data_offset,
        declared_width=declared_width,
        declared_height=declared_height,
    )


def parse_nclr(data: bytes) -> core.Nclr:
    header = parse_header(data, b"RLCN")
    section = require_section(data, header, b"TTLP")
    if section.size < 0x18:
        raise core.NitroFormatError("TTLP section is shorter than its fixed header")
    depth = core._u16(data, section.start + 8, header.endian)
    if depth not in PALETTE_CAPACITY:
        raise core.NitroFormatError(f"unsupported NCLR texture format {depth}")
    extended_palette = core._u32(data, section.start + 12, header.endian)
    declared_data_size = core._u32(data, section.start + 16, header.endian)
    data_offset = core._u32(data, section.start + 20, header.endian)
    data_start = section.start + 8 + data_offset
    if data_start < section.start + 0x18 or data_start > section.end:
        raise core.NitroFormatError("NCLR palette data offset is outside TTLP section")
    available = section.end - data_start
    data_size = min(declared_data_size or available, available)
    data_size -= data_size % 2
    if data_size <= 0:
        raise core.NitroFormatError("NCLR contains no palette color words")
    colors = tuple(
        core._bgr555_to_rgba(core._u16(data, data_start + offset, header.endian))
        for offset in range(0, data_size, 2)
    )
    capacity = PALETTE_CAPACITY[depth]
    if len(colors) <= capacity:
        palettes = (colors,)
    else:
        palettes = tuple(colors[i:i + capacity] for i in range(0, len(colors), capacity))
    return core.Nclr(
        header=header,
        section=section,
        depth=depth,
        bpp=DEPTH_BPP[depth],
        extended_palette=extended_palette,
        palettes=palettes,
        raw_color_count=len(colors),
        declared_data_size=declared_data_size,
    )


def parse_nscr(data: bytes) -> core.Nscr:
    header = parse_header(data, b"RCSN")
    section = require_section(data, header, b"NRCS")
    if section.size < 0x14:
        raise core.NitroFormatError("NRCS section is shorter than its fixed header")
    width = core._u16(data, section.start + 8, header.endian)
    height = core._u16(data, section.start + 10, header.endian)
    data_size = core._u32(data, section.start + 16, header.endian)
    data_start = section.start + 0x14
    if width <= 0 or height <= 0 or width % 8 or height % 8:
        raise core.NitroFormatError(f"NSCR dimensions {width}x{height} are not positive 8-pixel multiples")
    expected_entries = (width // 8) * (height // 8)
    if data_start + data_size > section.end:
        raise core.NitroFormatError("NSCR map data extends beyond NRCS section")
    if data_size == expected_entries * 2:
        entries = tuple(
            core._u16(data, data_start + i * 2, header.endian) for i in range(expected_entries)
        )
    elif data_size == expected_entries:
        entries = tuple(data[data_start:data_start + data_size])
    else:
        raise core.NitroFormatError(
            f"NSCR data size {data_size} does not match {expected_entries} one- or two-byte map entries"
        )
    return core.Nscr(header, section, width, height, entries)


def unpack_2bpp(data: bytes, pixel_count: int) -> list[int]:
    out: list[int] = []
    for value in data:
        for shift in (0, 2, 4, 6):
            out.append((value >> shift) & 0x3)
            if len(out) >= pixel_count:
                return out
    if len(out) < pixel_count:
        raise core.NitroFormatError(f"graphics data contains {len(out)} pixels; expected {pixel_count}")
    return out


def decode_rgba_linear(ncgr: core.Ncgr, palette: Sequence[tuple[int, int, int, int]] | None = None) -> list[tuple[int, int, int, int]]:
    depth = ncgr.depth
    if depth == 7:
        pixels = []
        for offset in range(0, len(ncgr.data) - 1, 2):
            word = int.from_bytes(ncgr.data[offset:offset + 2], "little")
            color = core._bgr555_to_rgba(word & 0x7FFF)
            pixels.append((color[0], color[1], color[2], 255 if word & 0x8000 else 0))
        return pixels
    if depth in (1, 6):
        if palette is None:
            pixels = []
            for value in ncgr.data:
                if depth == 1:
                    index, alpha_raw, alpha_max = value & 0x1F, value >> 5, 7
                    intensity = round(index * 255 / 31)
                else:
                    index, alpha_raw, alpha_max = value & 0x07, value >> 3, 31
                    intensity = round(index * 255 / 7)
                alpha = round(alpha_raw * 255 / alpha_max)
                pixels.append((intensity, intensity, intensity, alpha))
            return pixels
        pixels = []
        for value in ncgr.data:
            if depth == 1:
                index, alpha_raw, alpha_max = value & 0x1F, value >> 5, 7
            else:
                index, alpha_raw, alpha_max = value & 0x07, value >> 3, 31
            if index >= len(palette):
                raise core.NitroFormatError(
                    f"{DEPTH_NAME[depth]} palette index {index} exceeds {len(palette)} stored colors"
                )
            base = palette[index]
            pixels.append((base[0], base[1], base[2], round(alpha_raw * 255 / alpha_max)))
        return pixels
    raise core.NitroFormatError(f"texture format {depth} is not an alpha/direct linear format")


def decode_indices(ncgr: core.Ncgr, width: int, height: int) -> list[int]:
    count = width * height
    if ncgr.depth == 2:
        if ncgr.tiled:
            if width % 8 or height % 8:
                raise core.NitroFormatError("tiled 2bpp dimensions must be multiples of 8")
            tile_bytes = 16
            tiles_x = width // 8
            tiles_y = height // 8
            required = tiles_x * tiles_y * tile_bytes
            if len(ncgr.data) < required:
                raise core.NitroFormatError("2bpp tiled graphics data is shorter than the requested image")
            result = [0] * count
            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    ti = ty * tiles_x + tx
                    tile = unpack_2bpp(ncgr.data[ti * tile_bytes:(ti + 1) * tile_bytes], 64)
                    for y in range(8):
                        dst = (ty * 8 + y) * width + tx * 8
                        result[dst:dst + 8] = tile[y * 8:y * 8 + 8]
            return result
        return unpack_2bpp(ncgr.data, count)
    return core.decode_pixels(ncgr.data, ncgr.bpp, width, height, ncgr.tiled)


def diagnostic_dimensions(ncgr: core.Ncgr) -> tuple[int, int, str]:
    if ncgr.declared_width and ncgr.declared_height:
        required = ncgr.declared_width * ncgr.declared_height * ncgr.bpp // 8
        if required <= len(ncgr.data):
            return ncgr.declared_width, ncgr.declared_height, "declared_or_physical_ncgr_dimensions"
    if ncgr.depth == 7 and len(ncgr.data) >= 2:
        pixels = len(ncgr.data) // 2
        width = ncgr.declared_width or min(256, pixels)
        if width and pixels % width == 0:
            return width, pixels // width, "physical_direct_color_extent"
    tile_bytes = bytes_per_tile(ncgr.depth)
    tile_count = max(1, len(ncgr.data) // tile_bytes)
    columns = min(16, tile_count)
    return columns * 8, math.ceil(tile_count / columns) * 8, "diagnostic_16_tile_grid"


def ncgr_atomic_image(ncgr: core.Ncgr) -> tuple[core.Image, str]:
    width, height, basis = diagnostic_dimensions(ncgr)
    if ncgr.depth in (1, 6, 7) and not ncgr.tiled:
        rgba = decode_rgba_linear(ncgr)
        needed = width * height
        if len(rgba) < needed:
            raise core.NitroFormatError("linear alpha/direct graphics are shorter than preview dimensions")
        return core.Image(width, height, rgba[:needed]), basis
    indices = decode_indices(ncgr, width, height)
    return core.image_from_indices(indices, width, height), basis


def palette_for(nclr: core.Nclr, ncgr: core.Ncgr, palette_index: int = 0) -> Sequence[tuple[int, int, int, int]]:
    if ncgr.depth != nclr.depth:
        raise core.NitroFormatError(
            f"NCGR texture format {ncgr.depth} and NCLR texture format {nclr.depth} are incompatible"
        )
    if palette_index >= len(nclr.palettes):
        raise core.NitroFormatError(f"palette bank {palette_index} is not present")
    palette = nclr.palettes[palette_index]
    if not palette:
        raise core.NitroFormatError("palette bank is empty")
    return palette


def colorized_ncgr(ncgr: core.Ncgr, nclr: core.Nclr) -> tuple[core.Image, str]:
    width, height, basis = diagnostic_dimensions(ncgr)
    palette = palette_for(nclr, ncgr, 0)
    if ncgr.depth in (1, 6) and not ncgr.tiled:
        rgba = decode_rgba_linear(ncgr, palette)
        needed = width * height
        if len(rgba) < needed:
            raise core.NitroFormatError("alpha-indexed graphics are shorter than preview dimensions")
        return core.Image(width, height, rgba[:needed]), basis
    if ncgr.depth == 7:
        rgba = decode_rgba_linear(ncgr)
        needed = width * height
        return core.Image(width, height, rgba[:needed]), basis
    indices = decode_indices(ncgr, width, height)
    max_index = max(indices, default=0)
    if max_index >= len(palette):
        raise core.NitroFormatError(
            f"graphics palette index {max_index} exceeds {len(palette)} stored colors"
        )
    return core.image_from_indices(indices, width, height, palette), basis


def render_nscr(nscr: core.Nscr, ncgr: core.Ncgr, nclr: core.Nclr) -> core.Image:
    if ncgr.depth not in (2, 3, 4):
        raise core.NitroFormatError(
            f"NSCR rendering for texture format {DEPTH_NAME.get(ncgr.depth, ncgr.depth)} is not established"
        )
    if ncgr.depth != nclr.depth:
        raise core.NitroFormatError("NSCR candidate has incompatible NCGR/NCLR texture formats")
    tile_bytes = bytes_per_tile(ncgr.depth)
    tile_count = len(ncgr.data) // tile_bytes
    if nscr.max_tile_index >= tile_count:
        raise core.NitroFormatError(
            f"NSCR references tile {nscr.max_tile_index}, but NCGR contains {tile_count} tiles"
        )
    tiles_x = nscr.width // 8
    pixels = [(0, 0, 0, 255)] * (nscr.width * nscr.height)
    for map_index, entry in enumerate(nscr.entries):
        tile_number = entry & 0x03FF
        flip_x = bool(entry & (1 << 10))
        flip_y = bool(entry & (1 << 11))
        palette_bank = (entry >> 12) & 0xF
        tile_data = ncgr.data[tile_number * tile_bytes:(tile_number + 1) * tile_bytes]
        if ncgr.depth == 2:
            tile_indices = unpack_2bpp(tile_data, 64)
        else:
            tile_indices = core.unpack_indices(tile_data, ncgr.bpp, 64)
        palette = palette_for(nclr, ncgr, palette_bank if ncgr.depth in (2, 3) else 0)
        max_index = max(tile_indices, default=0)
        if max_index >= len(palette):
            raise core.NitroFormatError(
                f"NSCR tile palette index {max_index} exceeds {len(palette)} stored colors"
            )
        map_x = (map_index % tiles_x) * 8
        map_y = (map_index // tiles_x) * 8
        for y in range(8):
            src_y = 7 - y if flip_y else y
            for x in range(8):
                src_x = 7 - x if flip_x else x
                color_index = tile_indices[src_y * 8 + src_x]
                pixels[(map_y + y) * nscr.width + map_x + x] = palette[color_index]
    return core.Image(nscr.width, nscr.height, pixels)


def install_compatibility() -> None:
    core.BPP_BY_DEPTH.clear()
    core.BPP_BY_DEPTH.update(DEPTH_BPP)
    core.parse_nitro_header = parse_header
    core.parse_sections = parse_sections
    core.require_section = require_section
    core.parse_ncgr = parse_ncgr
    core.parse_nclr = parse_nclr
    core.parse_nscr = parse_nscr
    core.ncgr_index_image = ncgr_atomic_image
    core.colorized_ncgr_image = colorized_ncgr
    core.render_nscr = render_nscr
    core.Ncgr.tile_bytes = property(lambda self: bytes_per_tile(self.depth))
    core.Ncgr.tile_count = property(lambda self: len(self.data) // bytes_per_tile(self.depth))
    core.Nclr.colors_per_palette = property(lambda self: PALETTE_CAPACITY.get(self.depth, len(self.palettes[0]) if self.palettes else 0))


def read_resources(catalog_dir: Path) -> list[dict[str, str]]:
    with (catalog_dir / "resources.csv").open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def scan_anomalies(catalog_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for resource in read_resources(catalog_dir):
        path = catalog_dir / resource["payload_path"]
        data = path.read_bytes()
        if len(data) < 16:
            continue
        marker = int.from_bytes(data[4:6], "little")
        endian = "little" if marker == 0xFEFF else "big"
        declared_file = int.from_bytes(data[8:12], endian)
        header_size = int.from_bytes(data[12:14], endian)
        if declared_file != len(data):
            rows.append({
                "logical_path": resource["logical_path"], "kind": resource["kind"],
                "anomaly": "declared_file_size_mismatch", "declared": declared_file,
                "physical": len(data), "detail": "physical payload bounds used",
            })
        if header_size + 8 <= len(data):
            section_size = int.from_bytes(data[header_size + 4:header_size + 8], endian)
            physical_section = len(data) - header_size
            if section_size != physical_section:
                rows.append({
                    "logical_path": resource["logical_path"], "kind": resource["kind"],
                    "anomaly": "declared_section_size_mismatch", "declared": section_size,
                    "physical": physical_section, "detail": "final physical section extent used when necessary",
                })
        if resource["kind"] in ("NCGR", "NCLR") and len(data) >= header_size + 16:
            depth_offset = header_size + 12 if resource["kind"] == "NCGR" else header_size + 8
            width = 4 if resource["kind"] == "NCGR" else 2
            depth = int.from_bytes(data[depth_offset:depth_offset + width], endian)
            if depth in DEPTH_NAME and depth not in (3, 4):
                rows.append({
                    "logical_path": resource["logical_path"], "kind": resource["kind"],
                    "anomaly": "extended_texture_format", "declared": depth,
                    "physical": "", "detail": DEPTH_NAME[depth],
                })
        if resource["kind"] == "NSCR" and len(data) >= header_size + 20:
            width_px = int.from_bytes(data[header_size + 8:header_size + 10], endian)
            height_px = int.from_bytes(data[header_size + 10:header_size + 12], endian)
            map_size = int.from_bytes(data[header_size + 16:header_size + 20], endian)
            entries = (width_px // 8) * (height_px // 8) if width_px and height_px else 0
            if entries and map_size == entries:
                rows.append({
                    "logical_path": resource["logical_path"], "kind": resource["kind"],
                    "anomaly": "one_byte_nscr_entries", "declared": map_size,
                    "physical": entries, "detail": "one byte per tile-map entry",
                })
    return rows


def write_anomalies(output_dir: Path, anomalies: list[dict[str, Any]]) -> None:
    fields = ["logical_path", "kind", "anomaly", "declared", "physical", "detail"]
    core.write_csv(output_dir / "format_anomalies.csv", anomalies, fields)
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["format_anomalies"] = len(anomalies)
    summary["format_anomalies_by_type"] = dict(sorted(Counter(row["anomaly"] for row in anomalies).items()))
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render Guardian Signs Nitro graphics, including observed DS texture-format extensions."
    )
    parser.add_argument("catalog_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--max-pixels", type=int, default=core.DEFAULT_MAX_PIXELS)
    args = parser.parse_args()
    if args.max_pixels < 64:
        parser.error("--max-pixels must be at least 64")
    install_compatibility()
    catalog_dir = args.catalog_dir.resolve()
    output_dir = args.output_dir.resolve()
    anomalies = scan_anomalies(catalog_dir)
    summary = core.render_catalog(
        catalog_dir, output_dir, metadata_only=args.metadata_only, max_pixels=args.max_pixels
    )
    write_anomalies(output_dir, anomalies)
    print(f"recorded format anomalies: {len(anomalies)}")
    print(f"Guardian Signs resources parsed: {summary['resources_parsed']}/{summary['resources_inspected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
