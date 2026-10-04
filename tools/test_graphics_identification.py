#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import identify_graphics as identifier
import render_nitro_graphics as renderer


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sprite(color: tuple[int, int, int, int], *, offset: int = 4) -> renderer.Image:
    width = height = 16
    pixels = [(0, 0, 0, 0)] * (width * height)
    for y in range(offset, min(height, offset + 8)):
        for x in range(offset, min(width, offset + 8)):
            pixels[y * width + x] = color
    return renderer.Image(width, height, pixels)


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        catalog = root / "graphics_catalog"
        previews = root / "graphics_previews"
        output = root / "graphics_identification"
        registry = root / "confirmed.json"
        catalog.mkdir()
        previews.mkdir()

        candidate_specs = [
            ("G00001", "acf:0001", "NCER cell bank", "candidates/cells/G00001__bank_0000.png", sprite((0, 200, 0, 255)), "ncgr-known", 1),
            ("G00002", "acf:0002", "NCER cell bank", "candidates/cells/G00002__bank_0000.png", sprite((0, 200, 0, 255)), "ncgr-copy", 0),
            ("G00003", "acf:0003", "NCER cell bank", "candidates/cells/G00003__bank_0000.png", sprite((0, 0, 220, 255)), "ncgr-color", 0),
            ("G00004", "acf:0004", "NCER cell bank", "candidates/cells/G00004__bank_0000.png", sprite((220, 0, 0, 255), offset=1), "ncgr-known", 0),
            ("G00005", "acf:0005", "NSCR background", "candidates/backgrounds/G00005.png", renderer.Image(16, 16, [(30, 60, 90, 255)] * 256), "ncgr-bg", 0),
        ]

        resources: list[dict[str, object]] = []
        inspections: list[dict[str, object]] = []
        runs: list[dict[str, object]] = []
        candidates: list[dict[str, object]] = []

        for run_id, parent, preview_kind, preview_path, image, ncgr_sha, nanr_count in candidate_specs:
            renderer.write_png(previews / preview_path, image)
            suffix = int(run_id[1:])
            ncgr_path = f"{parent}/acf:0001"
            nclr_path = f"{parent}/acf:0002"
            layout_path = f"{parent}/acf:0003"
            layout_kind = "NCER" if preview_kind == "NCER cell bank" else "NSCR"
            for index, logical_path, kind, sha in (
                (1, ncgr_path, "NCGR", ncgr_sha),
                (2, nclr_path, "NCLR", f"nclr-{suffix}"),
                (3, layout_path, layout_kind, f"layout-{suffix}"),
            ):
                resources.append(
                    {
                        "logical_path": logical_path,
                        "parent_path": parent,
                        "depth": 2,
                        "parent_container": "ACF",
                        "entry_index": index,
                        "state": "acf-compressed",
                        "kind": kind,
                        "size": 100 + index,
                        "sha256": sha,
                        "payload_path": f"payloads/{run_id}_{kind.lower()}",
                    }
                )
                inspections.append(
                    {
                        "logical_path": logical_path,
                        "kind": kind,
                        "parse_status": "ok",
                        "error": "",
                        "width": "",
                        "height": "",
                        "bpp": 4 if kind in ("NCGR", "NCLR") else "",
                        "tile_count": 8 if kind == "NCGR" else "",
                        "palette_count": 1 if kind == "NCLR" else "",
                        "colors_per_palette": 16 if kind == "NCLR" else "",
                        "bank_count": 1 if kind == "NCER" else "",
                        "oam_count": 2 if kind == "NCER" else "",
                        "sections": 1,
                        "atomic_preview_path": "",
                        "presentation_basis": "",
                    }
                )
            runs.append(
                {
                    "run_id": run_id,
                    "parent_path": parent,
                    "start_index": 1,
                    "end_index": 3,
                    "resource_count": 3,
                    "NCGR": 1,
                    "NCLR": 1,
                    "NSCR": 1 if layout_kind == "NSCR" else 0,
                    "NCER": 1 if layout_kind == "NCER" else 0,
                    "NANR": nanr_count,
                    "resource_paths": f"{ncgr_path} {nclr_path} {layout_path}",
                    "fact": "maximal_contiguous_graphics_run",
                    "semantic_pairing_proven": False,
                }
            )
            candidates.append(
                {
                    "run_id": run_id,
                    "preview_kind": preview_kind,
                    "ncgr_path": ncgr_path,
                    "nclr_path": nclr_path,
                    "layout_path": layout_path,
                    "bank_index": 0 if preview_kind == "NCER cell bank" else "",
                    "preview_path": preview_path,
                    "structural_basis": "synthetic_test",
                    "semantic_pairing_proven": False,
                }
            )

        write_csv(
            catalog / "resources.csv",
            resources,
            ["logical_path", "parent_path", "depth", "parent_container", "entry_index", "state", "kind", "size", "sha256", "payload_path"],
        )
        write_csv(
            catalog / "adjacent_runs.csv",
            runs,
            ["run_id", "parent_path", "start_index", "end_index", "resource_count", "NCGR", "NCLR", "NSCR", "NCER", "NANR", "resource_paths", "fact", "semantic_pairing_proven"],
        )
        write_csv(
            previews / "resource_inspection.csv",
            inspections,
            ["logical_path", "kind", "parse_status", "error", "width", "height", "bpp", "tile_count", "palette_count", "colors_per_palette", "bank_count", "oam_count", "sections", "atomic_preview_path", "presentation_basis"],
        )
        write_csv(
            previews / "candidate_previews.csv",
            candidates,
            ["run_id", "preview_kind", "ncgr_path", "nclr_path", "layout_path", "bank_index", "preview_path", "structural_basis", "semantic_pairing_proven"],
        )

        registry.write_text(
            json.dumps(
                {
                    "format": "pokengineering-confirmed-graphics-assets-v1",
                    "assets": {
                        "TEST001": {
                            "preview_id": "G00001__bank_0000",
                            "semantic_name": "synthetic known sprite",
                            "status": "in_game_verified",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        summary = identifier.identify_catalog(catalog, previews, output, registry)
        if summary["candidates_catalogued"] != 5:
            raise SystemExit("identifier did not catalogue all synthetic candidates")
        if summary["confirmed_candidates_found"] != 1:
            raise SystemExit("identifier did not resolve the confirmed synthetic asset")

        with (output / "identified_candidates.csv").open("r", encoding="utf-8", newline="") as source:
            identified = {row["candidate_id"]: row for row in csv.DictReader(source)}

        known = identified["G00001__bank_0000"]
        exact = identified["G00002__bank_0000"]
        recolor = identified["G00003__bank_0000"]
        shared = identified["G00004__bank_0000"]
        background = identified["G00005__background"]

        if known["confirmed_asset_id"] != "TEST001" or "confirmed:TEST001" not in known["related_confirmed_assets"]:
            raise SystemExit("confirmed candidate did not retain its registry identity")
        if "exact_visual:TEST001" not in exact["related_confirmed_assets"]:
            raise SystemExit("exact visual duplicate was not related to the confirmed asset")
        if "same_alpha_shape:TEST001" not in recolor["related_confirmed_assets"]:
            raise SystemExit("palette/color variant was not detected by alpha shape")
        if "shared_ncgr:TEST001" not in shared["related_confirmed_assets"]:
            raise SystemExit("shared NCGR source was not related to the confirmed asset")
        if known["visual_group"] != exact["visual_group"] or int(known["visual_group_size"]) != 2:
            raise SystemExit("exact visual grouping is inconsistent")
        if background["likely_class"] != "background_or_ui_screen" or background["alpha_shape_sha256"]:
            raise SystemExit("opaque background classification/silhouette suppression failed")
        if known["likely_class"] != "animated_sprite_candidate":
            raise SystemExit("NANR-bearing cell candidate was not marked as animated")
        if not (output / "index.html").is_file() or "G00001__bank_0000" not in (output / "index.html").read_text(encoding="utf-8"):
            raise SystemExit("browseable identification gallery was not generated")

        with (output / "families.csv").open("r", encoding="utf-8", newline="") as source:
            families = list(csv.DictReader(source))
        if not any(row["family_type"] == "exact_visual" and int(row["member_count"]) == 2 for row in families):
            raise SystemExit("exact-visual family was not emitted")

    print("automatic graphics identification synthetic test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
