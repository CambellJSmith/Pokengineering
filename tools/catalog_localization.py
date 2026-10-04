#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str: # Calculate a stable content fingerprint without exposing file contents.
    digest: hashlib._Hash = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_filelist(path: Path) -> dict[str, bool | None]: # Load acftool's ordered archive metadata.
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("filelist.json must contain a JSON object")

    result: dict[str, bool | None] = {}
    for name, state in raw.items():
        if not isinstance(name, str) or state not in (True, False, None):
            raise ValueError("filelist.json contains an unsupported entry")
        result[name] = state
    return result


def count_strings(path: Path) -> int: # Count editable MES strings in a converted JSON file.
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return len(raw)


def parse_index(name: str) -> int | None: # Read acftool's four-digit archive entry prefix when present.
    prefix: str = name.split(".", 1)[0]
    return int(prefix) if len(prefix) == 4 and prefix.isdigit() else None


def compression_label(state: bool | None) -> str: # Convert acftool's tri-state metadata into a readable label.
    if state is None:
        return "unused"
    return "compressed" if state else "raw"


def main() -> int: # Produce a content-free catalogue of extracted localization resources.
    if len(sys.argv) != 4:
        print("usage: catalog_localization.py <archive_dir> <json_dir> <output_csv>", file=sys.stderr)
        return 2

    archive_dir: Path = Path(sys.argv[1]).resolve()
    json_dir: Path = Path(sys.argv[2]).resolve()
    output_csv: Path = Path(sys.argv[3]).resolve()
    filelist_path: Path = archive_dir / "filelist.json"

    if not filelist_path.is_file():
        print(f"missing acftool metadata: {filelist_path}", file=sys.stderr)
        return 1

    entries: dict[str, bool | None] = load_filelist(filelist_path)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with output_csv.open("w", encoding="utf-8", newline="") as destination:
        writer: csv.DictWriter[str] = csv.DictWriter(
            destination,
            fieldnames=["index", "filename", "state", "size", "sha256", "mes_json", "string_count"],
        )
        writer.writeheader()

        for name, state in entries.items():
            index: int | None = parse_index(name)
            entry_path: Path = archive_dir / name
            json_path: Path | None = json_dir / f"{index:04d}.json" if index is not None else None
            exists: bool = state is not None and entry_path.is_file()
            mes_json: bool = json_path is not None and json_path.is_file()

            writer.writerow(
                {
                    "index": "" if index is None else f"{index:04d}",
                    "filename": name,
                    "state": compression_label(state),
                    "size": entry_path.stat().st_size if exists else 0,
                    "sha256": sha256_file(entry_path) if exists else "",
                    "mes_json": "yes" if mes_json else "no",
                    "string_count": count_strings(json_path) if mes_json and json_path is not None else "",
                }
            )

    print(f"catalogued {len(entries)} archive entries to {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
