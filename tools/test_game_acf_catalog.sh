#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
temp_dir="$(mktemp -d)" # Keep all extracted game content in a disposable workspace.
workspace="$temp_dir/game_acf" # Use the same layout as the user-facing extraction workflow.
trap 'rm -rf "$temp_dir"' EXIT # Remove extracted proprietary data and reports after the test.

bash "$root_dir/tools/extract_game_data.sh" "" "$workspace" # Reconstruct FAT file 0x22, extract the ACF, and build reports.

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

if source_acf.read_bytes()[:4] != b"acf\0":
    raise SystemExit("reconstructed data_game_us.acf has the wrong signature")
if source_acf.read_bytes() != original_acf.read_bytes():
    raise SystemExit("preserved original.acf differs from the reconstructed source")

filelist = json.loads(filelist_path.read_text(encoding="utf-8"))
summary = json.loads(summary_path.read_text(encoding="utf-8"))
with catalog_path.open("r", encoding="utf-8", newline="") as source:
    catalog_rows = list(csv.DictReader(source))
with clusters_path.open("r", encoding="utf-8", newline="") as source:
    cluster_rows = list(csv.DictReader(source))

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

print(f"game ACF entries: {summary['archive_entries']} total, {real_entries} real")
print(f"game ACF bytes: {summary['total_real_bytes']}")
print(f"recognized: {summary['recognized_entries']}; unknown: {summary['unknown_entries']}")
print(f"unknown multi-entry clusters: {len(cluster_rows)}")
for label, count in list(summary["formats"].items())[:16]:
    print(f"format {label}: {count}")
print("Guardian Signs game ACF catalogue test passed")
PY
