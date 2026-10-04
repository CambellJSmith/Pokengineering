#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
temp_dir="$(mktemp -d)" # Keep all extracted game content in a disposable workspace.
workspace="$temp_dir/game_acf" # Use the same layout as the user-facing extraction workflow.
trap 'rm -rf "$temp_dir"' EXIT # Remove extracted proprietary data and reports after the test.

python3 "$root_dir/tools/test_recursive_container_inventory.py" # Validate recursive parsers against synthetic nested ACF/NARC data first.
bash "$root_dir/tools/extract_game_data.sh" "" "$workspace" # Reconstruct FAT file 0x22, extract the ACF, and build top-level and recursive reports.

python3 - "$workspace" <<'PY' # Verify catalogue integrity without printing or persisting game payloads.
import csv
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
source_acf = workspace / "source_data_game_us.acf"
original_acf = workspace / "original.acf"
archive_dir = workspace / "archive"
analysis_dir = workspace / "analysis"
filelist_path = archive_dir / "filelist.json"
catalog_path = analysis_dir / "catalog.csv"
clusters_path = analysis_dir / "unknown_clusters.csv"
summary_path = analysis_dir / "summary.json"
recursive_catalog_path = analysis_dir / "recursive_catalog.csv"
recursive_summary_path = analysis_dir / "recursive_summary.json"

if source_acf.read_bytes()[:4] != b"acf\0":
    raise SystemExit("reconstructed data_game_us.acf has the wrong signature")
if source_acf.read_bytes() != original_acf.read_bytes():
    raise SystemExit("preserved original.acf differs from the reconstructed source")

filelist = json.loads(filelist_path.read_text(encoding="utf-8"))
summary = json.loads(summary_path.read_text(encoding="utf-8"))
recursive_summary = json.loads(recursive_summary_path.read_text(encoding="utf-8"))
with catalog_path.open("r", encoding="utf-8", newline="") as source:
    catalog_rows = list(csv.DictReader(source))
with clusters_path.open("r", encoding="utf-8", newline="") as source:
    cluster_rows = list(csv.DictReader(source))
with recursive_catalog_path.open("r", encoding="utf-8", newline="") as source:
    recursive_rows = list(csv.DictReader(source))

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
print("Guardian Signs game ACF recursive inventory test passed")
PY
