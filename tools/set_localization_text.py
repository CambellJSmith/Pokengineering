#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def parse_decimal(value: str, label: str, width: int) -> str: # Normalize numeric archive and string indexes to their on-disk key widths.
    try:
        number: int = int(value, 10)
    except ValueError as error:
        raise ValueError(f"{label} must be a decimal integer") from error

    if number < 0:
        raise ValueError(f"{label} must not be negative")
    return f"{number:0{width}d}"


def main() -> int: # Replace one MES string in an extracted localization workspace without touching other entries.
    if len(sys.argv) != 5:
        print("usage: set_localization_text.py <workspace> <file_index> <string_index> <text>", file=sys.stderr)
        return 2

    workspace: Path = Path(sys.argv[1]).resolve()
    file_index: str = parse_decimal(sys.argv[2], "file_index", 4)
    string_index: str = parse_decimal(sys.argv[3], "string_index", 3)
    replacement: str = sys.argv[4]
    json_path: Path = workspace / "json" / f"{file_index}.json"

    if not json_path.is_file():
        print(f"missing localization JSON: {json_path}", file=sys.stderr)
        return 1

    raw: Any = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
        print(f"unexpected ra3mes JSON structure: {json_path}", file=sys.stderr)
        return 1

    if string_index not in raw:
        print(f"string index {string_index} does not exist in {json_path.name}", file=sys.stderr)
        return 1

    raw[string_index] = replacement
    json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated localization entry {file_index}:{string_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
