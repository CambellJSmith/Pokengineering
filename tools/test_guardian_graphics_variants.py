#!/usr/bin/env python3
from __future__ import annotations

import struct

import render_guardian_graphics as guardian
import render_nitro_graphics as core


def nitro(magic: bytes, section: bytes, declared_file_size: int | None = None) -> bytes:
    actual_size = 16 + len(section)
    size = actual_size if declared_file_size is None else declared_file_size
    return magic + struct.pack("<HHIHH", 0xFEFF, 0x0100, size, 16, 1) + section


def ncgr(depth: int, width_tiles: int, height_tiles: int, pixels: bytes, *, declared_data_size: int | None = None) -> bytes:
    data_size = len(pixels) if declared_data_size is None else declared_data_size
    section_size = 0x20 + data_size
    section = (
        b"RAHC"
        + struct.pack("<IHHIHHIII", section_size, height_tiles, width_tiles, depth, 0, 0, 1, data_size, 0x18)
        + pixels
    )
    # When declared data is larger than physical data, keep the stale section/file declarations.
    declared_file = 16 + section_size
    return nitro(b"RGCN", section, declared_file_size=declared_file)


def nclr(depth: int, words: list[int], *, stale_file_size: bool = False) -> bytes:
    colors = b"".join(struct.pack("<H", word) for word in words)
    section_size = 0x18 + len(colors)
    section = b"TTLP" + struct.pack("<IHHIII", section_size, depth, 0, 1, len(colors), 0x10) + colors
    declared = 16 + section_size - 4 if stale_file_size else None
    return nitro(b"RLCN", section, declared)


def nscr_one_byte() -> bytes:
    map_data = bytes([0])
    section = b"NRCS" + struct.pack("<IHHII", 0x15, 8, 8, 0, 1) + map_data
    return nitro(b"RCSN", section)


def main() -> None:
    guardian.install_compatibility()

    stale = guardian.parse_nclr(nclr(3, [0, 0x7FFF], stale_file_size=True))
    assert stale.depth == 3 and stale.raw_color_count == 2

    a3i5_pixels = bytes([(7 << 5) | (index % 4) for index in range(64)])
    a3i5 = guardian.parse_ncgr(ncgr(1, 1, 1, a3i5_pixels))
    a3i5_pal = guardian.parse_nclr(nclr(1, [0x001F, 0x03E0, 0x7C00, 0x7FFF]))
    image, _ = guardian.colorized_ncgr(a3i5, a3i5_pal)
    assert (image.width, image.height) == (8, 8)
    assert all(pixel[3] == 255 for pixel in image.pixels)

    packed_2bpp = bytes([0b11100100] * 16)
    pltt4 = guardian.parse_ncgr(ncgr(2, 1, 1, packed_2bpp))
    pltt4_pal = guardian.parse_nclr(nclr(2, [0x001F, 0x03E0, 0x7C00, 0x7FFF]))
    image, _ = guardian.colorized_ncgr(pltt4, pltt4_pal)
    assert (image.width, image.height) == (8, 8)
    assert set(guardian.decode_indices(pltt4, 8, 8)) == {0, 1, 2, 3}

    a5i3_pixels = bytes([(31 << 3) | (index % 2) for index in range(64)])
    a5i3 = guardian.parse_ncgr(ncgr(6, 1, 1, a5i3_pixels))
    a5i3_pal = guardian.parse_nclr(nclr(6, [0x001F, 0x7C00]))
    image, _ = guardian.colorized_ncgr(a5i3, a5i3_pal)
    assert (image.width, image.height) == (8, 8)
    assert all(pixel[3] == 255 for pixel in image.pixels)

    direct_words = [0x8000 | (index & 0x1F) for index in range(64)]
    direct_pixels = b"".join(struct.pack("<H", word) for word in direct_words)
    direct = guardian.parse_ncgr(ncgr(7, 1, 2, direct_pixels, declared_data_size=256))
    assert direct.declared_width == 8
    assert direct.declared_height == 8
    image, basis = guardian.ncgr_atomic_image(direct)
    assert (image.width, image.height) == (8, 8)
    assert basis == "declared_or_physical_ncgr_dimensions"

    screen = guardian.parse_nscr(nscr_one_byte())
    assert screen.entries == (0,)

    # Confirm the core dataclass properties were updated for nonstandard depths.
    assert pltt4.tile_bytes == 16
    assert pltt4.tile_count == 1
    assert a3i5_pal.colors_per_palette == 32
    assert pltt4_pal.colors_per_palette == 4
    assert a5i3_pal.colors_per_palette == 8

    print("Guardian Signs Nitro texture variant test passed")


if __name__ == "__main__":
    main()
