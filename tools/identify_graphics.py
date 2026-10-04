#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import struct
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class IdentificationError(ValueError):
    pass


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing required file: {path}")
    with path.open("r", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing required file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise IdentificationError(f"JSON root is not an object: {path}")
    return data


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


def read_rgba_png(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """Read the deterministic RGBA PNGs emitted by the preview renderer.

    The renderer currently writes non-interlaced, 8-bit RGBA images. Supporting
    PNG filters 0-4 makes the identifier tolerant of lossless PNG optimization.
    """
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise IdentificationError(f"not a PNG file: {path}")

    cursor = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise IdentificationError(f"truncated PNG chunk header: {path}")
        length = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        payload_end = payload_start + length
        crc_end = payload_end + 4
        if crc_end > len(data):
            raise IdentificationError(f"truncated PNG chunk {kind!r}: {path}")
        payload = data[payload_start:payload_end]
        expected_crc = struct.unpack_from(">I", data, payload_end)[0]
        actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise IdentificationError(f"PNG chunk {kind!r} has an invalid CRC: {path}")
        cursor = crc_end

        if kind == b"IHDR":
            if len(payload) != 13:
                raise IdentificationError(f"PNG IHDR has invalid size: {path}")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if compression != 0 or filter_method != 0:
                raise IdentificationError(f"unsupported PNG compression/filter method: {path}")
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break

    if None in (width, height, bit_depth, color_type, interlace):
        raise IdentificationError(f"PNG has no usable IHDR: {path}")
    assert width is not None and height is not None
    assert bit_depth is not None and color_type is not None and interlace is not None
    if bit_depth != 8 or color_type != 6 or interlace != 0:
        raise IdentificationError(
            f"identifier expects non-interlaced 8-bit RGBA preview PNGs; "
            f"got depth={bit_depth}, type={color_type}, interlace={interlace}: {path}"
        )

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise IdentificationError(f"PNG decompression failed for {path}: {exc}") from exc

    row_bytes = width * 4
    expected_min = height * (row_bytes + 1)
    if len(raw) != expected_min:
        raise IdentificationError(
            f"PNG decompressed length {len(raw)} does not match {expected_min}: {path}"
        )

    rows: list[bytes] = []
    previous = bytearray(row_bytes)
    offset = 0
    for row_index in range(height):
        filter_type = raw[offset]
        offset += 1
        encoded = raw[offset:offset + row_bytes]
        offset += row_bytes
        decoded = bytearray(row_bytes)
        for x, value in enumerate(encoded):
            left = decoded[x - 4] if x >= 4 else 0
            up = previous[x]
            upper_left = previous[x - 4] if x >= 4 else 0
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
                raise IdentificationError(
                    f"unsupported PNG filter {filter_type} on row {row_index}: {path}"
                )
            decoded[x] = (value + predictor) & 0xFF
        rows.append(bytes(decoded))
        previous = decoded

    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for x in range(width):
            base = x * 4
            pixels.append((row[base], row[base + 1], row[base + 2], row[base + 3]))
    return width, height, pixels


def candidate_id(row: dict[str, str]) -> str:
    run_id = row["run_id"]
    kind = row["preview_kind"]
    if kind == "NCER cell bank":
        return f"{run_id}__bank_{int(row['bank_index']):04d}"
    if kind == "NSCR background":
        return f"{run_id}__background"
    if kind == "NCGR+NCLR sheet":
        return f"{run_id}__sheet"
    safe = kind.lower().replace(" ", "_").replace("+", "_")
    return f"{run_id}__{safe}"


def pixel_hash(width: int, height: int, pixels: Sequence[tuple[int, int, int, int]]) -> str:
    digest = hashlib.sha256()
    digest.update(struct.pack(">II", width, height))
    digest.update(bytes(channel for pixel in pixels for channel in pixel))
    return digest.hexdigest()


def alpha_shape_hash(
    width: int,
    height: int,
    pixels: Sequence[tuple[int, int, int, int]],
) -> tuple[str, float]:
    mask = bytes(1 if pixel[3] >= 128 else 0 for pixel in pixels)
    coverage = sum(mask) / max(1, len(mask))
    # A fully opaque screen has no useful silhouette; grouping all backgrounds by
    # their rectangular alpha plane would be actively misleading.
    if coverage <= 0.005 or coverage >= 0.995:
        return "", coverage
    digest = hashlib.sha256()
    digest.update(struct.pack(">II", width, height))
    digest.update(mask)
    return digest.hexdigest(), coverage


def _sample_pixel(
    pixels: Sequence[tuple[int, int, int, int]], width: int, height: int, x: int, y: int
) -> tuple[int, int, int, int]:
    return pixels[min(height - 1, max(0, y)) * width + min(width - 1, max(0, x))]


def _composited_luma(pixel: tuple[int, int, int, int]) -> int:
    r, g, b, a = pixel
    # Composite transparent pixels over white before calculating luminance. This
    # makes the hash useful for sprites with transparent canvases.
    r = (r * a + 255 * (255 - a) + 127) // 255
    g = (g * a + 255 * (255 - a) + 127) // 255
    b = (b * a + 255 * (255 - a) + 127) // 255
    return (299 * r + 587 * g + 114 * b + 500) // 1000


def difference_hash(
    width: int,
    height: int,
    pixels: Sequence[tuple[int, int, int, int]],
) -> str:
    bits = 0
    for y in range(8):
        sy = 0 if height == 1 else round(y * (height - 1) / 7)
        row: list[int] = []
        for x in range(9):
            sx = 0 if width == 1 else round(x * (width - 1) / 8)
            row.append(_composited_luma(_sample_pixel(pixels, width, height, sx, sy)))
        for x in range(8):
            bits = (bits << 1) | int(row[x] > row[x + 1])
    return f"{bits:016x}"


def hamming_hex(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("hash strings must have equal length")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def classify_candidate(row: dict[str, str], run: dict[str, str] | None) -> str:
    kind = row["preview_kind"]
    if kind == "NCER cell bank":
        if run is not None and int(run.get("NANR", "0") or 0) > 0:
            return "animated_sprite_candidate"
        return "sprite_cell_bank"
    if kind == "NSCR background":
        return "background_or_ui_screen"
    if kind == "NCGR+NCLR sheet":
        return "graphics_tile_sheet"
    return "unclassified_graphics"


def size_tag(width: int, height: int, likely_class: str) -> str:
    longest = max(width, height)
    if likely_class in ("sprite_cell_bank", "animated_sprite_candidate"):
        if longest <= 32:
            return "icon_scale"
        if longest <= 64:
            return "small_sprite_scale"
        if longest <= 128:
            return "medium_sprite_scale"
        return "large_sprite_scale"
    if width >= 192 or height >= 128:
        return "screen_scale"
    return "compact_graphics"


def stable_group(prefix: str, key: str) -> str:
    return f"{prefix}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"


def relation_string(relations: list[tuple[str, str, int | None]]) -> str:
    order = {
        "confirmed": 0,
        "exact_visual": 1,
        "shared_ncgr": 2,
        "same_alpha_shape": 3,
        "near_visual": 4,
    }
    relations.sort(key=lambda item: (order.get(item[0], 99), item[1], item[2] or 0))
    parts = []
    for relation, asset_id, distance in relations:
        suffix = f":d{distance}" if distance is not None else ""
        parts.append(f"{relation}:{asset_id}{suffix}")
    return " ".join(parts)


def load_confirmed(registry_path: Path) -> dict[str, dict[str, Any]]:
    registry = load_json(registry_path)
    if registry.get("format") != "pokengineering-confirmed-graphics-assets-v1":
        raise IdentificationError(f"unsupported confirmed-asset registry format: {registry_path}")
    assets = registry.get("assets")
    if not isinstance(assets, dict):
        raise IdentificationError("confirmed-asset registry has no assets object")
    result: dict[str, dict[str, Any]] = {}
    for asset_id, record in assets.items():
        if not isinstance(record, dict) or not record.get("preview_id"):
            continue
        result[str(record["preview_id"])] = {"asset_id": str(asset_id), **record}
    return result


def identify_catalog(
    catalog_dir: Path,
    preview_dir: Path,
    output_dir: Path,
    registry_path: Path,
) -> dict[str, Any]:
    catalog_dir = catalog_dir.resolve()
    preview_dir = preview_dir.resolve()
    output_dir = output_dir.resolve()
    registry_path = registry_path.resolve()

    resources = read_csv(catalog_dir / "resources.csv")
    runs = read_csv(catalog_dir / "adjacent_runs.csv")
    inspections = read_csv(preview_dir / "resource_inspection.csv")
    candidates = read_csv(preview_dir / "candidate_previews.csv")
    confirmed = load_confirmed(registry_path)

    resource_by_path = {row["logical_path"]: row for row in resources}
    run_by_id = {row["run_id"]: row for row in runs}
    inspection_by_path = {row["logical_path"]: row for row in inspections}
    if len(resource_by_path) != len(resources):
        raise IdentificationError("graphics resources contain duplicate logical paths")
    if len(run_by_id) != len(runs):
        raise IdentificationError("adjacent graphics runs contain duplicate run IDs")

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    missing_previews: list[str] = []

    for candidate in candidates:
        cid = candidate_id(candidate)
        preview_rel = candidate.get("preview_path", "")
        if not preview_rel:
            missing_previews.append(cid)
            continue
        preview_path = preview_dir / preview_rel
        if not preview_path.is_file():
            missing_previews.append(cid)
            continue

        width, height, pixels = read_rgba_png(preview_path)
        p_hash = pixel_hash(width, height, pixels)
        shape_hash, alpha_coverage = alpha_shape_hash(width, height, pixels)
        d_hash = difference_hash(width, height, pixels)
        run = run_by_id.get(candidate["run_id"])
        likely_class = classify_candidate(candidate, run)

        ncgr_path = candidate.get("ncgr_path", "")
        nclr_path = candidate.get("nclr_path", "")
        layout_path = candidate.get("layout_path", "")
        ncgr_res = resource_by_path.get(ncgr_path, {})
        nclr_res = resource_by_path.get(nclr_path, {})
        layout_res = resource_by_path.get(layout_path, {}) if layout_path else {}
        ncgr_inspection = inspection_by_path.get(ncgr_path, {})
        nclr_inspection = inspection_by_path.get(nclr_path, {})
        layout_inspection = inspection_by_path.get(layout_path, {}) if layout_path else {}

        structure_parts = [
            candidate.get("preview_kind", ""),
            f"{width}x{height}",
            str(ncgr_inspection.get("bpp", "")),
            str(ncgr_inspection.get("tile_count", "")),
            str(nclr_inspection.get("palette_count", "")),
            str(layout_inspection.get("bank_count", "")),
            str(layout_inspection.get("oam_count", "")),
            str(run.get("NANR", "") if run else ""),
        ]
        structure_key = "|".join(structure_parts)
        source_key = "|".join(
            [
                str(ncgr_res.get("sha256", "")),
                str(nclr_res.get("sha256", "")),
                str(layout_res.get("sha256", "")),
                str(candidate.get("bank_index", "")),
            ]
        )

        rows.append(
            {
                "candidate_id": cid,
                "run_id": candidate["run_id"],
                "preview_kind": candidate["preview_kind"],
                "likely_class": likely_class,
                "size_tag": size_tag(width, height, likely_class),
                "width": width,
                "height": height,
                "alpha_coverage": f"{alpha_coverage:.6f}",
                "pixel_sha256": p_hash,
                "alpha_shape_sha256": shape_hash,
                "difference_hash": d_hash,
                "structure_key": structure_key,
                "source_key": source_key,
                "ncgr_sha256": ncgr_res.get("sha256", ""),
                "nclr_sha256": nclr_res.get("sha256", ""),
                "layout_sha256": layout_res.get("sha256", ""),
                "ncgr_path": ncgr_path,
                "nclr_path": nclr_path,
                "layout_path": layout_path,
                "bank_index": candidate.get("bank_index", ""),
                "parent_path": run.get("parent_path", "") if run else "",
                "has_nanr": bool(run and int(run.get("NANR", "0") or 0) > 0),
                "preview_path": preview_rel,
                "preview_absolute": str(preview_path),
                "confirmed_asset_id": "",
                "confirmed_status": "",
                "confirmed_semantic_name": "",
                "related_confirmed_assets": "",
                "automatic_tags": "",
                "review_score": 0,
            }
        )

    if not rows:
        detail = "full preview PNGs are missing" if missing_previews else "candidate catalogue is empty"
        raise IdentificationError(f"no candidate previews could be fingerprinted: {detail}")

    visual_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    shape_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ncgr_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    structure_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        visual_groups[row["pixel_sha256"]].append(row)
        if row["alpha_shape_sha256"]:
            shape_groups[row["alpha_shape_sha256"]].append(row)
        if row["ncgr_sha256"]:
            ncgr_groups[row["ncgr_sha256"]].append(row)
        structure_groups[row["structure_key"]].append(row)
        source_groups[row["source_key"]].append(row)

    for row in rows:
        row["visual_group"] = stable_group("V", row["pixel_sha256"])
        row["visual_group_size"] = len(visual_groups[row["pixel_sha256"]])
        if row["alpha_shape_sha256"]:
            row["shape_group"] = stable_group("A", row["alpha_shape_sha256"])
            row["shape_group_size"] = len(shape_groups[row["alpha_shape_sha256"]])
        else:
            row["shape_group"] = ""
            row["shape_group_size"] = 0
        row["ncgr_group"] = stable_group("N", row["ncgr_sha256"]) if row["ncgr_sha256"] else ""
        row["ncgr_group_size"] = len(ncgr_groups[row["ncgr_sha256"]]) if row["ncgr_sha256"] else 0
        row["structure_group"] = stable_group("T", row["structure_key"])
        row["structure_group_size"] = len(structure_groups[row["structure_key"]])
        row["source_group"] = stable_group("R", row["source_key"])
        row["source_group_size"] = len(source_groups[row["source_key"]])

    row_by_id = {row["candidate_id"]: row for row in rows}
    confirmed_rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for preview_id, record in confirmed.items():
        row = row_by_id.get(preview_id)
        if row is None:
            continue
        asset_id = record["asset_id"]
        row["confirmed_asset_id"] = asset_id
        row["confirmed_status"] = record.get("status", "")
        row["confirmed_semantic_name"] = record.get("semantic_name") or ""
        confirmed_rows.append((asset_id, record, row))

    for row in rows:
        relations: list[tuple[str, str, int | None]] = []
        for asset_id, _record, known in confirmed_rows:
            if row is known:
                relations.append(("confirmed", asset_id, None))
                continue
            if row["pixel_sha256"] == known["pixel_sha256"]:
                relations.append(("exact_visual", asset_id, None))
                continue
            if row["ncgr_sha256"] and row["ncgr_sha256"] == known["ncgr_sha256"]:
                relations.append(("shared_ncgr", asset_id, None))
                continue
            if (
                row["alpha_shape_sha256"]
                and row["alpha_shape_sha256"] == known["alpha_shape_sha256"]
                and row["preview_kind"] == known["preview_kind"]
            ):
                relations.append(("same_alpha_shape", asset_id, None))
                continue
            same_kind = row["preview_kind"] == known["preview_kind"]
            aspect_a = row["width"] / max(1, row["height"])
            aspect_b = known["width"] / max(1, known["height"])
            aspect_close = abs(aspect_a - aspect_b) <= max(0.15, aspect_b * 0.15)
            if same_kind and aspect_close:
                distance = hamming_hex(row["difference_hash"], known["difference_hash"])
                if distance <= 5:
                    relations.append(("near_visual", asset_id, distance))
        row["related_confirmed_assets"] = relation_string(relations)

        tags = [row["likely_class"], row["size_tag"]]
        if row["has_nanr"]:
            tags.append("animation_data_present")
        if row["visual_group_size"] > 1:
            tags.append("exact_visual_duplicate")
        if row["shape_group_size"] > row["visual_group_size"] and row["shape_group_size"] > 1:
            tags.append("palette_or_color_variant_candidate")
        if row["ncgr_group_size"] > 1:
            tags.append("shared_ncgr_source")
        if row["structure_group_size"] > 1:
            tags.append("shared_structure")
        if row["confirmed_asset_id"]:
            tags.append("confirmed_in_game")
        elif row["related_confirmed_assets"]:
            tags.append("related_to_confirmed_asset")
        row["automatic_tags"] = " ".join(dict.fromkeys(tags))

        score = 0
        relation_text = row["related_confirmed_assets"]
        if row["confirmed_asset_id"]:
            score = 100
        elif "exact_visual:" in relation_text:
            score = 90
        elif "shared_ncgr:" in relation_text:
            score = 80
        elif "same_alpha_shape:" in relation_text:
            score = 70
        elif "near_visual:" in relation_text:
            score = 60
        elif row["likely_class"] == "animated_sprite_candidate":
            score = 35
        elif row["likely_class"] == "sprite_cell_bank":
            score = 30
        elif row["likely_class"] == "background_or_ui_screen":
            score = 20
        else:
            score = 10
        row["review_score"] = score

    family_rows: list[dict[str, Any]] = []

    def add_families(kind: str, prefix: str, groups: dict[str, list[dict[str, Any]]], minimum: int = 2) -> None:
        for key, members in groups.items():
            if len(members) < minimum:
                continue
            confirmed_assets = sorted({m["confirmed_asset_id"] for m in members if m["confirmed_asset_id"]})
            family_rows.append(
                {
                    "family_type": kind,
                    "family_id": stable_group(prefix, key),
                    "member_count": len(members),
                    "confirmed_assets": " ".join(confirmed_assets),
                    "members": " ".join(sorted(m["candidate_id"] for m in members)),
                }
            )

    add_families("exact_visual", "V", visual_groups)
    add_families("same_alpha_shape", "A", shape_groups)
    add_families("shared_ncgr", "N", ncgr_groups)
    add_families("same_resource_set", "R", source_groups)
    add_families("same_structure", "T", structure_groups)
    family_rows.sort(key=lambda row: (row["family_type"], -int(row["member_count"]), row["family_id"]))

    output_fields = [
        "candidate_id", "run_id", "preview_kind", "likely_class", "size_tag", "width", "height",
        "alpha_coverage", "review_score", "confirmed_asset_id", "confirmed_status",
        "confirmed_semantic_name", "related_confirmed_assets", "automatic_tags",
        "visual_group", "visual_group_size", "shape_group", "shape_group_size",
        "ncgr_group", "ncgr_group_size", "source_group", "source_group_size",
        "structure_group", "structure_group_size", "difference_hash", "pixel_sha256",
        "alpha_shape_sha256", "ncgr_sha256", "nclr_sha256", "layout_sha256",
        "parent_path", "ncgr_path", "nclr_path", "layout_path", "bank_index", "preview_path",
    ]
    rows.sort(key=lambda row: (-int(row["review_score"]), row["likely_class"], row["candidate_id"]))
    write_csv(output_dir / "identified_candidates.csv", rows, output_fields)
    write_csv(
        output_dir / "families.csv",
        family_rows,
        ["family_type", "family_id", "member_count", "confirmed_assets", "members"],
    )

    class_counts = Counter(row["likely_class"] for row in rows)
    related_count = sum(bool(row["related_confirmed_assets"]) for row in rows)
    summary = {
        "candidates_catalogued": len(rows),
        "candidate_previews_missing": len(missing_previews),
        "confirmed_candidates_found": len(confirmed_rows),
        "candidates_related_to_confirmed": related_count,
        "classes": dict(sorted(class_counts.items())),
        "families": len(family_rows),
        "families_by_type": dict(sorted(Counter(row["family_type"] for row in family_rows).items())),
        "method": {
            "semantic_claims": "Only labels from docs/confirmed_graphics_assets.json are treated as confirmed semantic facts.",
            "exact_visual": "RGBA pixels and canvas dimensions match exactly.",
            "same_alpha_shape": "Canvas dimensions and per-pixel opaque/transparent mask match; fully opaque/transparent canvases are excluded.",
            "shared_ncgr": "Candidates resolve to NCGR resources with the same SHA-256.",
            "near_visual": "64-bit difference-hash Hamming distance <= 5, same preview type, and similar aspect ratio; this is a review hint only.",
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_gallery(output_dir / "index.html", rows, preview_dir, output_dir, summary)

    print(f"graphics candidates fingerprinted: {len(rows)}")
    print(f"confirmed candidates found: {len(confirmed_rows)}")
    print(f"candidates related to confirmed assets: {related_count}")
    print(f"automatic families: {len(family_rows)}")
    for name, count in sorted(class_counts.items()):
        print(f"class {name}: {count}")
    if missing_previews:
        print(f"candidate previews missing: {len(missing_previews)}")
    print(f"identification index: {output_dir / 'identified_candidates.csv'}")
    print(f"browseable gallery: {output_dir / 'index.html'}")
    return summary


def write_gallery(
    path: Path,
    rows: Sequence[dict[str, Any]],
    preview_dir: Path,
    output_dir: Path,
    summary: dict[str, Any],
) -> None:
    classes = sorted({str(row["likely_class"]) for row in rows})
    cards: list[str] = []
    for row in rows:
        image_path = preview_dir / str(row["preview_path"])
        relative_image = os.path.relpath(image_path, output_dir).replace(os.sep, "/")
        search_blob = " ".join(
            str(row.get(key, ""))
            for key in (
                "candidate_id", "likely_class", "automatic_tags", "related_confirmed_assets",
                "parent_path", "ncgr_path", "nclr_path", "layout_path",
            )
        ).lower()
        confirmed_badge = ""
        if row["confirmed_asset_id"]:
            name = row["confirmed_semantic_name"] or row["confirmed_asset_id"]
            confirmed_badge = f'<span class="confirmed">CONFIRMED: {html.escape(str(name))}</span>'
        relation = html.escape(str(row["related_confirmed_assets"])) or "none"
        cards.append(
            f'''<article class="card" data-class="{html.escape(str(row['likely_class']))}" data-search="{html.escape(search_blob, quote=True)}" data-related="{1 if row['related_confirmed_assets'] else 0}">
  <a href="{html.escape(relative_image, quote=True)}"><img loading="lazy" src="{html.escape(relative_image, quote=True)}" alt="{html.escape(str(row['candidate_id']), quote=True)}"></a>
  <h2>{html.escape(str(row['candidate_id']))}</h2>
  {confirmed_badge}
  <p><b>{html.escape(str(row['likely_class']))}</b> · {row['width']}×{row['height']} · score {row['review_score']}</p>
  <p class="tags">{html.escape(str(row['automatic_tags']))}</p>
  <details><summary>relations and sources</summary>
    <p><b>Confirmed relation:</b> {relation}</p>
    <p><b>Visual family:</b> {html.escape(str(row['visual_group']))} ({row['visual_group_size']})</p>
    <p><b>Shape family:</b> {html.escape(str(row['shape_group'])) or 'n/a'} ({row['shape_group_size']})</p>
    <p><b>NCGR family:</b> {html.escape(str(row['ncgr_group'])) or 'n/a'} ({row['ncgr_group_size']})</p>
    <p><code>{html.escape(str(row['ncgr_path']))}</code><br><code>{html.escape(str(row['nclr_path']))}</code><br><code>{html.escape(str(row['layout_path']))}</code></p>
  </details>
</article>'''
        )

    options = "\n".join(f'<option value="{html.escape(value)}">{html.escape(value)}</option>' for value in classes)
    path.write_text(
        f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guardian Signs graphics identification</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ margin: 1rem; }}
.controls {{ position: sticky; top: 0; z-index: 2; padding: .75rem; background: Canvas; border-bottom: 1px solid GrayText; display: flex; gap: .75rem; flex-wrap: wrap; }}
input, select {{ font: inherit; padding: .4rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: .8rem; margin-top: 1rem; }}
.card {{ border: 1px solid GrayText; border-radius: .5rem; padding: .6rem; overflow-wrap: anywhere; }}
.card img {{ width: 100%; height: 190px; object-fit: contain; image-rendering: pixelated; background: repeating-conic-gradient(#8882 0 25%, transparent 0 50%) 0/16px 16px; }}
h2 {{ font-size: 1rem; margin: .4rem 0; }}
p {{ margin: .35rem 0; font-size: .88rem; }}
.tags {{ opacity: .8; }}
.confirmed {{ display: inline-block; padding: .15rem .35rem; border: 1px solid currentColor; border-radius: .25rem; font-weight: 700; }}
.hidden {{ display: none; }}
code {{ font-size: .78rem; }}
</style>
</head>
<body>
<h1>Guardian Signs automatic graphics identification</h1>
<p>{summary['candidates_catalogued']} rendered candidates; {summary['confirmed_candidates_found']} confirmed; {summary['candidates_related_to_confirmed']} related to confirmed assets. Structural/visual relations are hypotheses unless explicitly marked CONFIRMED.</p>
<div class="controls">
<label>Search <input id="search" type="search" placeholder="G00583, sprite, acf:2140..."></label>
<label>Class <select id="class"><option value="">all</option>{options}</select></label>
<label><input id="related" type="checkbox"> only confirmed/related</label>
<span id="count"></span>
</div>
<div class="grid" id="grid">{''.join(cards)}</div>
<script>
const cards=[...document.querySelectorAll('.card')];
const q=document.querySelector('#search'), c=document.querySelector('#class'), r=document.querySelector('#related'), count=document.querySelector('#count');
function filter(){{
  const needle=q.value.trim().toLowerCase(), klass=c.value, related=r.checked;
  let shown=0;
  for(const card of cards){{
    const ok=(!needle||card.dataset.search.includes(needle))&&(!klass||card.dataset.class===klass)&&(!related||card.dataset.related==='1');
    card.classList.toggle('hidden',!ok); if(ok) shown++;
  }}
  count.textContent=`${{shown}} shown`;
}}
q.addEventListener('input',filter); c.addEventListener('change',filter); r.addEventListener('change',filter); filter();
</script>
</body>
</html>
''',
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Fingerprint rendered Guardian Signs graphics, classify their structural role, "
            "group duplicates/variants, and relate them to confirmed assets."
        )
    )
    parser.add_argument(
        "catalog_dir",
        type=Path,
        nargs="?",
        default=root / "work/game_acf/graphics_catalog",
    )
    parser.add_argument(
        "preview_dir",
        type=Path,
        nargs="?",
        default=root / "work/game_acf/graphics_previews",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=root / "work/game_acf/graphics_identification",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=root / "docs/confirmed_graphics_assets.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        identify_catalog(args.catalog_dir, args.preview_dir, args.output_dir, args.registry)
        return 0
    except (OSError, ValueError, IdentificationError) as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
