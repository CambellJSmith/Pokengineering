#!/usr/bin/env python3
from __future__ import annotations

import math

import render_guardian_graphics as guardian


def _nearest_divisor(total: int, preferred: int, limit: int | None = None) -> int:
    if total <= 0:
        raise guardian.core.NitroFormatError("physical graphics extent is empty")
    upper = total if limit is None else min(total, limit)
    divisors = [value for value in range(1, upper + 1) if total % value == 0]
    if not divisors:
        return 1
    return min(divisors, key=lambda value: (abs(value - preferred), -value))


def exact_diagnostic_dimensions(ncgr: guardian.core.Ncgr) -> tuple[int, int, str]:
    """Choose preview dimensions that consume exactly the stored NCGR payload.

    Guardian Signs contains many NCGRs whose declared dimensions describe a padded
    allocation rather than the physical bytes stored in the archive. Diagnostic
    previews must never invent that padding: tiled resources use an exact factor
    pair of the stored tile count, while linear resources use an exact factor pair
    of the stored pixel count.
    """
    if ncgr.tiled:
        tile_bytes = guardian.bytes_per_tile(ncgr.depth)
        tile_count = len(ncgr.data) // tile_bytes
        if tile_count <= 0:
            raise guardian.core.NitroFormatError("NCGR contains no complete tiles")

        preferred_tiles = 0
        if ncgr.declared_width and ncgr.declared_width % 8 == 0:
            preferred_tiles = ncgr.declared_width // 8
        if preferred_tiles <= 0:
            preferred_tiles = min(16, max(1, round(math.sqrt(tile_count))))

        # Prefer the declared/diagnostic width when it divides the physical tile
        # count. Otherwise choose the closest exact divisor. A 32-tile width cap
        # keeps diagnostic sheets practical while still allowing common DS widths.
        columns = _nearest_divisor(tile_count, preferred_tiles, limit=32)
        if columns == 1 and tile_count > 32:
            # Prime-ish counts have no useful narrow divisor. A single exact row is
            # better than fabricating missing tiles with ceil().
            columns = tile_count
        rows = tile_count // columns
        basis = (
            "physical_tile_extent_declared_width"
            if ncgr.declared_width and columns * 8 == ncgr.declared_width
            else "physical_tile_extent_exact_factor"
        )
        return columns * 8, rows * 8, basis

    if ncgr.depth == 2:
        pixel_count = len(ncgr.data) * 4
    elif ncgr.bpp == 4:
        pixel_count = len(ncgr.data) * 2
    elif ncgr.bpp == 8:
        pixel_count = len(ncgr.data)
    elif ncgr.bpp == 16:
        pixel_count = len(ncgr.data) // 2
    else:
        raise guardian.core.NitroFormatError(
            f"unsupported physical extent for {ncgr.bpp}bpp NCGR"
        )
    if pixel_count <= 0:
        raise guardian.core.NitroFormatError("NCGR contains no complete pixels")

    preferred = ncgr.declared_width or min(256, max(1, round(math.sqrt(pixel_count))))
    width = _nearest_divisor(pixel_count, preferred, limit=512)
    if width == 1 and pixel_count > 512:
        width = pixel_count
    height = pixel_count // width
    basis = (
        "physical_linear_extent_declared_width"
        if ncgr.declared_width and width == ncgr.declared_width
        else "physical_linear_extent_exact_factor"
    )
    return width, height, basis


def install_safe_extents() -> None:
    guardian.diagnostic_dimensions = exact_diagnostic_dimensions


def main() -> int:
    install_safe_extents()
    return guardian.main()


if __name__ == "__main__":
    raise SystemExit(main())
