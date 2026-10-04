#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import struct
import sys
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("render_nitro_graphics.py")
spec = importlib.util.spec_from_file_location("render_nitro_graphics", MODULE_PATH)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = renderer
spec.loader.exec_module(renderer)


def nitro_file(magic: bytes, sections: list[bytes], version: int = 0x0100) -> bytes:
    size = 16 + sum(len(section) for section in sections)
    return magic + struct.pack("<HHIHH", 0xFEFF, version, size, 16, len(sections)) + b"".join(sections)


def make_ncgr() -> bytes:
    tile0 = bytes([0x10] * 32)
    tile1 = bytes([0x32] * 32)
    pixels = tile0 + tile1
    section_size = 0x20 + len(pixels)
    section = (
        b"RAHC"
        + struct.pack("<IHHIHHIII", section_size, 1, 2, 3, 0, 0, 0, len(pixels), 0x18)
        + pixels
    )
    assert len(section) == section_size
    return nitro_file(b"RGCN", [section], 0x0101)


def bgr555(r: int, g: int, b: int) -> int:
    return ((b & 31) << 10) | ((g & 31) << 5) | (r & 31)


def make_nclr() -> bytes:
    palette0 = [bgr555(0, 0, 0), bgr555(31, 0, 0), bgr555(0, 31, 0), bgr555(0, 0, 31)] + [0] * 12
    palette1 = [bgr555(0, 0, 0), bgr555(31, 31, 0), bgr555(0, 31, 31), bgr555(31, 0, 31)] + [0] * 12
    colors = b"".join(struct.pack("<H", color) for color in palette0 + palette1)
    section_size = 0x18 + len(colors)
    section = b"TTLP" + struct.pack("<IHHIII", section_size, 3, 0, 0, len(colors), 0x10) + colors
    assert len(section) == section_size
    return nitro_file(b"RLCN", [section])


def make_nscr() -> bytes:
    entries = [0, 1 | (1 << 10) | (1 << 12)]
    map_data = b"".join(struct.pack("<H", entry) for entry in entries)
    section_size = 0x14 + len(map_data)
    section = b"NRCS" + struct.pack("<IHHII", section_size, 16, 8, 0, len(map_data)) + map_data
    assert len(section) == section_size
    return nitro_file(b"RCSN", [section])


def make_ncer() -> bytes:
    fixed = struct.pack("<HHIIIQ", 1, 0, 0x18, 0, 0, 0)
    bank = struct.pack("<HHI", 1, 0, 0)
    oam = struct.pack("<HHH", 0, 0, 0)
    section_size = 8 + len(fixed) + len(bank) + len(oam)
    section = b"KBEC" + struct.pack("<I", section_size) + fixed + bank + oam
    assert len(section) == section_size
    return nitro_file(b"RECN", [section])


def make_nanr() -> bytes:
    return nitro_file(b"RNAN", [b"KNBA" + struct.pack("<I", 8)])


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(renderer.PNG_SIGNATURE)
    return struct.unpack_from(">II", data, 16)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        catalog = root / "graphics_catalog"
        payloads = catalog / "payloads"
        output = root / "previews"
        payloads.mkdir(parents=True)
        fixtures = {
            "acf:0001": ("NCLR", "pal.nclr", make_nclr()),
            "acf:0002": ("NCGR", "gfx.ncgr", make_ncgr()),
            "acf:0003": ("NSCR", "map.nscr", make_nscr()),
            "acf:0004": ("NCER", "cell.ncer", make_ncer()),
            "acf:0005": ("NANR", "anim.nanr", make_nanr()),
        }
        rows = []
        for logical_path, (kind, name, data) in fixtures.items():
            destination = payloads / name
            destination.write_bytes(data)
            rows.append({
                "logical_path": logical_path,
                "parent_path": "",
                "depth": "1",
                "parent_container": "ACF",
                "entry_index": logical_path[-4:],
                "state": "acf-raw",
                "kind": kind,
                "size": str(len(data)),
                "sha256": "synthetic",
                "payload_path": f"payloads/{name}",
            })
        with (catalog / "resources.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with (catalog / "adjacent_runs.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "run_id", "parent_path", "start_index", "end_index", "resource_count", "NCGR", "NCLR",
                "NSCR", "NCER", "NANR", "resource_paths", "fact", "semantic_pairing_proven",
            ])
            writer.writeheader()
            writer.writerow({
                "run_id": "G00001", "parent_path": "", "start_index": 1, "end_index": 5,
                "resource_count": 5, "NCGR": 1, "NCLR": 1, "NSCR": 1, "NCER": 1, "NANR": 1,
                "resource_paths": " ".join(fixtures), "fact": "maximal_contiguous_graphics_run",
                "semantic_pairing_proven": "False",
            })

        summary = renderer.render_catalog(catalog, output, metadata_only=False, max_pixels=100000)
        assert summary["resources_inspected"] == 5
        assert summary["resources_parsed"] == 5
        assert summary["resource_parse_errors"] == 0
        assert summary["atomic_previews_written"] == 2
        assert summary["candidate_previews"] == {"background": 1, "cell_bank": 1, "sheet": 1}
        assert summary["semantic_pairings_claimed"] == 0

        assert png_dimensions(output / "atomic/palettes/pal.png") == (160, 20)
        assert png_dimensions(output / "atomic/indices/gfx.png") == (16, 8)
        assert png_dimensions(output / "candidates/sheets/G00001.png") == (16, 8)
        assert png_dimensions(output / "candidates/backgrounds/G00001.png") == (16, 8)
        assert png_dimensions(output / "candidates/cells/G00001__bank_0000.png") == (8, 8)

        inspection = list(csv.DictReader((output / "resource_inspection.csv").open(encoding="utf-8")))
        assert all(row["parse_status"] == "ok" for row in inspection)
        candidates = list(csv.DictReader((output / "candidate_previews.csv").open(encoding="utf-8")))
        assert len(candidates) == 3
        assert all(row["semantic_pairing_proven"] == "False" for row in candidates)
        assert not list(csv.DictReader((output / "unresolved.csv").open(encoding="utf-8")))

        metadata_output = root / "metadata"
        metadata = renderer.render_catalog(catalog, metadata_output, metadata_only=True, max_pixels=100000)
        assert metadata["resources_parsed"] == 5
        assert metadata["atomic_previews_written"] == 0
        assert not list(metadata_output.rglob("*.png"))

        try:
            renderer.parse_ncgr(b"RGCN")
        except renderer.NitroFormatError:
            pass
        else:
            raise AssertionError("truncated NCGR was accepted")

    print("Nitro graphics preview renderer synthetic test passed")


if __name__ == "__main__":
    main()
