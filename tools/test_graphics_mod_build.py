#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

import build_graphics_mod as builder


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    registry_path = root / "docs/confirmed_graphics_assets.json"
    registry = builder.load_registry(registry_path)
    asset = builder.load_asset(registry, "G00583")
    builder.validate_asset_config("G00583", asset)

    if asset["status"] != "in_game_verified":
        raise SystemExit("G00583 is not recorded as in-game verified")
    if asset["preview_id"] != "G00583__bank_0001":
        raise SystemExit("G00583 preview ID changed unexpectedly")
    if int(asset["top_level_acf_index"]) != 2140 or int(asset["ncer_bank"]) != 1:
        raise SystemExit("G00583 container/bank mapping changed unexpectedly")

    resources_path = root / "work/game_acf/graphics_catalog/resources.csv"
    with resources_path.open("r", encoding="utf-8", newline="") as source:
        rows = {row["logical_path"]: row for row in csv.DictReader(source)}

    expected_kinds = {"nclr": "NCLR", "ncgr": "NCGR", "ncer": "NCER"}
    for key, kind in expected_kinds.items():
        record = asset[key]
        logical_path = str(record["logical_path"])
        row = rows.get(logical_path)
        if row is None:
            raise SystemExit(f"registry resource missing from graphics catalogue: {logical_path}")
        if row["kind"] != kind:
            raise SystemExit(f"{logical_path} is {row['kind']}, expected {kind}")
        if row["payload_path"] != Path(str(record["payload_path"])).relative_to("work/game_acf/graphics_catalog").as_posix():
            raise SystemExit(f"registry payload path disagrees with catalogue for {logical_path}")
        payload = root / str(record["payload_path"])
        if not payload.is_file():
            raise SystemExit(f"registry payload file is missing: {payload}")

    parent_filelist = root / "work/game_acf/archive/filelist.json"
    entry = builder.find_indexed_entry(parent_filelist, 2140)
    if entry != "2140.acf":
        raise SystemExit(f"top-level ACF slot 2140 resolved unexpectedly: {entry}")

    with tempfile.TemporaryDirectory() as temp:
        filelist = Path(temp) / "filelist.json"
        filelist.write_text(json.dumps({"0001.NCLR": True, "0002.NCGR": True}), encoding="utf-8")
        if builder.find_indexed_entry(filelist, 2) != "0002.NCGR":
            raise SystemExit("indexed ACF entry resolver failed synthetic lookup")

    print("confirmed graphics asset/build configuration test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
