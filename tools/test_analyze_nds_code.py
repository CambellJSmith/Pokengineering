#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import struct
import tempfile
from pathlib import Path

import analyze_nds_code as code


def put_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "root"
        output = Path(temp) / "out"
        root.mkdir()

        header = bytearray(0x200)
        header[:12] = b"CODE TEST\x00\x00\x00"
        header[12:16] = b"TEST"

        arm9_rom = 0x100
        arm9_ram = 0x02000000
        arm9_entry = arm9_ram
        arm9 = b"ARM9hello\x00CODE"
        arm7_rom = 0x25C
        arm7_ram = 0x03800000
        arm7_entry = arm7_ram
        arm7 = b"ARM7TEST"
        ovt_rom = 0x200
        ovt_size = 64
        overlay_data_start = ovt_rom + ovt_size

        put_u32(header, code.ARM9_ROM_OFFSET, arm9_rom)
        put_u32(header, code.ARM9_ENTRY, arm9_entry)
        put_u32(header, code.ARM9_RAM, arm9_ram)
        put_u32(header, code.ARM9_SIZE, len(arm9))
        put_u32(header, code.ARM7_ROM_OFFSET, arm7_rom)
        put_u32(header, code.ARM7_ENTRY, arm7_entry)
        put_u32(header, code.ARM7_RAM, arm7_ram)
        put_u32(header, code.ARM7_SIZE, len(arm7))
        put_u32(header, code.FAT_ROM_OFFSET, 0x300)
        put_u32(header, code.FAT_SIZE, 16)
        put_u32(header, code.ARM9_OVT_ROM_OFFSET, ovt_rom)
        put_u32(header, code.ARM9_OVT_SIZE, ovt_size)
        put_u32(header, code.ARM7_OVT_ROM_OFFSET, 0)
        put_u32(header, code.ARM7_OVT_SIZE, 0)

        overlay0_ram = 0x02001000
        overlay0 = struct.pack("<I", overlay0_ram + 9) + b"hello\x00ABCDEF"
        assert len(overlay0) == 16
        overlay1_ram = 0x02001008
        overlay1 = b"COMPRESSED!!"
        assert len(overlay1) == 12
        overlay_region = overlay0 + overlay1
        assert overlay_data_start + len(overlay_region) == arm7_rom

        fat = struct.pack(
            "<IIII",
            overlay_data_start,
            overlay_data_start + len(overlay0),
            overlay_data_start + len(overlay0),
            arm7_rom,
        )

        table = bytearray()
        table.extend(
            struct.pack(
                "<8I",
                0,
                overlay0_ram,
                len(overlay0),
                8,
                overlay0_ram,
                overlay0_ram + 4,
                0,
                len(overlay0),
            )
        )
        table.extend(
            struct.pack(
                "<8I",
                1,
                overlay1_ram,
                32,
                4,
                overlay1_ram,
                overlay1_ram,
                1,
                (1 << 24) | len(overlay1),
            )
        )

        (root / "header.bin").write_bytes(header)
        (root / "arm9.bin").write_bytes(arm9 + b"FOOTER")
        (root / "arm7.bin").write_bytes(arm7)
        (root / "fat.bin").write_bytes(fat)
        (root / "a9ovr.bin").write_bytes(table)
        (root / "a9ovr_data.bin").write_bytes(overlay_region)

        summary = code.analyze(root, output)
        assert summary["arm9_overlay_count"] == 2
        assert summary["compressed_arm9_overlays"] == 1
        assert summary["uncompressed_arm9_overlays"] == 1
        assert summary["overlay_static_initializer_entries"] == 1
        assert summary["overlay_ram_overlap_groups"] == [[0, 1]]
        assert summary["ghidra_importable_programs"] == 3  # ARM9, ARM7, uncompressed overlay 0.

        rows = list(csv.DictReader((output / "overlays.csv").open(encoding="utf-8")))
        assert len(rows) == 2
        assert rows[0]["overlay_id"] == "0"
        assert rows[0]["compressed"] == "False"
        assert rows[0]["static_initializer_count"] == "1"
        assert rows[1]["compressed"] == "True"
        assert rows[1]["overlaps_overlay_ids"] == "0"

        inits = list(csv.DictReader((output / "static_initializers.csv").open(encoding="utf-8")))
        assert len(inits) == 1
        assert inits[0]["target_address"] == f"0x{overlay0_ram + 8:08X}"
        assert inits[0]["instruction_set"] == "THUMB"
        assert inits[0]["inside_overlay_file_ram"] == "True"

        strings = list(csv.DictReader((output / "strings.csv").open(encoding="utf-8")))
        assert any(row["module"] == "arm9" and "hello" in row["text"] for row in strings)
        assert any(row["module"] == "overlay_000" and row["text"] == "hello" for row in strings)
        assert not any(row["module"] == "overlay_001" for row in strings)

        ghidra = list(csv.DictReader((output / "ghidra_targets.csv").open(encoding="utf-8")))
        assert ghidra[0]["program"] == "arm9"
        assert ghidra[2]["program"] == "overlay_000"
        assert ghidra[2]["importable"] == "True"
        assert ghidra[3]["program"] == "overlay_001"
        assert ghidra[3]["importable"] == "False"

        assert (output / "executables/arm9.bin").read_bytes() == arm9
        assert (output / "executables/overlays/overlay_000.raw.bin").read_bytes() == overlay0
        parsed = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert parsed["header"]["game_code"] == "TEST"

    print("Nintendo DS executable memory-map synthetic test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
