#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import render_guardian_graphics as guardian

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class SpriteEditError(ValueError):
    pass


@dataclass(frozen=True)
class PieceSpec:
    index: int
    start_byte: int
    byte_count: int
    width: int
    height: int
    palette_bank: int
    oam_indices: tuple[int, ...]

    @property
    def end_byte(self) -> int:
        return self.start_byte + self.byte_count

    @property
    def filename(self) -> str:
        users = "_".join(f"{value:02d}" for value in self.oam_indices)
        return (
            f"piece_{self.index:02d}__oam_{users}__byte_{self.start_byte:04X}"
            f"__pal_{self.palette_bank:02d}__{self.width}x{self.height}.png"
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def indexed_png_bytes(
    width: int,
    height: int,
    indices: Sequence[int],
    palette: Sequence[tuple[int, int, int, int]],
) -> bytes:
    if width <= 0 or height <= 0 or len(indices) != width * height:
        raise SpriteEditError("indexed PNG dimensions do not match the index buffer")
    if not palette or len(palette) > 256:
        raise SpriteEditError("indexed PNG palette must contain 1-256 colors")
    if any(index < 0 or index >= len(palette) for index in indices):
        raise SpriteEditError("indexed PNG contains an index outside its palette")

    # Always emit 8-bit indexed PNGs. Editors may later optimize the image to
    # 1/2/4-bit indexed storage; read_png() accepts those variants as well.
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    plte = bytes(channel for color in palette for channel in color[:3])
    alpha = bytes(0 if index == 0 else color[3] for index, color in enumerate(palette))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        start = y * width
        raw.extend(indices[start:start + width])
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"PLTE", plte)
        + _png_chunk(b"tRNS", alpha)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def write_indexed_png(
    path: Path,
    width: int,
    height: int,
    indices: Sequence[int],
    palette: Sequence[tuple[int, int, int, int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(indexed_png_bytes(width, height, indices, palette))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter_png_rows(raw: bytes, row_bytes: int, height: int, filter_bpp: int) -> list[bytes]:
    rows: list[bytes] = []
    cursor = 0
    previous = bytearray(row_bytes)
    for row_index in range(height):
        if cursor >= len(raw):
            raise SpriteEditError(f"PNG ended before scanline {row_index}")
        filter_type = raw[cursor]
        cursor += 1
        if cursor + row_bytes > len(raw):
            raise SpriteEditError(f"PNG scanline {row_index} is truncated")
        encoded = raw[cursor:cursor + row_bytes]
        cursor += row_bytes
        decoded = bytearray(row_bytes)
        for x, value in enumerate(encoded):
            left = decoded[x - filter_bpp] if x >= filter_bpp else 0
            up = previous[x]
            upper_left = previous[x - filter_bpp] if x >= filter_bpp else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = _paeth(left, up, upper_left)
            else:
                raise SpriteEditError(f"unsupported PNG filter type {filter_type}")
            decoded[x] = (value + predictor) & 0xFF
        rows.append(bytes(decoded))
        previous = decoded
    if cursor != len(raw):
        # PNG zlib streams should contain exactly the encoded scanlines. Treat
        # trailing bytes as suspicious rather than silently ignoring them.
        raise SpriteEditError("PNG decompressed stream contains trailing scanline data")
    return rows


def _unpack_indexed_row(row: bytes, width: int, bit_depth: int) -> list[int]:
    if bit_depth == 8:
        if len(row) < width:
            raise SpriteEditError("indexed PNG row is shorter than its width")
        return list(row[:width])
    if bit_depth not in (1, 2, 4):
        raise SpriteEditError(f"unsupported indexed PNG bit depth {bit_depth}")
    mask = (1 << bit_depth) - 1
    per_byte = 8 // bit_depth
    out: list[int] = []
    for value in row:
        for slot in range(per_byte):
            shift = 8 - bit_depth * (slot + 1)
            out.append((value >> shift) & mask)
            if len(out) == width:
                return out
    if len(out) != width:
        raise SpriteEditError("indexed PNG row does not contain enough pixels")
    return out


def read_png(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise SpriteEditError(f"not a PNG file: {path}")

    cursor = len(PNG_SIGNATURE)
    ihdr: tuple[int, int, int, int, int, int, int] | None = None
    plte: list[tuple[int, int, int]] = []
    transparency: bytes | None = None
    idat = bytearray()
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise SpriteEditError(f"truncated PNG chunk header: {path}")
        length = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        payload_end = payload_start + length
        crc_end = payload_end + 4
        if crc_end > len(data):
            raise SpriteEditError(f"truncated PNG chunk {kind!r}: {path}")
        payload = data[payload_start:payload_end]
        expected_crc = struct.unpack_from(">I", data, payload_end)[0]
        actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise SpriteEditError(f"PNG chunk {kind!r} has an invalid CRC: {path}")
        cursor = crc_end

        if kind == b"IHDR":
            if len(payload) != 13:
                raise SpriteEditError("PNG IHDR has the wrong size")
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif kind == b"PLTE":
            if len(payload) % 3:
                raise SpriteEditError("PNG PLTE size is not divisible by 3")
            plte = [tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)]  # type: ignore[list-item]
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break

    if ihdr is None:
        raise SpriteEditError("PNG has no IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = ihdr
    if width <= 0 or height <= 0:
        raise SpriteEditError("PNG dimensions must be positive")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise SpriteEditError("only non-interlaced standard-deflate PNGs are supported")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise SpriteEditError(f"PNG IDAT decompression failed: {exc}") from exc

    if color_type == 3:
        if bit_depth not in (1, 2, 4, 8):
            raise SpriteEditError(f"unsupported indexed PNG bit depth {bit_depth}")
        if not plte:
            raise SpriteEditError("indexed PNG has no PLTE")
        row_bytes = (width * bit_depth + 7) // 8
        rows = _unfilter_png_rows(raw, row_bytes, height, 1)
        indices = [index for row in rows for index in _unpack_indexed_row(row, width, bit_depth)]
        alphas = list(transparency or b"")
        palette_rgba = [
            (rgb[0], rgb[1], rgb[2], alphas[i] if i < len(alphas) else 255)
            for i, rgb in enumerate(plte)
        ]
        return {
            "width": width,
            "height": height,
            "color_type": color_type,
            "indices": indices,
            "palette": palette_rgba,
            "pixels": None,
        }

    if bit_depth != 8 or color_type not in (2, 6):
        raise SpriteEditError(
            f"unsupported PNG color type/bit depth combination: type={color_type}, depth={bit_depth}"
        )
    channels = 3 if color_type == 2 else 4
    row_bytes = width * channels
    rows = _unfilter_png_rows(raw, row_bytes, height, channels)
    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for x in range(width):
            offset = x * channels
            if color_type == 2:
                pixels.append((row[offset], row[offset + 1], row[offset + 2], 255))
            else:
                pixels.append((row[offset], row[offset + 1], row[offset + 2], row[offset + 3]))
    return {
        "width": width,
        "height": height,
        "color_type": color_type,
        "indices": None,
        "palette": None,
        "pixels": pixels,
    }


def pack_4bpp(indices: Sequence[int], width: int, height: int, tiled: bool) -> bytes:
    if len(indices) != width * height:
        raise SpriteEditError("4bpp index buffer does not match dimensions")
    if any(index < 0 or index > 15 for index in indices):
        raise SpriteEditError("4bpp image contains a palette index greater than 15")

    def pack_linear(values: Sequence[int]) -> bytes:
        if len(values) % 2:
            raise SpriteEditError("4bpp pixel count must be even")
        return bytes(values[i] | (values[i + 1] << 4) for i in range(0, len(values), 2))

    if not tiled:
        return pack_linear(indices)
    if width % 8 or height % 8:
        raise SpriteEditError("tiled NCGR piece dimensions must be 8-pixel multiples")
    out = bytearray()
    for tile_y in range(height // 8):
        for tile_x in range(width // 8):
            tile: list[int] = []
            for y in range(8):
                start = (tile_y * 8 + y) * width + tile_x * 8
                tile.extend(indices[start:start + 8])
            out.extend(pack_linear(tile))
    return bytes(out)


def piece_specs(ncer: guardian.core.Ncer, bank_index: int, ncgr: guardian.core.Ncgr) -> list[PieceSpec]:
    if bank_index < 0 or bank_index >= len(ncer.banks):
        raise SpriteEditError(f"NCER bank {bank_index} does not exist; bank count is {len(ncer.banks)}")
    if ncgr.bpp != 4 or ncgr.depth != 3:
        raise SpriteEditError(
            f"first sprite editor supports PLTT16 4bpp NCGR only; got depth={ncgr.depth}, bpp={ncgr.bpp}"
        )

    bank = ncer.banks[bank_index]
    grouped: dict[tuple[int, int, int, int, int], list[int]] = {}
    ranges: dict[tuple[int, int], tuple[int, int, int]] = {}
    for oam in bank.oams:
        if oam.disabled or oam.affine or oam.mode == 2 or oam.width <= 0 or oam.height <= 0:
            continue
        if oam.depth != ncgr.bpp:
            raise SpriteEditError(f"OAM {oam.index} bit depth does not match NCGR")
        start_byte = bank.data_offset + ((oam.tile_offset << ncer.block_size) * 0x20)
        byte_count = oam.width * oam.height * ncgr.bpp // 8
        end_byte = start_byte + byte_count
        if start_byte < 0 or end_byte > len(ncgr.data):
            raise SpriteEditError(
                f"OAM {oam.index} source range {start_byte}:{end_byte} exceeds NCGR payload"
            )
        palette_bank = oam.palette_index
        key = (start_byte, byte_count, oam.width, oam.height, palette_bank)
        grouped.setdefault(key, []).append(oam.index)
        range_key = (start_byte, end_byte)
        interpretation = (oam.width, oam.height, palette_bank)
        prior = ranges.get(range_key)
        if prior is not None and prior != interpretation:
            raise SpriteEditError(
                f"NCGR byte range {start_byte}:{end_byte} is used with conflicting OAM interpretations"
            )
        ranges[range_key] = interpretation

    if not grouped:
        raise SpriteEditError(f"NCER bank {bank_index} has no safely editable OAM graphics")

    ordered = sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1], item[0][2], item[0][3]))
    # Partial overlaps cannot be independently edited without an explicit conflict
    # resolver. Exact duplicate ranges were grouped above and are safe.
    unique_ranges = [(key[0], key[0] + key[1]) for key, _ in ordered]
    for index, (start_a, end_a) in enumerate(unique_ranges):
        for start_b, end_b in unique_ranges[index + 1:]:
            if start_a < end_b and start_b < end_a and (start_a, end_a) != (start_b, end_b):
                raise SpriteEditError(
                    f"bank {bank_index} contains partially overlapping NCGR ranges "
                    f"{start_a}:{end_a} and {start_b}:{end_b}"
                )

    return [
        PieceSpec(
            index=index,
            start_byte=key[0],
            byte_count=key[1],
            width=key[2],
            height=key[3],
            palette_bank=key[4],
            oam_indices=tuple(sorted(users)),
        )
        for index, (key, users) in enumerate(ordered)
    ]


def _load_sources(ncgr_path: Path, nclr_path: Path, ncer_path: Path):
    guardian.install_compatibility()
    ncgr_bytes = ncgr_path.read_bytes()
    nclr_bytes = nclr_path.read_bytes()
    ncer_bytes = ncer_path.read_bytes()
    ncgr = guardian.parse_ncgr(ncgr_bytes)
    nclr = guardian.parse_nclr(nclr_bytes)
    ncer = guardian.core.parse_ncer(ncer_bytes)
    if ncgr.depth != nclr.depth:
        raise SpriteEditError(
            f"NCGR texture format {ncgr.depth} does not match NCLR texture format {nclr.depth}"
        )
    return ncgr_bytes, nclr_bytes, ncer_bytes, ncgr, nclr, ncer


def export_project(
    ncgr_path: Path,
    nclr_path: Path,
    ncer_path: Path,
    bank_index: int,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SpriteEditError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    ncgr_bytes, nclr_bytes, ncer_bytes, ncgr, nclr, ncer = _load_sources(
        ncgr_path, nclr_path, ncer_path
    )
    specs = piece_specs(ncer, bank_index, ncgr)
    bank = ncer.banks[bank_index]

    reference = guardian.core.render_ncer_bank(
        bank, ncer, ncgr, nclr, guardian.core.DEFAULT_MAX_PIXELS
    )
    guardian.core.write_png(output_dir / f"reference_bank_{bank_index:04d}.png", reference)

    pieces_manifest: list[dict[str, object]] = []
    for spec in specs:
        if spec.palette_bank >= len(nclr.palettes):
            raise SpriteEditError(
                f"piece {spec.index} references missing palette bank {spec.palette_bank}"
            )
        palette = nclr.palettes[spec.palette_bank]
        if len(palette) < 16:
            raise SpriteEditError(
                f"piece {spec.index} palette bank {spec.palette_bank} has only {len(palette)} colors"
            )
        source = ncgr.data[spec.start_byte:spec.end_byte]
        indices = guardian.core.decode_pixels(source, 4, spec.width, spec.height, ncgr.tiled)
        write_indexed_png(
            output_dir / "pieces" / spec.filename,
            spec.width,
            spec.height,
            indices,
            palette[:16],
        )
        pieces_manifest.append({
            "index": spec.index,
            "filename": f"pieces/{spec.filename}",
            "start_byte": spec.start_byte,
            "byte_count": spec.byte_count,
            "width": spec.width,
            "height": spec.height,
            "palette_bank": spec.palette_bank,
            "oam_indices": list(spec.oam_indices),
        })

    manifest: dict[str, object] = {
        "format": "pokengineering-ncer-sprite-edit-v1",
        "bank_index": bank_index,
        "ncgr_sha256": sha256_bytes(ncgr_bytes),
        "nclr_sha256": sha256_bytes(nclr_bytes),
        "ncer_sha256": sha256_bytes(ncer_bytes),
        "ncgr_depth": ncgr.depth,
        "ncgr_bpp": ncgr.bpp,
        "ncgr_tiled": ncgr.tiled,
        "ncgr_data_bytes": len(ncgr.data),
        "ncer_block_size": ncer.block_size,
        "piece_count": len(specs),
        "pieces": pieces_manifest,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "README.txt").write_text(
        "Edit only the PNG files inside pieces/.\n"
        "Each PNG is an indexed 16-color source piece used by the NCER bank.\n"
        "Keep the image dimensions unchanged and use only colors from its existing palette.\n"
        "reference_bank_*.png is a flattened reference only; do not import edits from it.\n",
        encoding="utf-8",
    )
    return manifest


def _indices_from_png(
    path: Path,
    expected_width: int,
    expected_height: int,
    expected_palette: Sequence[tuple[int, int, int, int]],
) -> list[int]:
    image = read_png(path)
    width = int(image["width"])
    height = int(image["height"])
    if (width, height) != (expected_width, expected_height):
        raise SpriteEditError(
            f"{path.name} dimensions changed from {expected_width}x{expected_height} to {width}x{height}"
        )

    indices = image["indices"]
    if indices is not None:
        palette = image["palette"]
        assert isinstance(indices, list)
        assert isinstance(palette, list)
        expected_rgb = [tuple(color[:3]) for color in expected_palette]
        actual_rgb = [tuple(color[:3]) for color in palette[:len(expected_palette)]]
        if actual_rgb != expected_rgb:
            raise SpriteEditError(
                f"{path.name} indexed palette changed; keep the exported palette intact"
            )
        if any(index < 0 or index >= len(expected_palette) for index in indices):
            raise SpriteEditError(f"{path.name} uses an index outside the 16-color source palette")
        return [int(index) for index in indices]

    pixels = image["pixels"]
    assert isinstance(pixels, list)
    rgb_to_indices: dict[tuple[int, int, int], list[int]] = {}
    for index, color in enumerate(expected_palette):
        rgb_to_indices.setdefault(tuple(color[:3]), []).append(index)
    out: list[int] = []
    for pixel_index, pixel in enumerate(pixels):
        r, g, b, a = pixel
        if a == 0:
            out.append(0)
            continue
        if a != 255:
            x = pixel_index % expected_width
            y = pixel_index // expected_width
            raise SpriteEditError(
                f"{path.name} pixel ({x},{y}) has partial alpha {a}; use opaque palette colors or transparent index 0"
            )
        matches = rgb_to_indices.get((r, g, b), [])
        if not matches:
            x = pixel_index % expected_width
            y = pixel_index // expected_width
            raise SpriteEditError(
                f"{path.name} pixel ({x},{y}) color #{r:02X}{g:02X}{b:02X} is not in its NCLR palette"
            )
        if len(matches) > 1:
            x = pixel_index % expected_width
            y = pixel_index // expected_width
            raise SpriteEditError(
                f"{path.name} pixel ({x},{y}) uses a duplicated palette color; preserve indexed PNG mode"
            )
        out.append(matches[0])
    return out


def import_project(
    ncgr_path: Path,
    nclr_path: Path,
    ncer_path: Path,
    project_dir: Path,
    output_ncgr: Path,
    *,
    expect_identical: bool = False,
) -> bytes:
    manifest_path = project_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "pokengineering-ncer-sprite-edit-v1":
        raise SpriteEditError("unsupported or missing sprite-edit manifest format")
    bank_index = int(manifest["bank_index"])

    ncgr_bytes, nclr_bytes, ncer_bytes, ncgr, nclr, ncer = _load_sources(
        ncgr_path, nclr_path, ncer_path
    )
    hashes = {
        "ncgr_sha256": sha256_bytes(ncgr_bytes),
        "nclr_sha256": sha256_bytes(nclr_bytes),
        "ncer_sha256": sha256_bytes(ncer_bytes),
    }
    for key, actual in hashes.items():
        expected = str(manifest.get(key, ""))
        if actual != expected:
            raise SpriteEditError(f"source {key.removesuffix('_sha256')} does not match export manifest")

    specs = piece_specs(ncer, bank_index, ncgr)
    manifest_pieces = manifest.get("pieces")
    if not isinstance(manifest_pieces, list) or len(manifest_pieces) != len(specs):
        raise SpriteEditError("manifest piece layout no longer matches the source NCER bank")

    edited_data = bytearray(ncgr.data)
    for spec, row in zip(specs, manifest_pieces, strict=True):
        if not isinstance(row, dict):
            raise SpriteEditError("invalid piece record in manifest")
        expected_layout = (
            int(row["start_byte"]), int(row["byte_count"]), int(row["width"]),
            int(row["height"]), int(row["palette_bank"]), tuple(int(x) for x in row["oam_indices"]),
        )
        actual_layout = (
            spec.start_byte, spec.byte_count, spec.width, spec.height,
            spec.palette_bank, spec.oam_indices,
        )
        if expected_layout != actual_layout:
            raise SpriteEditError(f"piece {spec.index} manifest layout does not match current source")
        palette = nclr.palettes[spec.palette_bank][:16]
        png_path = project_dir / str(row["filename"])
        indices = _indices_from_png(png_path, spec.width, spec.height, palette)
        packed = pack_4bpp(indices, spec.width, spec.height, ncgr.tiled)
        if len(packed) != spec.byte_count:
            raise SpriteEditError(
                f"piece {spec.index} encoded to {len(packed)} bytes; expected {spec.byte_count}"
            )
        edited_data[spec.start_byte:spec.end_byte] = packed

    data_start = ncgr.section.start + 8 + ncgr.data_offset
    data_end = data_start + len(ncgr.data)
    rebuilt = bytearray(ncgr_bytes)
    rebuilt[data_start:data_end] = edited_data
    rebuilt_bytes = bytes(rebuilt)
    if len(rebuilt_bytes) != len(ncgr_bytes):
        raise SpriteEditError("rebuilt NCGR size changed unexpectedly")
    if expect_identical and rebuilt_bytes != ncgr_bytes:
        raise SpriteEditError("unchanged exported pieces did not round-trip to byte-identical NCGR")

    output_ncgr.parent.mkdir(parents=True, exist_ok=True)
    output_ncgr.write_bytes(rebuilt_bytes)
    return rebuilt_bytes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export/import editable source pieces for a Guardian Signs NCER sprite bank."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="export indexed source-piece PNGs and a bank reference")
    export.add_argument("ncgr", type=Path)
    export.add_argument("nclr", type=Path)
    export.add_argument("ncer", type=Path)
    export.add_argument("bank", type=int)
    export.add_argument("output_dir", type=Path)

    imp = sub.add_parser("import", help="encode edited source-piece PNGs back into the NCGR")
    imp.add_argument("ncgr", type=Path)
    imp.add_argument("nclr", type=Path)
    imp.add_argument("ncer", type=Path)
    imp.add_argument("project_dir", type=Path)
    imp.add_argument("output_ncgr", type=Path)
    imp.add_argument("--expect-identical", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "export":
            manifest = export_project(args.ncgr, args.nclr, args.ncer, args.bank, args.output_dir)
            print(f"sprite bank exported: {args.output_dir}")
            print(f"editable source pieces: {manifest['piece_count']}")
            print(f"reference: {args.output_dir / f'reference_bank_{args.bank:04d}.png'}")
            return 0
        rebuilt = import_project(
            args.ncgr, args.nclr, args.ncer, args.project_dir, args.output_ncgr,
            expect_identical=args.expect_identical,
        )
        print(f"rebuilt NCGR: {args.output_ncgr}")
        print(f"rebuilt SHA-256: {sha256_bytes(rebuilt)}")
        if args.expect_identical:
            print("NCGR round-trip: byte-identical")
        return 0
    except (OSError, KeyError, ValueError, SpriteEditError, guardian.core.NitroFormatError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
