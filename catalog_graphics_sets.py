#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path


def find_repo_root() -> Path:
    candidates: list[Path] = []

    try:
        candidates.append(Path.cwd().resolve())
    except OSError:
        pass

    try:
        candidates.append(Path(__file__).resolve().parent)
    except OSError:
        pass

    checked: set[Path] = set()

    for start in candidates:
        for candidate in (start, *start.parents):
            if candidate in checked:
                continue

            checked.add(candidate)

            if (
                (candidate / "tools" / "catalog_game_acf.py").is_file()
                and
                (candidate / "tools" / "inventory_recursive_containers.py").is_file()
            ):
                return candidate

    searched = "\n".join(f"  - {path}" for path in checked)

    raise SystemExit(
        "Could not locate the Pokengineering repository root.\n\n"
        "The repository root must contain:\n"
        "  tools/catalog_game_acf.py\n"
        "  tools/inventory_recursive_containers.py\n\n"
        "Run this script from somewhere inside the Pokengineering checkout.\n\n"
        f"Searched:\n{searched}"
    )


ROOT = find_repo_root()
TOOLS = ROOT / "tools"

WORKSPACE = ROOT / "work" / "game_acf"
ARCHIVE = WORKSPACE / "archive"
ANALYSIS = WORKSPACE / "analysis"

OUTPUT = WORKSPACE / "graphics_catalog"
PAYLOADS = OUTPUT / "payloads"

MAX_DEPTH = 64


sys.path.insert(0, str(TOOLS))


try:
    from catalog_game_acf import identify_format, load_filelist, parse_index

    from inventory_recursive_containers import (
        ContainerFormatError,
        decompress_lz10,
        inspect_payload,
        parse_acf,
        parse_narc,
        plausible_lz10_header,
    )
except ImportError as error:
    raise SystemExit(
        "Located the Pokengineering repo at:\n"
        f"  {ROOT}\n\n"
        "but could not import its existing analysis tools.\n"
        f"Python module path added:\n  {TOOLS}\n\n"
        f"Import failed: {error}"
    ) from error


MAGICS = {
    b"RGCN": ("NCGR", ".ncgr"),
    b"RLCN": ("NCLR", ".nclr"),
    b"RCSN": ("NSCR", ".nscr"),
    b"RECN": ("NCER", ".ncer"),
    b"RNAN": ("NANR", ".nanr"),
}


LABEL_TO_KIND = {
    "NCGR graphics": "NCGR",
    "NCLR palette": "NCLR",
    "NSCR screen": "NSCR",
    "NCER cell": "NCER",
    "NANR animation": "NANR",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(path: str) -> str:
    return path.replace("/", "__").replace(":", "_")


def write_csv(
    path: Path,
    rows: list[dict],
    fields: list[str],
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(rows)


def unwrap_graphics(
    data: bytes,
):
    current = data
    seen = set()

    for _ in range(8):
        current_hash = digest(current)

        if current_hash in seen:
            fail(
                "Decode cycle while unwrapping a graphics resource."
            )

        seen.add(current_hash)

        if current[:4] in MAGICS:
            kind, extension = MAGICS[current[:4]]

            return (
                kind,
                extension,
                current,
            )

        label, offset = identify_format(current)

        if (
            label == "Nintendo LZ10"
            or plausible_lz10_header(current)
        ):
            try:
                current = decompress_lz10(current)
            except ContainerFormatError:
                return None

            continue

        if (
            label.startswith("embedded ")
            and offset is not None
            and offset > 0
        ):
            embedded_magic = current[
                offset : offset + 4
            ]

            if embedded_magic in MAGICS:
                kind, extension = MAGICS[
                    embedded_magic
                ]

                return (
                    kind,
                    extension,
                    current[offset:],
                )

        return None

    fail(
        "More than 8 nested wrapper/compression "
        "layers encountered."
    )


def load_expected():
    catalog_path = (
        ANALYSIS / "recursive_catalog.csv"
    )

    summary_path = (
        ANALYSIS / "recursive_summary.json"
    )

    if (
        not catalog_path.is_file()
        or not summary_path.is_file()
    ):
        fail(
            "The recursive inventory is missing.\n"
            f"Expected:\n  {catalog_path}\n  {summary_path}\n\n"
            "Run tools/extract_game_data.sh first."
        )

    summary = json.loads(
        summary_path.read_text(
            encoding="utf-8",
        )
    )

    for key in (
        "container_parse_errors",
        "cycle_stops",
        "max_depth_stops",
    ):
        value = int(
            summary.get(
                key,
                -1,
            )
        )

        if value != 0:
            fail(
                "recursive_summary.json is not clean: "
                f"{key}={value}"
            )

    with catalog_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(
            csv.DictReader(file)
        )

    all_paths = [
        row["logical_path"]
        for row in rows
    ]

    if len(all_paths) != len(set(all_paths)):
        fail(
            "recursive_catalog.csv contains "
            "duplicate logical paths."
        )

    expected_graphics = {
        row["logical_path"]:
        LABEL_TO_KIND[row["effective_format"]]

        for row in rows

        if row["effective_format"]
        in LABEL_TO_KIND
    }

    return (
        set(all_paths),
        expected_graphics,
    )


def walk_archive():
    filelist_path = (
        ARCHIVE / "filelist.json"
    )

    if not filelist_path.is_file():
        fail(
            f"Missing {filelist_path}\n"
            "Run tools/extract_game_data.sh first."
        )

    entries = []
    resources = []

    top_level = load_filelist(
        filelist_path
    )

    def walk(
        index: int,
        state: str,
        data: bytes | None,
        parent_path: str,
        parent_container: str,
        depth: int,
        ancestors=frozenset(),
    ):
        segment = (
            f"{parent_container.lower()}:"
            f"{index:04d}"
        )

        logical_path = (
            f"{parent_path}/{segment}"
            if parent_path
            else segment
        )

        entry = {
            "logical_path": logical_path,
            "parent_path": parent_path,
            "depth": depth,
            "parent_container": parent_container,
            "entry_index": index,
            "state": state,
        }

        entries.append(entry)

        if data is None:
            return

        graphics = unwrap_graphics(data)

        if graphics is not None:
            (
                kind,
                extension,
                payload,
            ) = graphics

            payload_path = (
                PAYLOADS
                / (
                    safe_name(logical_path)
                    + extension
                )
            )

            payload_path.write_bytes(
                payload
            )

            resources.append(
                {
                    **entry,
                    "kind": kind,
                    "size": len(payload),
                    "sha256": digest(payload),
                    "payload_path": str(
                        payload_path.relative_to(
                            ROOT
                        )
                    ),
                }
            )

        inspection = inspect_payload(
            data
        )

        if (
            not inspection.container_kind
            or inspection.container_data
            is None
        ):
            return

        if depth >= MAX_DEPTH:
            fail(
                "Maximum recursion depth "
                f"reached at {logical_path}"
            )

        container_hash = digest(
            inspection.container_data
        )

        if container_hash in ancestors:
            fail(
                "Container cycle detected at "
                f"{logical_path}"
            )

        try:
            if (
                inspection.container_kind
                == "ACF"
            ):
                children = parse_acf(
                    inspection.container_data
                )
            else:
                children = parse_narc(
                    inspection.container_data
                )

        except ContainerFormatError as error:
            fail(
                "Container parse failed at "
                f"{logical_path}: {error}"
            )

        next_ancestors = (
            ancestors
            | {container_hash}
        )

        for child in children:
            walk(
                child.index,
                child.state,
                child.data,
                logical_path,
                inspection.container_kind,
                depth + 1,
                next_ancestors,
            )

    indexed = []

    for (
        filename,
        compressed,
    ) in top_level.items():
        index = parse_index(
            filename
        )

        if index is None:
            fail(
                "Top-level ACF filename "
                "has no stable index: "
                f"{filename}"
            )

        indexed.append(
            (
                index,
                filename,
                compressed,
            )
        )

    for (
        index,
        filename,
        compressed,
    ) in sorted(indexed):
        if compressed is None:
            walk(
                index,
                "unused",
                None,
                "",
                "ACF",
                1,
            )

            continue

        path = (
            ARCHIVE / filename
        )

        if not path.is_file():
            fail(
                "Missing extracted entry: "
                f"{path}"
            )

        walk(
            index,
            (
                "acf-compressed"
                if compressed
                else "acf-raw"
            ),
            path.read_bytes(),
            "",
            "ACF",
            1,
        )

    entries.sort(
        key=lambda row:
        row["logical_path"]
    )

    resources.sort(
        key=lambda row:
        row["logical_path"]
    )

    return (
        entries,
        resources,
    )


def parent_groups(
    resources,
):
    grouped = defaultdict(list)

    for resource in resources:
        grouped[
            resource["parent_path"]
        ].append(
            resource
        )

    rows = []

    for (
        parent,
        members,
    ) in grouped.items():
        members.sort(
            key=lambda row:
            row["entry_index"]
        )

        counts = Counter(
            row["kind"]
            for row in members
        )

        rows.append(
            {
                "parent_path": parent,
                "resource_count": len(
                    members
                ),
                "NCGR": counts["NCGR"],
                "NCLR": counts["NCLR"],
                "NSCR": counts["NSCR"],
                "NCER": counts["NCER"],
                "NANR": counts["NANR"],
                "first_index": members[
                    0
                ]["entry_index"],
                "last_index": members[
                    -1
                ]["entry_index"],
                "resource_paths": " ".join(
                    row["logical_path"]
                    for row in members
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            -row["resource_count"],
            row["parent_path"],
        ),
    )


def same_parent_pairs(
    resources,
):
    grouped = defaultdict(list)

    for resource in resources:
        grouped[
            resource["parent_path"]
        ].append(
            resource
        )

    rows = []

    for (
        parent,
        members,
    ) in sorted(
        grouped.items()
    ):
        members.sort(
            key=lambda row:
            row["entry_index"]
        )

        for (
            left_position,
            left,
        ) in enumerate(
            members
        ):
            for right in members[
                left_position + 1 :
            ]:
                if (
                    left["kind"]
                    == right["kind"]
                ):
                    continue

                rows.append(
                    {
                        "parent_path": parent,
                        "left_path":
                            left[
                                "logical_path"
                            ],
                        "left_kind":
                            left["kind"],
                        "left_index":
                            left[
                                "entry_index"
                            ],
                        "right_path":
                            right[
                                "logical_path"
                            ],
                        "right_kind":
                            right["kind"],
                        "right_index":
                            right[
                                "entry_index"
                            ],
                        "index_distance":
                            right[
                                "entry_index"
                            ]
                            - left[
                                "entry_index"
                            ],
                        "fact":
                            "same_parent_container",
                        "semantic_pairing_proven":
                            False,
                    }
                )

    return rows


def adjacent_runs(
    entries,
    resources,
):
    resource_map = {
        row["logical_path"]: row
        for row in resources
    }

    grouped = defaultdict(list)

    for entry in entries:
        grouped[
            entry["parent_path"]
        ].append(
            entry
        )

    rows = []
    run_id = 0

    for (
        parent,
        members,
    ) in sorted(
        grouped.items()
    ):
        members.sort(
            key=lambda row:
            row["entry_index"]
        )

        run = []

        def flush():
            nonlocal run_id
            nonlocal run

            if not run:
                return

            run_id += 1

            counts = Counter(
                resource_map[
                    row["logical_path"]
                ]["kind"]

                for row in run
            )

            rows.append(
                {
                    "run_id":
                        f"G{run_id:05d}",
                    "parent_path":
                        parent,
                    "start_index":
                        run[0][
                            "entry_index"
                        ],
                    "end_index":
                        run[-1][
                            "entry_index"
                        ],
                    "resource_count":
                        len(run),
                    "NCGR":
                        counts["NCGR"],
                    "NCLR":
                        counts["NCLR"],
                    "NSCR":
                        counts["NSCR"],
                    "NCER":
                        counts["NCER"],
                    "NANR":
                        counts["NANR"],
                    "resource_paths":
                        " ".join(
                            row[
                                "logical_path"
                            ]
                            for row in run
                        ),
                    "fact":
                        (
                            "maximal_contiguous_"
                            "graphics_run"
                        ),
                    "semantic_pairing_proven":
                        False,
                }
            )

            run = []

        previous_index = None

        for member in members:
            path = member[
                "logical_path"
            ]

            index = member[
                "entry_index"
            ]

            is_graphics = (
                path
                in resource_map
            )

            contiguous = (
                previous_index
                is not None
                and index
                == previous_index + 1
            )

            if is_graphics:
                if (
                    run
                    and not contiguous
                ):
                    flush()

                run.append(
                    member
                )

            else:
                flush()

            previous_index = (
                index
            )

        flush()

    return sorted(
        rows,
        key=lambda row: (
            -row["resource_count"],
            row["parent_path"],
            row["start_index"],
        ),
    )


def main():
    print(f"Repository root: {ROOT}")

    (
        expected_paths,
        expected_graphics,
    ) = load_expected()

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    if PAYLOADS.exists():
        shutil.rmtree(
            PAYLOADS
        )

    PAYLOADS.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        entries,
        resources,
    ) = walk_archive()

    actual_paths = {
        row["logical_path"]
        for row in entries
    }

    if actual_paths != expected_paths:
        missing = sorted(
            expected_paths
            - actual_paths
        )

        extra = sorted(
            actual_paths
            - expected_paths
        )

        fail(
            "Fresh traversal does not "
            "exactly match "
            "recursive_catalog.csv.\n"
            f"Missing: {len(missing)} "
            f"{missing[:5]}\n"
            f"Extra:   {len(extra)} "
            f"{extra[:5]}"
        )

    actual_graphics = {
        row["logical_path"]:
        row["kind"]

        for row in resources
    }

    if (
        actual_graphics
        != expected_graphics
    ):
        missing = sorted(
            set(expected_graphics)
            - set(actual_graphics)
        )

        extra = sorted(
            set(actual_graphics)
            - set(expected_graphics)
        )

        wrong = sorted(
            path

            for path in (
                set(actual_graphics)
                & set(expected_graphics)
            )

            if (
                actual_graphics[path]
                != expected_graphics[path]
            )
        )

        fail(
            "Graphics export does not "
            "exactly match the recursive "
            "inventory.\n"
            f"Missing: {len(missing)} "
            f"{missing[:5]}\n"
            f"Extra:   {len(extra)} "
            f"{extra[:5]}\n"
            f"Wrong kind: {len(wrong)} "
            f"{wrong[:5]}"
        )

    groups = parent_groups(
        resources
    )

    pairs = same_parent_pairs(
        resources
    )

    runs = adjacent_runs(
        entries,
        resources,
    )

    write_csv(
        OUTPUT / "resources.csv",
        resources,
        [
            "logical_path",
            "parent_path",
            "depth",
            "parent_container",
            "entry_index",
            "state",
            "kind",
            "size",
            "sha256",
            "payload_path",
        ],
    )

    write_csv(
        OUTPUT / "parent_groups.csv",
        groups,
        [
            "parent_path",
            "resource_count",
            "NCGR",
            "NCLR",
            "NSCR",
            "NCER",
            "NANR",
            "first_index",
            "last_index",
            "resource_paths",
        ],
    )

    write_csv(
        OUTPUT
        / "same_parent_pairs.csv",
        pairs,
        [
            "parent_path",
            "left_path",
            "left_kind",
            "left_index",
            "right_path",
            "right_kind",
            "right_index",
            "index_distance",
            "fact",
            "semantic_pairing_proven",
        ],
    )

    write_csv(
        OUTPUT
        / "adjacent_runs.csv",
        runs,
        [
            "run_id",
            "parent_path",
            "start_index",
            "end_index",
            "resource_count",
            "NCGR",
            "NCLR",
            "NSCR",
            "NCER",
            "NANR",
            "resource_paths",
            "fact",
            "semantic_pairing_proven",
        ],
    )

    counts = Counter(
        row["kind"]
        for row in resources
    )

    summary = {
        "recursive_paths_verified":
            len(actual_paths),
        "graphics_resources_exported":
            len(resources),
        "graphics_formats":
            dict(
                sorted(
                    counts.items()
                )
            ),
        "parent_groups":
            len(groups),
        "same_parent_cross_format_pairs":
            len(pairs),
        "adjacent_graphics_runs":
            len(runs),
        "semantic_pairings_claimed":
            0,
        "verification": {
            "recursive_catalog_exact_path_match":
                True,
            "graphics_set_exact_match":
                True,
            "container_parse_errors":
                0,
            "cycle_stops":
                0,
            "max_depth_stops":
                0,
        },
    }

    (
        OUTPUT / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("PASS")

    print(
        "Recursive paths verified:       "
        f"{len(actual_paths)}"
    )

    print(
        "Graphics resources exported:   "
        f"{len(resources)}"
    )

    for kind in (
        "NCGR",
        "NCLR",
        "NSCR",
        "NCER",
        "NANR",
    ):
        print(
            f"  {kind}: "
            f"{counts[kind]}"
        )

    print(
        "Parent groups:                  "
        f"{len(groups)}"
    )

    print(
        "Same-parent cross-format pairs: "
        f"{len(pairs)}"
    )

    print(
        "Adjacent graphics runs:         "
        f"{len(runs)}"
    )

    print(
        f"Output: {OUTPUT}"
    )

    print(
        "Semantic pairings guessed:      0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
