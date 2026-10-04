#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
temp_dir="$(mktemp -d)" # Keep all extracted game content in a disposable workspace.
workspace="$temp_dir/game_acf" # Use the same layout as the user-facing extraction workflow.
trap 'rm -rf "$temp_dir"' EXIT # Remove extracted proprietary data and reports after the test.

python3 "$root_dir/tools/test_recursive_container_inventory.py" # Validate recursive parsers and graphics grouping against synthetic nested data first.
bash "$root_dir/tools/extract_game_data.sh" "" "$workspace" # Reconstruct FAT file 0x22, extract the ACF, and build all deterministic reports.

python3 - "$workspace" <<'PY' # Verify catalogue integrity without printing or persisting game payloads.
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

workspace = Path(sys.argv[1])
source_acf = workspace / "source_data_game_us.acf"
original_acf = workspace / "original.acf"
archive_dir = workspace / "archive"
analysis_dir = workspace / "analysis"
graphics_dir = workspace / "graphics_catalog"
filelist_path = archive_dir / "filelist.json"
catalog_path = analysis_dir / "catalog.csv"
clusters_path = analysis_dir / "unknown_clusters.csv"
summary_path = analysis_dir / "summary.json"
recursive_catalog_path = analysis_dir / "recursive_catalog.csv"
recursive_summary_path = analysis_dir / "recursive_summary.json"
graphics_resources_path = graphics_dir / "resources.csv"
graphics_summary_path = graphics_dir / "summary.json"
graphics_parent_groups_path = graphics_dir / "parent_groups.csv"
graphics_pairs_path = graphics_dir / "same_parent_pairs.csv"
graphics_runs_path = graphics_dir / "adjacent_runs.csv"

if source_acf.read_bytes()[:4] != b"acf\0":
    raise SystemExit("reconstructed data_game_us.acf has the wrong signature")
if source_acf.read_bytes() != original_acf.read_bytes():
    raise SystemExit("preserved original.acf differs from the reconstructed source")

filelist = json.loads(filelist_path.read_text(encoding="utf-8"))
summary = json.loads(summary_path.read_text(encoding="utf-8"))
recursive_summary = json.loads(recursive_summary_path.read_text(encoding="utf-8"))
graphics_summary = json.loads(graphics_summary_path.read_text(encoding="utf-8"))
with catalog_path.open("r", encoding="utf-8", newline="") as source:
    catalog_rows = list(csv.DictReader(source))
with clusters_path.open("r", encoding="utf-8", newline="") as source:
    cluster_rows = list(csv.DictReader(source))
with recursive_catalog_path.open("r", encoding="utf-8", newline="") as source:
    recursive_rows = list(csv.DictReader(source))
with graphics_resources_path.open("r", encoding="utf-8", newline="") as source:
    graphics_rows = list(csv.DictReader(source))
with graphics_parent_groups_path.open("r", encoding="utf-8", newline="") as source:
    graphics_parent_groups = list(csv.DictReader(source))
with graphics_pairs_path.open("r", encoding="utf-8", newline="") as source:
    graphics_pairs = list(csv.DictReader(source))
with graphics_runs_path.open("r", encoding="utf-8", newline="") as source:
    graphics_runs = list(csv.DictReader(source))

real_entries = sum(1 for state in filelist.values() if state is not None)
if len(catalog_rows) != len(filelist):
    raise SystemExit(f"catalogue row count {len(catalog_rows)} does not match filelist count {len(filelist)}")
if summary["archive_entries"] != len(filelist):
    raise SystemExit("summary archive entry count does not match filelist")
if summary["real_entries"] != real_entries or real_entries <= 0:
    raise SystemExit("summary real-entry count is invalid")
if summary["recognized_entries"] + summary["unknown_entries"] != real_entries:
    raise SystemExit("recognized/unknown counts do not cover all real entries")
if summary["total_real_bytes"] <= 0:
    raise SystemExit("summary reports no extracted game data")

required_columns = {
    "index", "filename", "state", "size", "sha256", "entropy", "printable_ratio",
    "first_16_hex", "ascii_magic", "detected_format", "magic_offset", "u16_le_0",
    "u32_le_0", "size_mod_4", "size_mod_16", "cluster_key",
}
if not catalog_rows or not required_columns.issubset(catalog_rows[0]):
    raise SystemExit("catalogue is missing required analysis columns")

recursive_required_columns = {
    "logical_path", "parent_path", "depth", "parent_container", "entry_index", "state",
    "size", "sha256", "first_16_hex", "detected_format", "magic_offset", "decoded_format",
    "decoded_size", "effective_format", "container_kind", "child_count", "parse_status",
    "entry_warning", "decode_error", "parse_error",
}
if not recursive_rows or not recursive_required_columns.issubset(recursive_rows[0]):
    raise SystemExit("recursive catalogue is missing required analysis columns")
if recursive_summary["top_level_slots"] != len(filelist):
    raise SystemExit("recursive summary top-level slot count does not match filelist")
if recursive_summary["top_level_real_entries"] != real_entries:
    raise SystemExit("recursive summary top-level real-entry count does not match filelist")
if recursive_summary["inventory_rows"] != len(recursive_rows):
    raise SystemExit("recursive summary row count does not match recursive catalogue")
if recursive_summary["inventory_rows"] <= len(filelist) or recursive_summary["real_entries"] <= real_entries:
    raise SystemExit("recursive inventory did not discover entries below the top-level ACF")
if recursive_summary["recognized_entries"] + recursive_summary["unknown_entries"] != recursive_summary["real_entries"]:
    raise SystemExit("recursive recognized/unknown counts do not cover all real entries")
if recursive_summary["max_depth"] < 2:
    raise SystemExit("recursive inventory never descended into a nested container")
if recursive_summary["container_parse_errors"] != 0:
    failures = [row for row in recursive_rows if row["parse_status"] == "error"][:5]
    raise SystemExit(f"recursive inventory has container parse errors: {failures}")
if recursive_summary["cycle_stops"] != 0 or recursive_summary["max_depth_stops"] != 0:
    raise SystemExit("recursive inventory stopped before traversing all reachable containers")
if recursive_summary["containers"] != recursive_summary["parsed_containers"]:
    raise SystemExit("not every detected ACF/NARC container was parsed")

paths = [row["logical_path"] for row in recursive_rows]
if len(paths) != len(set(paths)):
    raise SystemExit("recursive logical paths are not unique")
path_set = set(paths)
top_level_rows = [row for row in recursive_rows if row["depth"] == "1"]
if len(top_level_rows) != len(filelist):
    raise SystemExit("recursive catalogue does not preserve every top-level ACF slot")
for row in recursive_rows:
    if row["depth"] != "1" and row["parent_path"] not in path_set:
        raise SystemExit(f"recursive row has a missing parent path: {row['logical_path']}")

minimum_acf = summary["formats"].get("ACF archive", 0)
minimum_narc = summary["formats"].get("NARC archive", 0)
if recursive_summary["parsed_containers"].get("ACF", 0) < minimum_acf:
    raise SystemExit("recursive inventory parsed fewer ACF containers than the top-level catalogue exposes")
if recursive_summary["parsed_containers"].get("NARC", 0) < minimum_narc:
    raise SystemExit("recursive inventory parsed fewer NARC containers than the top-level catalogue exposes")

graphics_required_columns = {
    "logical_path", "parent_path", "depth", "parent_container", "entry_index", "state",
    "kind", "size", "sha256", "payload_path",
}
if not graphics_rows or not graphics_required_columns.issubset(graphics_rows[0]):
    raise SystemExit("graphics catalogue is missing required resource columns")
if graphics_summary["recursive_paths_verified"] != len(recursive_rows):
    raise SystemExit("graphics catalogue did not verify every recursive path")
if graphics_summary["graphics_resources_exported"] != len(graphics_rows):
    raise SystemExit("graphics summary resource count does not match resources.csv")
if graphics_summary["semantic_pairings_claimed"] != 0:
    raise SystemExit("graphics catalogue guessed semantic relationships")
verification = graphics_summary["verification"]
if not all(verification.get(key) is True for key in (
    "recursive_catalog_exact_path_match", "payload_hashes_exact_match", "graphics_headers_validated"
)):
    raise SystemExit("graphics catalogue verification state is incomplete")

format_to_kind = {
    "NCGR graphics": "NCGR",
    "NCLR palette": "NCLR",
    "NSCR screen": "NSCR",
    "NCER cell": "NCER",
    "NANR animation": "NANR",
}
expected_graphics_counts = {
    kind: recursive_summary["effective_formats"].get(label, 0)
    for label, kind in format_to_kind.items()
    if recursive_summary["effective_formats"].get(label, 0)
}
if graphics_summary["graphics_formats"] != expected_graphics_counts:
    raise SystemExit(
        f"graphics format counts do not exactly match recursive inventory: "
        f"{graphics_summary['graphics_formats']} != {expected_graphics_counts}"
    )
if len(graphics_rows) != sum(expected_graphics_counts.values()):
    raise SystemExit("graphics resources do not cover every recognized 2D Nitro graphics entry")

recursive_by_path = {row["logical_path"]: row for row in recursive_rows}
graphics_counts = Counter(row["kind"] for row in graphics_rows)
for row in graphics_rows:
    logical_path = row["logical_path"]
    recursive = recursive_by_path.get(logical_path)
    if recursive is None:
        raise SystemExit(f"graphics resource has no recursive source row: {logical_path}")
    if row["sha256"] != recursive["sha256"]:
        raise SystemExit(f"graphics resource hash differs from recursive source: {logical_path}")
    payload_path = graphics_dir / row["payload_path"]
    if not payload_path.is_file():
        raise SystemExit(f"graphics payload is missing: {payload_path}")
    payload_hash = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    if payload_hash != row["sha256"]:
        raise SystemExit(f"exported graphics payload hash is wrong: {logical_path}")

if graphics_summary["parent_groups"] != len(graphics_parent_groups):
    raise SystemExit("graphics parent-group summary count is wrong")
if graphics_summary["same_parent_cross_format_pairs"] != len(graphics_pairs):
    raise SystemExit("graphics same-parent pair summary count is wrong")
if graphics_summary["adjacent_graphics_runs"] != len(graphics_runs):
    raise SystemExit("graphics adjacent-run summary count is wrong")
if any(row["semantic_pairing_proven"].lower() != "false" for row in graphics_pairs + graphics_runs):
    raise SystemExit("a structural graphics relationship was incorrectly marked semantic")

print(f"game ACF entries: {summary['archive_entries']} total, {real_entries} real")
print(f"game ACF bytes: {summary['total_real_bytes']}")
print(f"top-level recognized: {summary['recognized_entries']}; unknown: {summary['unknown_entries']}")
print(f"unknown multi-entry clusters: {len(cluster_rows)}")
print(f"recursive rows: {recursive_summary['inventory_rows']} total, {recursive_summary['real_entries']} real")
print(f"recursive bytes: {recursive_summary['total_real_bytes']}")
print(f"recursive maximum depth: {recursive_summary['max_depth']}")
print(f"recursive ACF containers: {recursive_summary['parsed_containers'].get('ACF', 0)}")
print(f"recursive NARC containers: {recursive_summary['parsed_containers'].get('NARC', 0)}")
print(f"recursive LZ10 inner classifications: {recursive_summary['decoded_lz10_entries']}")
print(f"recursive recognized: {recursive_summary['recognized_entries']}; unknown: {recursive_summary['unknown_entries']}")
for label, count in list(recursive_summary["effective_formats"].items())[:16]:
    print(f"recursive format {label}: {count}")
print(f"graphics resources: {len(graphics_rows)}")
for kind in ("NCGR", "NCLR", "NSCR", "NCER", "NANR"):
    print(f"graphics format {kind}: {graphics_counts[kind]}")
print(f"graphics parent groups: {len(graphics_parent_groups)}")
print(f"graphics same-parent cross-format pairs: {len(graphics_pairs)}")
print(f"graphics adjacent runs: {len(graphics_runs)}")
print("Guardian Signs game ACF recursive inventory and graphics catalogue test passed")
PY
