#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

PNG_SIGNATURE: Final[bytes] = b"\x89PNG\r\n\x1a\n"
MAGIC_BY_KIND: Final[dict[str, bytes]] = {
    "NCGR": b"RGCN",
    "NCLR": b"RLCN",
    "NSCR": b"RCSN",
    "NCER": b"RECN",
    "NANR": b"RNAN",
}
BPP_BY_DEPTH: Final[dict[int, int]] = {3: 4, 4: 8}
OAM_SIZES: Final[dict[tuple[int, int], tuple[int, int]]] = {
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}
DEFAULT_MAX_PIXELS: Final[int] = 4_194_304


class NitroFormatError(ValueError):
    pass


@dataclass(frozen=True)
class NitroHeader:
    magic: bytes
    endian: str
    byte_order: int
    version: int
    file_size: int
    header_size: int
    section_count: int


@dataclass(frozen=True)
class NitroSection:
    magic: bytes
    start: int
    size: int

    @property
    def end(self) -> int:
        return self.start + self.size


@dataclass(frozen=True)
class Ncgr:
    header: NitroHeader
    section: NitroSection
    depth: int
    bpp: int
    raw_height_chars: int
    raw_width_chars: int
    unknown_word: int
    tiled_flag: int
    tiled: bool
    data: bytes
    data_offset: int
    declared_width: int | None
    declared_height: int | None

    @property
    def tile_bytes(self) -> int:
        return 32 if self.bpp == 4 else 64

    @property
    def tile_count(self) -> int:
        return len(self.data) // self.tile_bytes


@dataclass(frozen=True)
class Nclr:
    header: NitroHeader
    section: NitroSection
    depth: int
    bpp: int
    extended_palette: int
    palettes: tuple[tuple[tuple[int, int, int, int], ...], ...]
    raw_color_count: int
    declared_data_size: int

    @property
    def palette_count(self) -> int:
        return len(self.palettes)

    @property
    def colors_per_palette(self) -> int:
        return 16 if self.depth == 3 else 256


@dataclass(frozen=True)
class Nscr:
    header: NitroHeader
    section: NitroSection
    width: int
    height: int
    entries: tuple[int, ...]

    @property
    def max_tile_index(self) -> int:
        return max((entry & 0x03FF for entry in self.entries), default=0)

    @property
    def max_palette_index(self) -> int:
        return max(((entry >> 12) & 0xF for entry in self.entries), default=0)


@dataclass(frozen=True)
class Oam:
    index: int
    x: int
    y: int
    width: int
    height: int
    affine: bool
    disabled: bool
    mode: int
    depth: int
    flip_x: bool
    flip_y: bool
    tile_offset: int
    priority: int
    palette_index: int


@dataclass(frozen=True)
class NcerBank:
    index: int
    oams: tuple[Oam, ...]
    data_offset: int
    data_size: int


@dataclass(frozen=True)
class Ncer:
    header: NitroHeader
    section: NitroSection
    bank_type: int
    block_size: int
    banks: tuple[NcerBank, ...]

    @property
    def oam_count(self) -> int:
        return sum(len(bank.oams) for bank in self.banks)


@dataclass(frozen=True)
class Nanr:
    header: NitroHeader
    sections: tuple[str, ...]


@dataclass
class Image:
    width: int
    height: int
    pixels: list[tuple[int, int, int, int]]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image dimensions must be positive")
        if len(self.pixels) != self.width * self.height:
            raise ValueError("pixel count does not match image dimensions")


def _unpack(data: bytes, offset: int, fmt: str, endian: str = "<") -> tuple[Any, ...]:
    size = struct.calcsize(endian + fmt)
    if offset < 0 or offset + size > len(data):
        raise NitroFormatError(f"read outside file at 0x{offset:X} for {size} bytes")
    return struct.unpack_from(endian + fmt, data, offset)


def _u16(data: bytes, offset: int, endian: str = "<") -> int:
    return int(_unpack(data, offset, "H", endian)[0])


def _u32(data: bytes, offset: int, endian: str = "<") -> int:
    return int(_unpack(data, offset, "I", endian)[0])


def parse_nitro_header(data: bytes, expected_magic: bytes | None = None) -> NitroHeader:
    if len(data) < 16:
        raise NitroFormatError("Nitro file is shorter than the 16-byte common header")
    magic = data[:4]
    if expected_magic is not None and magic != expected_magic:
        raise NitroFormatError(f"unexpected file magic {magic!r}; expected {expected_magic!r}")

    le_byte_order = _u16(data, 4, "<")
    if le_byte_order == 0xFEFF:
        endian = "<"
        byte_order = le_byte_order
    elif le_byte_order == 0xFFFE:
        endian = ">"
        byte_order = le_byte_order
    else:
        raise NitroFormatError(f"unsupported Nitro byte-order marker 0x{le_byte_order:04X}")

    version = _u16(data, 6, endian)
    file_size = _u32(data, 8, endian)
    header_size = _u16(data, 12, endian)
    section_count = _u16(data, 14, endian)
    if file_size < 16 or file_size > len(data):
        raise NitroFormatError(f"declared file size {file_size} is outside payload length {len(data)}")
    if header_size < 16 or header_size > file_size:
        raise NitroFormatError(f"invalid Nitro header size {header_size}")
    return NitroHeader(magic, endian, byte_order, version, file_size, header_size, section_count)


def parse_sections(data: bytes, header: NitroHeader) -> tuple[NitroSection, ...]:
    sections: list[NitroSection] = []
    offset = header.header_size
    for index in range(header.section_count):
        if offset + 8 > header.file_size:
            raise NitroFormatError(f"section {index} header extends beyond declared file size")
        magic = data[offset:offset + 4]
        size = _u32(data, offset + 4, header.endian)
        if size < 8:
            raise NitroFormatError(f"section {index} has invalid size {size}")
        if offset + size > header.file_size:
            raise NitroFormatError(f"section {index} extends beyond declared file size")
        sections.append(NitroSection(magic, offset, size))
        offset += size
    return tuple(sections)


def require_section(data: bytes, header: NitroHeader, magic: bytes) -> NitroSection:
    for section in parse_sections(data, header):
        if section.magic == magic:
            return section
    raise NitroFormatError(f"missing required section {magic!r}")


def parse_ncgr(data: bytes) -> Ncgr:
    header = parse_nitro_header(data, b"RGCN")
    section = require_section(data, header, b"RAHC")
    if section.size < 0x20:
        raise NitroFormatError("RAHC section is shorter than its fixed header")
    raw_height = _u16(data, section.start + 8, header.endian)
    raw_width = _u16(data, section.start + 10, header.endian)
    depth = _u32(data, section.start + 12, header.endian)
    if depth not in BPP_BY_DEPTH:
        raise NitroFormatError(f"unsupported NCGR color depth {depth}")
    unknown_word = _u32(data, section.start + 16, header.endian)
    tiled_flag = _u32(data, section.start + 20, header.endian)
    data_size = _u32(data, section.start + 24, header.endian)
    data_offset = _u32(data, section.start + 28, header.endian)
    data_start = section.start + 8 + data_offset
    data_end = data_start + data_size
    if data_start < section.start + 0x20 or data_end > section.end:
        raise NitroFormatError(
            f"NCGR graphics data range 0x{data_start:X}-0x{data_end:X} is outside RAHC section"
        )
    bpp = BPP_BY_DEPTH[depth]
    tile_bytes = 32 if bpp == 4 else 64
    if data_size % tile_bytes != 0:
        raise NitroFormatError(f"NCGR graphics data size {data_size} is not tile-aligned for {bpp}bpp")

    declared_width: int | None = None
    declared_height: int | None = None
    if raw_width != 0xFFFF and raw_height != 0xFFFF and raw_width > 0 and raw_height > 0:
        declared_width = raw_width * 8
        declared_height = raw_height * 8

    # Nitro tools use the low byte of this field to distinguish character-tiled
    # storage (zero) from linear storage (nonzero). Preserve the full field.
    tiled = (tiled_flag & 0xFF) == 0
    return Ncgr(
        header=header,
        section=section,
        depth=depth,
        bpp=bpp,
        raw_height_chars=raw_height,
        raw_width_chars=raw_width,
        unknown_word=unknown_word,
        tiled_flag=tiled_flag,
        tiled=tiled,
        data=data[data_start:data_end],
        data_offset=data_offset,
        declared_width=declared_width,
        declared_height=declared_height,
    )


def _bgr555_to_rgba(word: int) -> tuple[int, int, int, int]:
    r5 = word & 0x1F
    g5 = (word >> 5) & 0x1F
    b5 = (word >> 10) & 0x1F
    return (
        (r5 * 255 + 15) // 31,
        (g5 * 255 + 15) // 31,
        (b5 * 255 + 15) // 31,
        255,
    )


def parse_nclr(data: bytes) -> Nclr:
    header = parse_nitro_header(data, b"RLCN")
    section = require_section(data, header, b"TTLP")
    if section.size < 0x18:
        raise NitroFormatError("TTLP section is shorter than its fixed header")
    depth = _u16(data, section.start + 8, header.endian)
    if depth not in BPP_BY_DEPTH:
        raise NitroFormatError(f"unsupported NCLR color depth {depth}")
    extended_palette = _u32(data, section.start + 12, header.endian)
    declared_data_size = _u32(data, section.start + 16, header.endian)
    data_offset = _u32(data, section.start + 20, header.endian)
    data_start = section.start + 8 + data_offset
    if data_start < section.start + 0x18 or data_start > section.end:
        raise NitroFormatError("NCLR palette data offset is outside TTLP section")

    available = section.end - data_start
    data_size = declared_data_size
    if data_size == 0 or data_size > available:
        # Some converters wrote the palette-compression size field incorrectly. The bounded
        # section and pointer still define the stored color words deterministically.
        data_size = available
    data_size -= data_size % 2
    if data_size <= 0:
        raise NitroFormatError("NCLR contains no palette color words")

    words = [_u16(data, data_start + offset, header.endian) for offset in range(0, data_size, 2)]
    colors = tuple(_bgr555_to_rgba(word) for word in words)
    base_count = 16 if depth == 3 else 256
    if len(colors) <= base_count:
        palettes = (colors,)
    else:
        palettes = tuple(colors[i:i + base_count] for i in range(0, len(colors), base_count))
    return Nclr(
        header=header,
        section=section,
        depth=depth,
        bpp=BPP_BY_DEPTH[depth],
        extended_palette=extended_palette,
        palettes=palettes,
        raw_color_count=len(colors),
        declared_data_size=declared_data_size,
    )


def parse_nscr(data: bytes) -> Nscr:
    header = parse_nitro_header(data, b"RCSN")
    section = require_section(data, header, b"NRCS")
    if section.size < 0x14:
        raise NitroFormatError("NRCS section is shorter than its fixed header")
    width = _u16(data, section.start + 8, header.endian)
    height = _u16(data, section.start + 10, header.endian)
    data_size = _u32(data, section.start + 16, header.endian)
    data_start = section.start + 0x14
    data_end = data_start + data_size
    if width <= 0 or height <= 0 or width % 8 or height % 8:
        raise NitroFormatError(f"NSCR dimensions {width}x{height} are not positive 8-pixel multiples")
    expected_entries = (width // 8) * (height // 8)
    if data_size != expected_entries * 2:
        raise NitroFormatError(
            f"NSCR data size {data_size} does not match {expected_entries} map entries for {width}x{height}"
        )
    if data_end > section.end:
        raise NitroFormatError("NSCR map data extends beyond NRCS section")
    entries = tuple(_u16(data, data_start + i * 2, header.endian) for i in range(expected_entries))
    return Nscr(header, section, width, height, entries)


def _decode_oam(attr0: int, attr1: int, attr2: int, index: int) -> Oam:
    y = attr0 & 0xFF
    if y >= 0x80:
        y -= 0x100
    affine = bool((attr0 >> 8) & 1)
    disabled = not affine and bool((attr0 >> 9) & 1)
    mode = (attr0 >> 10) & 3
    depth = 4 if ((attr0 >> 13) & 1) == 0 else 8
    shape = (attr0 >> 14) & 3
    x = attr1 & 0x1FF
    if x >= 0x100:
        x -= 0x200
    flip_x = not affine and bool((attr1 >> 12) & 1)
    flip_y = not affine and bool((attr1 >> 13) & 1)
    size_code = (attr1 >> 14) & 3
    dimensions = OAM_SIZES.get((shape, size_code), (0, 0))
    return Oam(
        index=index,
        x=x,
        y=y,
        width=dimensions[0],
        height=dimensions[1],
        affine=affine,
        disabled=disabled,
        mode=mode,
        depth=depth,
        flip_x=flip_x,
        flip_y=flip_y,
        tile_offset=attr2 & 0x03FF,
        priority=(attr2 >> 10) & 3,
        palette_index=(attr2 >> 12) & 0xF,
    )


def parse_ncer(data: bytes) -> Ncer:
    header = parse_nitro_header(data, b"RECN")
    section = require_section(data, header, b"KBEC")
    if section.size < 0x20:
        raise NitroFormatError("KBEC section is shorter than its fixed header")
    bank_count = _u16(data, section.start + 8, header.endian)
    bank_type = _u16(data, section.start + 10, header.endian)
    bank_data_offset = _u32(data, section.start + 12, header.endian)
    block_size = _u32(data, section.start + 16, header.endian) & 0xFF
    partition_data_offset = _u32(data, section.start + 20, header.endian)
    if bank_type not in (0, 1):
        raise NitroFormatError(f"unsupported NCER bank type {bank_type}")
    if block_size > 4:
        raise NitroFormatError(f"unsupported NCER OBJ mapping block shift {block_size}")

    record_size = 8 if bank_type == 0 else 16
    bank_table_start = section.start + 8 + bank_data_offset
    if bank_table_start < section.start + 0x20 or bank_table_start + bank_count * record_size > section.end:
        raise NitroFormatError("NCER bank table is outside KBEC section")

    partition_offsets = [0] * bank_count
    partition_sizes = [0] * bank_count
    if partition_data_offset:
        partition_header = section.start + 8 + partition_data_offset
        if partition_header + 8 > section.end:
            raise NitroFormatError("NCER partition header is outside KBEC section")
        first_partition_offset = _u32(data, partition_header + 4, header.endian)
        table = partition_header + first_partition_offset
        if table + bank_count * 8 > section.end:
            raise NitroFormatError("NCER partition table is outside KBEC section")
        for index in range(bank_count):
            partition_offsets[index] = _u32(data, table + index * 8, header.endian)
            partition_sizes[index] = _u32(data, table + index * 8 + 4, header.endian)

    oam_base = bank_table_start + bank_count * record_size
    banks: list[NcerBank] = []
    for bank_index in range(bank_count):
        record = bank_table_start + bank_index * record_size
        oam_count = _u16(data, record, header.endian)
        cell_offset = _u32(data, record + 4, header.endian)
        oam_start = oam_base + cell_offset
        oam_end = oam_start + oam_count * 6
        if oam_start < oam_base or oam_end > section.end:
            raise NitroFormatError(f"NCER bank {bank_index} OAM data is outside KBEC section")
        oams = []
        for oam_index in range(oam_count):
            offset = oam_start + oam_index * 6
            oams.append(
                _decode_oam(
                    _u16(data, offset, header.endian),
                    _u16(data, offset + 2, header.endian),
                    _u16(data, offset + 4, header.endian),
                    oam_index,
                )
            )
        banks.append(
            NcerBank(
                index=bank_index,
                oams=tuple(oams),
                data_offset=partition_offsets[bank_index],
                data_size=partition_sizes[bank_index],
            )
        )
    return Ncer(header, section, bank_type, block_size, tuple(banks))


def parse_nanr(data: bytes) -> Nanr:
    header = parse_nitro_header(data, b"RNAN")
    sections = tuple(section.magic.decode("ascii", "replace") for section in parse_sections(data, header))
    return Nanr(header, sections)


def unpack_indices(data: bytes, bpp: int, pixel_count: int) -> list[int]:
    result: list[int] = []
    if bpp == 4:
        for value in data:
            result.append(value & 0xF)
            if len(result) >= pixel_count:
                break
            result.append((value >> 4) & 0xF)
            if len(result) >= pixel_count:
                break
    elif bpp == 8:
        result.extend(data[:pixel_count])
    else:
        raise NitroFormatError(f"unsupported indexed bit depth {bpp}")
    if len(result) < pixel_count:
        raise NitroFormatError(f"graphics data contains {len(result)} pixels; expected {pixel_count}")
    return result


def decode_pixels(data: bytes, bpp: int, width: int, height: int, tiled: bool) -> list[int]:
    if width <= 0 or height <= 0:
        raise NitroFormatError("decode dimensions must be positive")
    pixel_count = width * height
    if not tiled:
        return unpack_indices(data, bpp, pixel_count)
    if width % 8 or height % 8:
        raise NitroFormatError("tiled graphics dimensions must be multiples of 8")
    tile_bytes = 32 if bpp == 4 else 64
    tiles_x = width // 8
    tiles_y = height // 8
    required = tiles_x * tiles_y * tile_bytes
    if len(data) < required:
        raise NitroFormatError(f"tiled graphics requires {required} bytes but only {len(data)} are available")
    pixels = [0] * pixel_count
    for tile_y in range(tiles_y):
        for tile_x in range(tiles_x):
            tile_index = tile_y * tiles_x + tile_x
            tile = unpack_indices(
                data[tile_index * tile_bytes:(tile_index + 1) * tile_bytes], bpp, 64
            )
            for y in range(8):
                dst = (tile_y * 8 + y) * width + tile_x * 8
                src = y * 8
                pixels[dst:dst + 8] = tile[src:src + 8]
    return pixels


def diagnostic_ncgr_dimensions(ncgr: Ncgr) -> tuple[int, int, str]:
    if ncgr.declared_width and ncgr.declared_height:
        required = ncgr.declared_width * ncgr.declared_height * ncgr.bpp // 8
        if required <= len(ncgr.data):
            return ncgr.declared_width, ncgr.declared_height, "declared_ncgr_dimensions"
    tile_count = max(1, ncgr.tile_count)
    columns = min(16, tile_count)
    rows = math.ceil(tile_count / columns)
    return columns * 8, rows * 8, "diagnostic_16_tile_grid"


def image_from_indices(
    indices: Sequence[int],
    width: int,
    height: int,
    palette: Sequence[tuple[int, int, int, int]] | None = None,
    *,
    transparent_zero: bool = False,
) -> Image:
    if len(indices) != width * height:
        raise NitroFormatError("index buffer does not match image dimensions")
    pixels: list[tuple[int, int, int, int]] = []
    if palette is None:
        max_index = max(indices, default=0)
        scale = 255 / max(1, max_index)
        for index in indices:
            value = int(round(index * scale))
            pixels.append((value, value, value, 255))
    else:
        for index in indices:
            if index >= len(palette):
                raise NitroFormatError(f"palette index {index} exceeds {len(palette)} available colors")
            color = palette[index]
            if transparent_zero and index == 0:
                pixels.append((color[0], color[1], color[2], 0))
            else:
                pixels.append(color)
    return Image(width, height, pixels)


def ncgr_index_image(ncgr: Ncgr) -> tuple[Image, str]:
    width, height, basis = diagnostic_ncgr_dimensions(ncgr)
    if basis.startswith("diagnostic"):
        indices = decode_pixels(ncgr.data, ncgr.bpp, width, height, True)
    else:
        indices = decode_pixels(ncgr.data, ncgr.bpp, width, height, ncgr.tiled)
    return image_from_indices(indices, width, height), basis


def _palette_for_sheet(nclr: Nclr, ncgr: Ncgr, palette_index: int = 0) -> Sequence[tuple[int, int, int, int]]:
    if ncgr.depth != nclr.depth:
        raise NitroFormatError(f"NCGR depth {ncgr.depth} and NCLR depth {nclr.depth} are incompatible")
    if palette_index >= nclr.palette_count:
        raise NitroFormatError(f"palette bank {palette_index} is not present")
    palette = nclr.palettes[palette_index]
    required = 16 if ncgr.bpp == 4 else 256
    if len(palette) < required:
        raise NitroFormatError(f"palette has {len(palette)} colors; {required} are required")
    return palette


def colorized_ncgr_image(ncgr: Ncgr, nclr: Nclr) -> tuple[Image, str]:
    palette = _palette_for_sheet(nclr, ncgr, 0)
    width, height, basis = diagnostic_ncgr_dimensions(ncgr)
    tiled = True if basis.startswith("diagnostic") else ncgr.tiled
    indices = decode_pixels(ncgr.data, ncgr.bpp, width, height, tiled)
    return image_from_indices(indices, width, height, palette), basis


def render_nscr(nscr: Nscr, ncgr: Ncgr, nclr: Nclr) -> Image:
    if ncgr.depth != nclr.depth:
        raise NitroFormatError("NSCR candidate has incompatible NCGR/NCLR depths")
    if nscr.max_tile_index >= ncgr.tile_count:
        raise NitroFormatError(
            f"NSCR references tile {nscr.max_tile_index}, but NCGR contains {ncgr.tile_count} tiles"
        )
    if ncgr.bpp == 4 and nscr.max_palette_index >= nclr.palette_count:
        raise NitroFormatError(
            f"NSCR references palette bank {nscr.max_palette_index}, but NCLR contains {nclr.palette_count} banks"
        )
    if ncgr.bpp == 8 and (not nclr.palettes or len(nclr.palettes[0]) < 256):
        raise NitroFormatError("8bpp NSCR candidate does not have a 256-color palette")

    tiles_x = nscr.width // 8
    pixels = [(0, 0, 0, 255)] * (nscr.width * nscr.height)
    tile_bytes = ncgr.tile_bytes
    for map_index, entry in enumerate(nscr.entries):
        tile_number = entry & 0x03FF
        flip_x = bool(entry & (1 << 10))
        flip_y = bool(entry & (1 << 11))
        palette_bank = (entry >> 12) & 0xF
        tile_data = ncgr.data[tile_number * tile_bytes:(tile_number + 1) * tile_bytes]
        tile_indices = unpack_indices(tile_data, ncgr.bpp, 64)
        palette = nclr.palettes[palette_bank] if ncgr.bpp == 4 else nclr.palettes[0]
        map_x = (map_index % tiles_x) * 8
        map_y = (map_index // tiles_x) * 8
        for y in range(8):
            src_y = 7 - y if flip_y else y
            for x in range(8):
                src_x = 7 - x if flip_x else x
                color_index = tile_indices[src_y * 8 + src_x]
                if color_index >= len(palette):
                    raise NitroFormatError("NSCR tile uses a palette index not present in NCLR")
                pixels[(map_y + y) * nscr.width + map_x + x] = palette[color_index]
    return Image(nscr.width, nscr.height, pixels)


def _flip_image(image: Image, flip_x: bool, flip_y: bool) -> Image:
    if not flip_x and not flip_y:
        return image
    pixels = [(0, 0, 0, 0)] * len(image.pixels)
    for y in range(image.height):
        src_y = image.height - 1 - y if flip_y else y
        for x in range(image.width):
            src_x = image.width - 1 - x if flip_x else x
            pixels[y * image.width + x] = image.pixels[src_y * image.width + src_x]
    return Image(image.width, image.height, pixels)


def _alpha_over(dst: tuple[int, int, int, int], src: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    sa = src[3]
    if sa == 255:
        return src
    if sa == 0:
        return dst
    da = dst[3]
    out_a = sa + (da * (255 - sa) + 127) // 255
    if out_a == 0:
        return (0, 0, 0, 0)
    out = []
    for channel in range(3):
        numerator = src[channel] * sa * 255 + dst[channel] * da * (255 - sa)
        out.append((numerator + out_a * 127) // (out_a * 255))
    return (out[0], out[1], out[2], out_a)


def render_ncer_bank(bank: NcerBank, ncer: Ncer, ncgr: Ncgr, nclr: Nclr, max_pixels: int) -> Image:
    drawable = [
        oam for oam in bank.oams
        if not oam.disabled and not oam.affine and oam.width > 0 and oam.height > 0 and oam.mode != 2
    ]
    if not drawable:
        raise NitroFormatError("NCER bank has no directly renderable non-affine OAM entries")
    if any(oam.depth != ncgr.bpp for oam in drawable):
        raise NitroFormatError("NCER OAM bit depth does not match candidate NCGR")
    if ncgr.depth != nclr.depth:
        raise NitroFormatError("NCER candidate has incompatible NCGR/NCLR depths")

    min_x = min(oam.x for oam in drawable)
    min_y = min(oam.y for oam in drawable)
    max_x = max(oam.x + oam.width for oam in drawable)
    max_y = max(oam.y + oam.height for oam in drawable)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0 or width * height > max_pixels:
        raise NitroFormatError(f"NCER bank canvas {width}x{height} exceeds preview limits")
    canvas = Image(width, height, [(0, 0, 0, 0)] * (width * height))

    for oam in sorted(drawable, key=lambda item: (item.priority, item.index), reverse=True):
        start_byte = bank.data_offset + ((oam.tile_offset << ncer.block_size) * 0x20)
        byte_count = oam.width * oam.height * ncgr.bpp // 8
        end_byte = start_byte + byte_count
        if start_byte < 0 or end_byte > len(ncgr.data):
            raise NitroFormatError(
                f"NCER OAM {oam.index} graphics range {start_byte}:{end_byte} exceeds NCGR data"
            )
        indices = decode_pixels(ncgr.data[start_byte:end_byte], ncgr.bpp, oam.width, oam.height, ncgr.tiled)
        palette_bank = oam.palette_index if ncgr.bpp == 4 else 0
        palette = _palette_for_sheet(nclr, ncgr, palette_bank)
        sprite = image_from_indices(indices, oam.width, oam.height, palette, transparent_zero=True)
        sprite = _flip_image(sprite, oam.flip_x, oam.flip_y)
        dst_x = oam.x - min_x
        dst_y = oam.y - min_y
        for y in range(sprite.height):
            for x in range(sprite.width):
                dst_index = (dst_y + y) * width + dst_x + x
                src = sprite.pixels[y * sprite.width + x]
                canvas.pixels[dst_index] = _alpha_over(canvas.pixels[dst_index], src)
    return canvas


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def png_bytes(image: Image) -> bytes:
    raw = bytearray()
    stride = image.width * 4
    packed = bytearray()
    for pixel in image.pixels:
        packed.extend(pixel)
    for y in range(image.height):
        raw.append(0)
        raw.extend(packed[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def write_png(path: Path, image: Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(image))


def palette_preview(nclr: Nclr, swatch: int = 10) -> Image:
    columns = 16
    rows = sum(max(1, math.ceil(len(palette) / columns)) for palette in nclr.palettes)
    width = columns * swatch
    height = rows * swatch
    pixels = [(0, 0, 0, 255)] * (width * height)
    row_base = 0
    for palette in nclr.palettes:
        palette_rows = max(1, math.ceil(len(palette) / columns))
        for index, color in enumerate(palette):
            cell_x = index % columns
            cell_y = row_base + index // columns
            for y in range(cell_y * swatch, (cell_y + 1) * swatch):
                start = y * width + cell_x * swatch
                pixels[start:start + swatch] = [color] * swatch
        row_base += palette_rows
    return Image(width, height, pixels)


def safe_stem(resource: dict[str, str]) -> str:
    return Path(resource["payload_path"]).stem


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing required catalogue: {path}")
    with path.open("r", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def inspect_resource(kind: str, data: bytes) -> tuple[object, dict[str, Any]]:
    if kind == "NCGR":
        value = parse_ncgr(data)
        return value, {
            "width": value.declared_width or "", "height": value.declared_height or "",
            "bpp": value.bpp, "tile_count": value.tile_count, "palette_count": "",
            "colors_per_palette": "", "bank_count": "", "oam_count": "",
            "sections": value.header.section_count,
        }
    if kind == "NCLR":
        value = parse_nclr(data)
        return value, {
            "width": "", "height": "", "bpp": value.bpp, "tile_count": "",
            "palette_count": value.palette_count, "colors_per_palette": value.colors_per_palette,
            "bank_count": "", "oam_count": "", "sections": value.header.section_count,
        }
    if kind == "NSCR":
        value = parse_nscr(data)
        return value, {
            "width": value.width, "height": value.height, "bpp": "", "tile_count": "",
            "palette_count": "", "colors_per_palette": "", "bank_count": "", "oam_count": "",
            "sections": value.header.section_count,
        }
    if kind == "NCER":
        value = parse_ncer(data)
        return value, {
            "width": "", "height": "", "bpp": "", "tile_count": "", "palette_count": "",
            "colors_per_palette": "", "bank_count": len(value.banks), "oam_count": value.oam_count,
            "sections": value.header.section_count,
        }
    if kind == "NANR":
        value = parse_nanr(data)
        return value, {
            "width": "", "height": "", "bpp": "", "tile_count": "", "palette_count": "",
            "colors_per_palette": "", "bank_count": "", "oam_count": "",
            "sections": " ".join(value.sections),
        }
    raise NitroFormatError(f"unsupported graphics resource kind {kind}")


def render_catalog(catalog_dir: Path, output_dir: Path, *, metadata_only: bool, max_pixels: int) -> dict[str, Any]:
    catalog_dir = catalog_dir.resolve()
    output_dir = output_dir.resolve()
    resources = read_csv(catalog_dir / "resources.csv")
    runs = read_csv(catalog_dir / "adjacent_runs.csv")
    resource_by_path = {row["logical_path"]: row for row in resources}
    if len(resource_by_path) != len(resources):
        raise ValueError("graphics resources.csv contains duplicate logical paths")

    output_dir.mkdir(parents=True, exist_ok=True)
    parsed: dict[str, object] = {}
    inspection_rows: list[dict[str, Any]] = []
    atomic_preview_count = 0
    parse_errors = 0

    for resource in sorted(resources, key=lambda row: row["logical_path"]):
        kind = resource["kind"]
        expected_magic = MAGIC_BY_KIND.get(kind)
        payload_path = catalog_dir / resource["payload_path"]
        row: dict[str, Any] = {
            "logical_path": resource["logical_path"], "kind": kind, "parse_status": "ok", "error": "",
            "width": "", "height": "", "bpp": "", "tile_count": "", "palette_count": "",
            "colors_per_palette": "", "bank_count": "", "oam_count": "", "sections": "",
            "atomic_preview_path": "", "presentation_basis": "",
        }
        try:
            if not payload_path.is_file():
                raise FileNotFoundError(f"missing graphics payload {payload_path}")
            data = payload_path.read_bytes()
            if expected_magic is None or not data.startswith(expected_magic):
                raise NitroFormatError(f"{kind} payload has unexpected magic")
            parsed_value, details = inspect_resource(kind, data)
            parsed[resource["logical_path"]] = parsed_value
            row.update(details)
            if not metadata_only and kind == "NCLR":
                destination = output_dir / "atomic" / "palettes" / f"{safe_stem(resource)}.png"
                write_png(destination, palette_preview(parsed_value))  # type: ignore[arg-type]
                row["atomic_preview_path"] = str(destination.relative_to(output_dir))
                row["presentation_basis"] = "palette_swatch_grid"
                atomic_preview_count += 1
            elif not metadata_only and kind == "NCGR":
                image, basis = ncgr_index_image(parsed_value)  # type: ignore[arg-type]
                if image.width * image.height > max_pixels:
                    raise NitroFormatError("NCGR diagnostic preview exceeds max-pixels limit")
                destination = output_dir / "atomic" / "indices" / f"{safe_stem(resource)}.png"
                write_png(destination, image)
                row["atomic_preview_path"] = str(destination.relative_to(output_dir))
                row["presentation_basis"] = basis
                atomic_preview_count += 1
        except (OSError, ValueError) as error:
            row["parse_status"] = "error"
            row["error"] = str(error)
            parse_errors += 1
        inspection_rows.append(row)

    candidate_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    composite_counts: Counter[str] = Counter()

    for run in sorted(runs, key=lambda row: row["run_id"]):
        paths = run["resource_paths"].split()
        members = [resource_by_path[path] for path in paths if path in resource_by_path]
        by_kind: dict[str, list[dict[str, str]]] = defaultdict(list)
        for member in members:
            by_kind[member["kind"]].append(member)

        if len(by_kind["NCGR"]) != 1 or len(by_kind["NCLR"]) != 1:
            unresolved_rows.append({
                "run_id": run["run_id"], "preview_kind": "composite",
                "resource_paths": run["resource_paths"],
                "reason": "contiguous run does not contain exactly one NCGR and exactly one NCLR",
            })
            continue
        ncgr_res = by_kind["NCGR"][0]
        nclr_res = by_kind["NCLR"][0]
        ncgr = parsed.get(ncgr_res["logical_path"])
        nclr = parsed.get(nclr_res["logical_path"])
        if not isinstance(ncgr, Ncgr) or not isinstance(nclr, Nclr):
            unresolved_rows.append({
                "run_id": run["run_id"], "preview_kind": "composite",
                "resource_paths": run["resource_paths"], "reason": "NCGR or NCLR failed parsing",
            })
            continue

        structural_basis = "unique_ncgr_nclr_in_maximal_contiguous_graphics_run"
        try:
            image, _basis = colorized_ncgr_image(ncgr, nclr)
            if image.width * image.height > max_pixels:
                raise NitroFormatError("colorized NCGR preview exceeds max-pixels limit")
            preview_path = ""
            if not metadata_only:
                destination = output_dir / "candidates" / "sheets" / f"{run['run_id']}.png"
                write_png(destination, image)
                preview_path = str(destination.relative_to(output_dir))
            candidate_rows.append({
                "run_id": run["run_id"], "preview_kind": "NCGR+NCLR sheet",
                "ncgr_path": ncgr_res["logical_path"], "nclr_path": nclr_res["logical_path"],
                "layout_path": "", "bank_index": "", "preview_path": preview_path,
                "structural_basis": structural_basis, "semantic_pairing_proven": False,
            })
            composite_counts["sheet"] += 1
        except ValueError as error:
            unresolved_rows.append({
                "run_id": run["run_id"], "preview_kind": "NCGR+NCLR sheet",
                "resource_paths": f"{ncgr_res['logical_path']} {nclr_res['logical_path']}",
                "reason": str(error),
            })

        if len(by_kind["NSCR"]) == 1:
            nscr_res = by_kind["NSCR"][0]
            nscr = parsed.get(nscr_res["logical_path"])
            if isinstance(nscr, Nscr):
                try:
                    image = render_nscr(nscr, ncgr, nclr)
                    if image.width * image.height > max_pixels:
                        raise NitroFormatError("NSCR preview exceeds max-pixels limit")
                    preview_path = ""
                    if not metadata_only:
                        destination = output_dir / "candidates" / "backgrounds" / f"{run['run_id']}.png"
                        write_png(destination, image)
                        preview_path = str(destination.relative_to(output_dir))
                    candidate_rows.append({
                        "run_id": run["run_id"], "preview_kind": "NSCR background",
                        "ncgr_path": ncgr_res["logical_path"], "nclr_path": nclr_res["logical_path"],
                        "layout_path": nscr_res["logical_path"], "bank_index": "",
                        "preview_path": preview_path, "structural_basis": structural_basis,
                        "semantic_pairing_proven": False,
                    })
                    composite_counts["background"] += 1
                except ValueError as error:
                    unresolved_rows.append({
                        "run_id": run["run_id"], "preview_kind": "NSCR background",
                        "resource_paths": f"{ncgr_res['logical_path']} {nclr_res['logical_path']} {nscr_res['logical_path']}",
                        "reason": str(error),
                    })
            else:
                unresolved_rows.append({
                    "run_id": run["run_id"], "preview_kind": "NSCR background",
                    "resource_paths": nscr_res["logical_path"], "reason": "NSCR failed parsing",
                })
        elif len(by_kind["NSCR"]) > 1:
            unresolved_rows.append({
                "run_id": run["run_id"], "preview_kind": "NSCR background",
                "resource_paths": " ".join(item["logical_path"] for item in by_kind["NSCR"]),
                "reason": "multiple NSCR resources in run; no layout was selected",
            })

        if len(by_kind["NCER"]) == 1:
            ncer_res = by_kind["NCER"][0]
            ncer = parsed.get(ncer_res["logical_path"])
            if isinstance(ncer, Ncer):
                for bank in ncer.banks:
                    try:
                        image = render_ncer_bank(bank, ncer, ncgr, nclr, max_pixels)
                        preview_path = ""
                        if not metadata_only:
                            destination = output_dir / "candidates" / "cells" / f"{run['run_id']}__bank_{bank.index:04d}.png"
                            write_png(destination, image)
                            preview_path = str(destination.relative_to(output_dir))
                        candidate_rows.append({
                            "run_id": run["run_id"], "preview_kind": "NCER cell bank",
                            "ncgr_path": ncgr_res["logical_path"], "nclr_path": nclr_res["logical_path"],
                            "layout_path": ncer_res["logical_path"], "bank_index": bank.index,
                            "preview_path": preview_path, "structural_basis": structural_basis,
                            "semantic_pairing_proven": False,
                        })
                        composite_counts["cell_bank"] += 1
                    except ValueError as error:
                        unresolved_rows.append({
                            "run_id": run["run_id"], "preview_kind": f"NCER cell bank {bank.index}",
                            "resource_paths": f"{ncgr_res['logical_path']} {nclr_res['logical_path']} {ncer_res['logical_path']}",
                            "reason": str(error),
                        })
            else:
                unresolved_rows.append({
                    "run_id": run["run_id"], "preview_kind": "NCER cell bank",
                    "resource_paths": ncer_res["logical_path"], "reason": "NCER failed parsing",
                })
        elif len(by_kind["NCER"]) > 1:
            unresolved_rows.append({
                "run_id": run["run_id"], "preview_kind": "NCER cell bank",
                "resource_paths": " ".join(item["logical_path"] for item in by_kind["NCER"]),
                "reason": "multiple NCER resources in run; no cell layout was selected",
            })

    inspection_fields = [
        "logical_path", "kind", "parse_status", "error", "width", "height", "bpp", "tile_count",
        "palette_count", "colors_per_palette", "bank_count", "oam_count", "sections",
        "atomic_preview_path", "presentation_basis",
    ]
    candidate_fields = [
        "run_id", "preview_kind", "ncgr_path", "nclr_path", "layout_path", "bank_index",
        "preview_path", "structural_basis", "semantic_pairing_proven",
    ]
    unresolved_fields = ["run_id", "preview_kind", "resource_paths", "reason"]
    write_csv(output_dir / "resource_inspection.csv", inspection_rows, inspection_fields)
    write_csv(output_dir / "candidate_previews.csv", candidate_rows, candidate_fields)
    write_csv(output_dir / "unresolved.csv", unresolved_rows, unresolved_fields)

    parsed_counts = Counter(row["kind"] for row in inspection_rows if row["parse_status"] == "ok")
    summary: dict[str, Any] = {
        "resources_inspected": len(resources),
        "resources_parsed": len(resources) - parse_errors,
        "resource_parse_errors": parse_errors,
        "parsed_formats": dict(sorted(parsed_counts.items())),
        "atomic_previews_written": atomic_preview_count,
        "candidate_previews": dict(sorted(composite_counts.items())),
        "candidate_rows": len(candidate_rows),
        "unresolved_rows": len(unresolved_rows),
        "metadata_only": metadata_only,
        "semantic_pairings_claimed": 0,
        "pairing_policy": "combined previews require exactly one NCGR and one NCLR in the same maximal contiguous graphics run; no semantic relationship is claimed",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"graphics resources inspected: {summary['resources_inspected']}")
    print(f"graphics resources parsed: {summary['resources_parsed']}")
    print(f"graphics parse errors: {summary['resource_parse_errors']}")
    print(f"atomic previews written: {summary['atomic_previews_written']}")
    print(f"candidate preview rows: {summary['candidate_rows']}")
    print(f"unresolved preview rows: {summary['unresolved_rows']}")
    print("semantic pairings guessed: 0")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Render deterministic previews for catalogued Nintendo DS Nitro 2D graphics.")
    parser.add_argument("catalog_dir", type=Path, help="graphics_catalog directory produced by catalog_graphics_sets.py")
    parser.add_argument("output_dir", type=Path, help="directory for PNG previews and preview metadata")
    parser.add_argument("--metadata-only", action="store_true", help="parse and classify resources without writing PNG files")
    parser.add_argument("--max-pixels", type=int, default=DEFAULT_MAX_PIXELS, help="maximum pixels allowed in any generated preview")
    args = parser.parse_args()
    if args.max_pixels < 64:
        parser.error("--max-pixels must be at least 64")
    render_catalog(args.catalog_dir, args.output_dir, metadata_only=args.metadata_only, max_pixels=args.max_pixels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
