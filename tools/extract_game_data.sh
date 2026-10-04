#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
provided_acf="${1:-}" # Accept an explicitly supplied correctly extracted game ACF when provided.
workspace="${2:-$root_dir/work/game_acf}" # Keep generated analysis outside version control.
setup_tools="$root_dir/tools/setup_guardian_tools.sh" # Build pinned local dependencies automatically when they are absent.
acftool="$root_dir/tools/bin/acftool" # Use the pinned Guardian Signs ACF utility.
cataloguer="$root_dir/tools/catalog_game_acf.py" # Classify extracted archive entries.
recursive_inventory="$root_dir/tools/inventory_recursive_containers.py" # Recursively inspect nested ACF and NARC containers.
graphics_cataloguer="$root_dir/tools/catalog_graphics_sets.py" # Export and structurally group reachable 2D Nitro graphics resources.
nitrofs_extractor="$root_dir/tools/extract_nitrofs_file.py" # Recover the correctly aligned ACF directly from raw FAT data.
working_acf="$workspace/archive.acf" # Give acftool a stable basename so its output directory is predictable.
archive_dir="$workspace/archive" # acftool extracts archive.acf into this directory.
original_acf="$workspace/original.acf" # Preserve an untouched local copy of the correctly aligned archive.
reconstructed_acf="$workspace/source_data_game_us.acf" # Store the raw-FAT reconstruction for traceability.
analysis_dir="$workspace/analysis" # Store metadata-only reports separately from extracted proprietary payloads.
graphics_dir="$workspace/graphics_catalog" # Keep exported graphics payloads and deterministic grouping reports together.

require_file() { # Fail early when a required file is missing.
    [[ -f "$1" ]] || { printf 'missing required file: %s\n' "$1" >&2; exit 1; }
}

require_file "$setup_tools" # Confirm the reproducible dependency bootstrapper exists.
require_file "$cataloguer" # Confirm the top-level classifier exists.
require_file "$recursive_inventory" # Confirm the recursive container inventory exists.
require_file "$graphics_cataloguer" # Confirm the graphics catalogue tool exists.
require_file "$nitrofs_extractor" # Confirm the validated raw-FAT extractor exists.
command -v python3 >/dev/null 2>&1 || { printf 'missing required command: python3\n' >&2; exit 1; } # Require Python for extraction and analysis helpers.

if [[ ! -x "$acftool" ]]; then # Make a fresh checkout usable with one extraction command.
    printf 'acftool is not installed locally; building pinned Guardian Signs tools...\n' # Explain the one-time bootstrap before invoking it.
    bash "$setup_tools" # Clone, pin, build, and install acftool plus ra3mes into ignored local directories.
fi

[[ -x "$acftool" ]] || { printf 'failed to install required tool: %s\n' "$acftool" >&2; exit 1; } # Refuse to continue if bootstrap did not produce acftool.

if [[ -e "$workspace" ]] && [[ -n "$(find "$workspace" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then # Refuse to overwrite an existing analysis session.
    printf 'workspace is not empty: %s\nremove it or choose another workspace path\n' "$workspace" >&2
    exit 1
fi

mkdir -p "$workspace" "$analysis_dir" # Create the ignored local workspace.

if [[ -n "$provided_acf" ]]; then # Allow users with a known-good ACF to bypass FAT reconstruction.
    require_file "$provided_acf" # Confirm the supplied archive exists.
    source_acf="$provided_acf" # Analyze the explicit archive without modifying it.
else
    require_file "$root_dir/fat_data.bin" # Require the validated raw NitroFS payload.
    require_file "$root_dir/fat.bin" # Require the original Nintendo DS FAT table.
    require_file "$root_dir/_file_IDs.txt" # Require the FAT ID/path mapping.
    python3 "$nitrofs_extractor" "$root_dir/fat_data.bin" "$root_dir/fat.bin" "$root_dir/_file_IDs.txt" "data/data_game_us.acf" "$reconstructed_acf" # Reconstruct FAT file ID 0x22 at its correct absolute offsets.
    source_acf="$reconstructed_acf" # Use the validated reconstructed archive for extraction.
fi

python3 - "$source_acf" <<'PY' # Validate the ACF signature before invoking the external extractor.
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.read_bytes()[:4] != b"acf\0":
    raise SystemExit(f"game archive does not begin with acf\\0: {path}")
PY

cp -- "$source_acf" "$working_acf" # Work on a local copy so the source archive remains untouched.
"$acftool" --extract "$working_acf" # Extract and decompress all real ACF entries plus filelist.json.
mv -- "$working_acf" "$original_acf" # Preserve the exact source bytes after extraction completes.
python3 "$cataloguer" "$archive_dir" "$analysis_dir" # Generate top-level metadata, format classifications, and unknown clusters.
python3 "$recursive_inventory" "$archive_dir" "$analysis_dir" # Traverse nested ACF/NARC containers and classify every reachable child.
python3 "$graphics_cataloguer" "$archive_dir" "$analysis_dir/recursive_catalog.csv" "$graphics_dir" # Reverify the traversal and export all recognized 2D Nitro graphics resources.

printf 'game ACF workspace: %s\n' "$workspace" # Report the complete local analysis location.
printf 'extracted entries: %s\n' "$archive_dir" # Report where proprietary extracted files are stored locally.
printf 'resource catalogue: %s\n' "$analysis_dir/catalog.csv" # Report the primary top-level metadata table.
printf 'unknown clusters: %s\n' "$analysis_dir/unknown_clusters.csv" # Report the top-level unknown-format grouping table.
printf 'summary: %s\n' "$analysis_dir/summary.json" # Report the top-level machine-readable overview.
printf 'recursive catalogue: %s\n' "$analysis_dir/recursive_catalog.csv" # Report stable logical paths for recursively discovered resources.
printf 'recursive summary: %s\n' "$analysis_dir/recursive_summary.json" # Report recursive container and format totals.
printf 'graphics resources: %s\n' "$graphics_dir/resources.csv" # Report every exported graphics resource and stable logical path.
printf 'graphics parent groups: %s\n' "$graphics_dir/parent_groups.csv" # Report exact same-container graphics neighborhoods.
printf 'graphics adjacent pairs: %s\n' "$graphics_dir/adjacent_pairs.csv" # Report exact adjacent graphics slot edges without semantic guesses.
printf 'graphics adjacent runs: %s\n' "$graphics_dir/adjacent_runs.csv" # Report exact contiguous graphics runs without semantic guesses.
printf 'graphics summary: %s\n' "$graphics_dir/summary.json" # Report deterministic graphics totals and verification state.
