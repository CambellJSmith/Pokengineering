#!/usr/bin/env python3
from __future__ import annotations

import render_guardian_graphics as guardian
import render_guardian_graphics_safe as safe


def dummy_ncgr(*, depth: int, bpp: int, tiled: bool, data: bytes, width: int, height: int):
    header = guardian.core.NitroHeader(b"RGCN", "<", 0xFEFF, 0x0100, len(data) + 48, 16, 1)
    section = guardian.core.NitroSection(b"RAHC", 16, len(data) + 32)
    return guardian.core.Ncgr(
        header=header,
        section=section,
        depth=depth,
        bpp=bpp,
        raw_height_chars=height // 8,
        raw_width_chars=width // 8,
        unknown_word=0,
        tiled_flag=0 if tiled else 1,
        tiled=tiled,
        data=data,
        data_offset=24,
        declared_width=width,
        declared_height=height,
    )


def main() -> int:
    safe.install_safe_extents()
    guardian.install_compatibility()

    # 20 physical 4bpp tiles with a header claiming 32 tiles. The old fallback
    # produced a 16x2 tile sheet and then failed because 12 tiles did not exist.
    tiled = dummy_ncgr(
        depth=3,
        bpp=4,
        tiled=True,
        data=bytes(20 * 32),
        width=128,
        height=16,
    )
    width, height, basis = safe.exact_diagnostic_dimensions(tiled)
    assert (width // 8) * (height // 8) == 20
    assert basis.startswith("physical_tile_extent")
    image, _ = guardian.ncgr_atomic_image(tiled)
    assert image.width * image.height == 20 * 64

    # Linear indexed payload: 11,776 physical pixels against a 12,288-pixel
    # declaration. The fallback must consume exactly 11,776 pixels.
    linear = dummy_ncgr(
        depth=3,
        bpp=4,
        tiled=False,
        data=bytes(11776 // 2),
        width=96,
        height=128,
    )
    width, height, basis = safe.exact_diagnostic_dimensions(linear)
    assert width * height == 11776
    assert basis.startswith("physical_linear_extent")
    image, _ = guardian.ncgr_atomic_image(linear)
    assert image.width * image.height == 11776

    # Prime tile counts must remain exact too; never round up to a padded row.
    prime = dummy_ncgr(
        depth=3,
        bpp=4,
        tiled=True,
        data=bytes(17 * 32),
        width=128,
        height=16,
    )
    width, height, _ = safe.exact_diagnostic_dimensions(prime)
    assert (width // 8) * (height // 8) == 17
    guardian.ncgr_atomic_image(prime)

    print("Guardian Signs physical preview extent test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
