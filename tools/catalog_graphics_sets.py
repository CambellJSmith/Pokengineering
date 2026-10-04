#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Final

from catalog_game_acf import load_filelist, parse_index
from inventory_recursive_containers import ContainerFormatError, inspect_payload, parse_acf, parse_narc

GRAPHICS_FORMATS: Final[dict[str, tuple[str, str, bytes]]] = {
    "NCGR graphics": ("NCGR", ".ncgr", b"RGCN"),
    "NCLR palette": ("NCLR", ".nclr", b"RLCN"),
    "NSCR screen": ("NSCR", ".nscr", b"RCSN"),
    "NCER cell": ("NCER", ".ncer", b"RECN"),
    "NANR animation": ("NANR", ".nanr", b"RNAN"),
}
DEFAULT_MAX_DEPTH: Final[int] = 64


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(logical_path: str) -> str:
    return logical_path.replace("/", "__").replace(":", "_")


def load_recursive_inventory(catalog_path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    summary_path = catalog_path.with_name("recursive_summary.json")
    if not catalog_path.is_file():
        raise FileNotFoundError(f"missing recursive catalogue: {catalog_path}")
    if not summary_path.is_file():
        raise FileNotFoundError(f"missing recursive summary: {summary_path}")

    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    for key in ("container_parse_errors", "cycle_stops", "max_depth_stops"):
        if int(summary.get(key, -1)) != 0:
            raise ValueError(f"recursive inventory is not clean: {key}={summary.get(key)}")

    with catalog_path.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    paths = [row["logical_path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise ValueError("recursive catalogue contains duplicate logical paths")
    return rows, {row["logical_path"]: row["sha256"] for row in rows if row["state"] != "unused"}


def walk_payloads(archive_dir: Path, max_depth: int = DEFAULT_MAX_DEPTH) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    filelist_path = archive_dir / "filelist.json"
    if not filelist_path.is_file():
        raise FileNotFoundError(f"missing acftool metadata: {filelist_path}")
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")

    entries = load_filelist(filelist_path)
    traversed: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}

    def walk(
        *,
        index: int,
        state: str,
        data: bytes | None,
        parent_path: str,
        parent_container: str,
        depth: int,
        ancestors: frozenset[str] = frozenset(),
    ) -> None:
        segment = f"{parent_container.lower()}:{index:04d}"
        logical_path = f"{parent_path}/{segment}" if parent_path else segment
        traversed.append(
            {
                "logical_path": logical_path,
                "parent_path": parent_path,
                "depth": depth,
                "parent_container": parent_container,
                "entry_index": index,
                "state": state,
            }
        )
        if data is None:
            return

        payloads[logical_path] = data
        inspection = inspect_payload(data)
        if not inspection.container_kind or inspection.container_data is None:
            return
        if depth >= max_depth:
            raise ValueError(f"maximum recursion depth reached at {logical_path}")

        container_digest = sha256_bytes(inspection.container_data)
        if container_digest in ancestors:
            raise ValueError(f"container cycle detected at {logical_path}")

        try:
            children = parse_acf(inspection.container_data) if inspection.container_kind == "ACF" else parse_narc(inspection.container_data)
        except ContainerFormatError as error:
            raise ValueError(f"container parse failed at {logical_path}: {error}") from error

        next_ancestors = ancestors | {container_digest}
        for child in children:
            walk(
                index=child.index,
                state=child.state,
                data=child.data,
                parent_path=logical_path,
                parent_container=inspection.container_kind,
                depth=depth + 1,
                ancestors=next_ancestors,
            )

    indexed: list[tuple[int, str, bool | None]] = []
    for filename, compressed in entries.items():
        index = parse_index(filename)
        if index is None:
            raise ValueError(f"top-level ACF filename has no stable four-digit index: {filename}")
        indexed.append((index, filename, compressed))

    for index, filename, compressed in sorted(indexed):
        if compressed is None:
            walk(index=index, state="unused", data=None, parent_path="", parent_container="ACF", depth=1)
            continue
        entry_path = archive_dir / filename
        if not entry_path.is_file():
            raise FileNotFoundError(f"missing extracted top-level ACF entry: {entry_path}")
        walk(
            index=index,
            state="acf-compressed" if compressed else "acf-raw",
            data=entry_path.read_bytes(),
            parent_path="",
            parent_container="ACF",
            depth=1,
        )

    return traversed, payloads


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parent_groups(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for resource in resources:
        grouped[str(resource["parent_path"])].append(resource)

    rows: list[dict[str, Any]] = []
    for parent_path, members in grouped.items():
        members.sort(key=lambda row: int(row["entry_index"]))
        counts = Counter(str(row["kind"]) for row in members)
        rows.append(
            {
                "parent_path": parent_path,
                "resource_count": len(members),
                "NCGR": counts["NCGR"],
                "NCLR": counts["NCLR"],
                "NSCR": counts["NSCR"],
                "NCER": counts["NCER"],
                "NANR": counts["NANR"],
                "first_index": members[0]["entry_index"],
                "last_index": members[-1]["entry_index"],
                "resource_paths": " ".join(str(row["logical_path"]) for row in members),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["resource_count"]), str(row["parent_path"])))


def build_adjacent_pairs(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for resource in resources:
        grouped[str(resource["parent_path"])].append(resource)

    rows: list[dict[str, Any]] = []
    for parent_path, members in sorted(grouped.items()):
        members.sort(key=lambda row: int(row["entry_index"]))
        for left, right in zip(members, members[1:]):
            if int(right["entry_index"]) != int(left["entry_index"]) + 1:
                continue
            rows.append(
                {
                    "parent_path": parent_path,
                    "left_path": left["logical_path"],
                    "left_kind": left["kind"],
                    "left_index": left["entry_index"],
                    "right_path": right["logical_path"],
                    "right_kind": right["kind"],
                    "right_index": right["entry_index"],
                    "index_distance": 1,
                    "fact": "adjacent_graphics_slots",
                    "semantic_pairing_proven": False,
                }
            )
    return rows


def build_adjacent_runs(traversed: list[dict[str, Any]], resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resource_map = {str(row["logical_path"]): row for row in resources}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in traversed:
        grouped[str(entry["parent_path"])].append(entry)

    rows: list[dict[str, Any]] = []
    run_id = 0
    for parent_path, members in sorted(grouped.items()):
        members.sort(key=lambda row: int(row["entry_index"]))
        run: list[dict[str, Any]] = []
        previous_index: int | None = None

        def flush() -> None:
            nonlocal run_id, run
            if not run:
                return
            run_id += 1
            counts = Counter(str(resource_map[str(row["logical_path"])]["kind"]) for row in run)
            rows.append(
                {
                    "run_id": f"G{run_id:05d}",
                    "parent_path": parent_path,
                    "start_index": run[0]["entry_index"],
                    "end_index": run[-1]["entry_index"],
                    "resource_count": len(run),
                    "NCGR": counts["NCGR"],
                    "NCLR": counts["NCLR"],
                    "NSCR": counts["NSCR"],
                    "NCER": counts["NCER"],
                    "NANR": counts["NANR"],
                    "resource_paths": " ".join(str(row["logical_path"]) for row in run),
                    "fact": "maximal_contiguous_graphics_run",
                    "semantic_pairing_proven": False,
                }
            )
            run = []

        for member in members:
            index = int(member["entry_index"])
            is_graphics = str(member["logical_path"]) in resource_map
            if is_graphics:
                if run and previous_index is not None and index != previous_index + 1:
                    flush()
                run.append(member)
            else:
                flush()
            previous_index = index
        flush()

    return sorted(rows, key=lambda row: (-int(row["resource_count"]), str(row["parent_path"]), int(row["start_index"])))


def build_graphics_catalog(
    archive_dir: Path,
    recursive_catalog_path: Path,
    output_dir: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict[str, Any]:
    archive_dir = archive_dir.resolve()
    recursive_catalog_path = recursive_catalog_path.resolve()
    output_dir = output_dir.resolve()
    expected_rows, expected_hashes = load_recursive_inventory(recursive_catalog_path)
    traversed, payloads = walk_payloads(archive_dir, max_depth)

    expected_paths = {row["logical_path"] for row in expected_rows}
    actual_paths = {str(row["logical_path"]) for row in traversed}
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)[:5]
        extra = sorted(actual_paths - expected_paths)[:5]
        raise ValueError(f"fresh traversal differs from recursive catalogue; missing={missing}; extra={extra}")

    for logical_path, expected_hash in expected_hashes.items():
        data = payloads.get(logical_path)
        if data is None:
            raise ValueError(f"recursive real entry has no traversed payload: {logical_path}")
        if sha256_bytes(data) != expected_hash:
            raise ValueError(f"payload hash differs from recursive catalogue: {logical_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    payload_dir = output_dir / "payloads"
    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    payload_dir.mkdir(parents=True)

    traversed_by_path = {str(row["logical_path"]): row for row in traversed}
    resources: list[dict[str, Any]] = []
    for expected in expected_rows:
        format_info = GRAPHICS_FORMATS.get(expected["effective_format"])
        if format_info is None:
            continue
        kind, extension, magic = format_info
        logical_path = expected["logical_path"]
        data = payloads[logical_path]
        if not data.startswith(magic):
            raise ValueError(f"{kind} entry has an unexpected header at {logical_path}")
        destination = payload_dir / f"{safe_name(logical_path)}{extension}"
        destination.write_bytes(data)
        source = traversed_by_path[logical_path]
        resources.append(
            {
                "logical_path": logical_path,
                "parent_path": source["parent_path"],
                "depth": source["depth"],
                "parent_container": source["parent_container"],
                "entry_index": source["entry_index"],
                "state": source["state"],
                "kind": kind,
                "size": len(data),
                "sha256": sha256_bytes(data),
                "payload_path": str(destination.relative_to(output_dir)),
            }
        )

    resources.sort(key=lambda row: str(row["logical_path"]))
    parent_groups = build_parent_groups(resources)
    adjacent_pairs = build_adjacent_pairs(resources)
    adjacent_runs = build_adjacent_runs(traversed, resources)

    write_csv(
        output_dir / "resources.csv",
        resources,
        ["logical_path", "parent_path", "depth", "parent_container", "entry_index", "state", "kind", "size", "sha256", "payload_path"],
    )
    write_csv(
        output_dir / "parent_groups.csv",
        parent_groups,
        ["parent_path", "resource_count", "NCGR", "NCLR", "NSCR", "NCER", "NANR", "first_index", "last_index", "resource_paths"],
    )
    write_csv(
        output_dir / "adjacent_pairs.csv",
        adjacent_pairs,
        ["parent_path", "left_path", "left_kind", "left_index", "right_path", "right_kind", "right_index", "index_distance", "fact", "semantic_pairing_proven"],
    )
    write_csv(
        output_dir / "adjacent_runs.csv",
        adjacent_runs,
        ["run_id", "parent_path", "start_index", "end_index", "resource_count", "NCGR", "NCLR", "NSCR", "NCER", "NANR", "resource_paths", "fact", "semantic_pairing_proven"],
    )

    counts = Counter(str(row["kind"]) for row in resources)
    summary: dict[str, Any] = {
        "recursive_paths_verified": len(actual_paths),
        "graphics_resources_exported": len(resources),
        "graphics_formats": dict(sorted(counts.items())),
        "parent_groups": len(parent_groups),
        "adjacent_graphics_pairs": len(adjacent_pairs),
        "adjacent_graphics_runs": len(adjacent_runs),
        "semantic_pairings_claimed": 0,
        "verification": {
            "recursive_catalog_exact_path_match": True,
            "payload_hashes_exact_match": True,
            "graphics_headers_validated": True,
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"verified recursive paths: {summary['recursive_paths_verified']}")
    print(f"exported graphics resources: {summary['graphics_resources_exported']}")
    for kind in ("NCGR", "NCLR", "NSCR", "NCER", "NANR"):
        print(f"graphics {kind}: {counts[kind]}")
    print(f"parent groups: {summary['parent_groups']}")
    print(f"adjacent graphics pairs: {summary['adjacent_graphics_pairs']}")
    print(f"adjacent graphics runs: {summary['adjacent_graphics_runs']}")
    print("semantic pairings guessed: 0")
    print(f"graphics catalogue: {output_dir}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Export and structurally group Guardian Signs 2D Nitro graphics resources.")
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("recursive_catalog", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    args = parser.parse_args()
    build_graphics_catalog(args.archive_dir, args.recursive_catalog, args.output_dir, args.max_depth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
