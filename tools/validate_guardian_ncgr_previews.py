#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import render_guardian_graphics as guardian
import render_guardian_graphics_safe as safe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode every Guardian Signs NCGR preview in memory without writing PNG files."
    )
    parser.add_argument("catalog_dir", type=Path)
    args = parser.parse_args()

    safe.install_safe_extents()
    guardian.install_compatibility()

    catalog_dir = args.catalog_dir.resolve()
    with (catalog_dir / "resources.csv").open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    checked = 0
    failures: list[tuple[str, str]] = []
    for row in rows:
        if row["kind"] != "NCGR":
            continue
        checked += 1
        try:
            payload = (catalog_dir / row["payload_path"]).read_bytes()
            ncgr = guardian.parse_ncgr(payload)
            guardian.ncgr_atomic_image(ncgr)
        except Exception as exc:
            failures.append((row["logical_path"], str(exc)))

    if failures:
        print(f"Guardian NCGR preview validation failures: {len(failures)}")
        for logical_path, error in failures[:25]:
            print(f"  {logical_path}: {error}")
        raise SystemExit(1)

    print(f"Guardian NCGR previews decoded in memory: {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
