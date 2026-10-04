#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import edit_ncer_sprite as editor


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    payloads = root / "work/game_acf/graphics_catalog/payloads"
    ncgr = payloads / "acf_2140__acf_0002.ncgr"
    nclr = payloads / "acf_2140__acf_0001.nclr"
    ncer = payloads / "acf_2140__acf_0003.ncer"
    for path in (ncgr, nclr, ncer):
        if not path.is_file():
            raise SystemExit(f"missing identified G00583 source payload: {path}")

    with tempfile.TemporaryDirectory() as temp:
        workspace = Path(temp) / "G00583_bank_0001"
        manifest = editor.export_project(ncgr, nclr, ncer, 1, workspace)
        if manifest["piece_count"] != 6:
            raise SystemExit(f"G00583 bank 1 piece count changed: {manifest['piece_count']}")
        if not (workspace / "reference_bank_0001.png").is_file():
            raise SystemExit("G00583 reference PNG was not generated")
        piece_files = sorted((workspace / "pieces").glob("*.png"))
        if len(piece_files) != 6:
            raise SystemExit(f"G00583 export wrote {len(piece_files)} piece PNGs instead of 6")

        parsed_manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
        if parsed_manifest["bank_index"] != 1:
            raise SystemExit("G00583 manifest bank index changed")

        rebuilt = Path(temp) / "roundtrip.ncgr"
        editor.import_project(
            ncgr, nclr, ncer, workspace, rebuilt, expect_identical=True
        )
        if rebuilt.read_bytes() != ncgr.read_bytes():
            raise SystemExit("G00583 NCGR round-trip is not byte-identical")

    print("G00583 bank 1 editable NCGR round-trip passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
