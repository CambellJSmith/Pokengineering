#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
provided_acf="${1:-}" # Accept an explicit correctly extracted localization ACF when supplied.
workspace="${2:-$root_dir/work/localization}" # Keep editable outputs in the ignored local workspace.
acftool="$root_dir/tools/bin/acftool" # Use the locally pinned ACF utility.
ra3mes="$root_dir/tools/bin/ra3mes" # Use the locally pinned Guardian Signs text converter.
cataloguer="$root_dir/tools/catalog_localization.py" # Build a metadata catalogue after extraction.
nitrofs_extractor="$root_dir/tools/extract_nitrofs_file.py" # Recover correctly aligned files directly from the raw FAT payload when needed.
editable_acf="$workspace/editable.acf" # Give acftool a temporary archive name that maps to the editable directory.
original_acf="$workspace/original.acf" # Preserve an untouched local copy for comparison and recovery.
reconstructed_acf="$workspace/source_data_localize_us.acf" # Store a correctly aligned ACF reconstructed from the repository's raw FAT inputs.
archive_dir="$workspace/editable" # acftool extracts editable.acf into this directory.
json_dir="$workspace/json" # Store human-editable MES JSON files separately from binary resources.
catalog_path="$workspace/catalog.csv" # Store non-content resource metadata for analysis.
mes_manifest="$workspace/mes_entries.txt" # Preserve the exact ACF filenames selected as Guardian Signs MES resources.
mes_count=275 # Guardian Signs retail localization archives contain 275 leading MES files.

require_file() { # Fail early when a required file is unavailable.
    [[ -f "$1" ]] || { printf 'missing required file: %s\n' "$1" >&2; exit 1; }
}

require_executable() { # Fail early when a required local tool has not been built.
    [[ -x "$1" ]] || { printf 'missing required tool: %s\nrun tools/setup_guardian_tools.sh first\n' "$1" >&2; exit 1; }
}

require_file "$cataloguer" # Confirm the catalogue script exists.
require_file "$nitrofs_extractor" # Confirm the validated NitroFS extraction helper exists.
require_executable "$acftool" # Confirm the ACF extractor/rebuilder is installed.
require_executable "$ra3mes" # Confirm the MES converter is installed.
command -v python3 >/dev/null 2>&1 || { printf 'missing required command: python3\n' >&2; exit 1; } # Require Python for FAT recovery and catalogue generation.

if [[ -e "$workspace" ]] && [[ -n "$(find "$workspace" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then # Refuse to overwrite an existing editing session.
    printf 'workspace is not empty: %s\nremove it or choose another workspace path\n' "$workspace" >&2
    exit 1
fi

mkdir -p "$workspace" "$json_dir" # Create the local editing workspace.

if [[ -n "$provided_acf" ]]; then # Prefer an explicitly supplied correctly extracted archive.
    require_file "$provided_acf" # Confirm the user-supplied localization archive exists.
    source_acf="$provided_acf" # Use the explicit source without modifying it.
else
    require_file "$root_dir/fat_data.bin" # Require the raw FAT payload needed to bypass the misaligned unpacked data directory.
    require_file "$root_dir/fat.bin" # Require the original Nintendo DS FAT table.
    require_file "$root_dir/_file_IDs.txt" # Require the file-ID/path mapping created during FAT unpacking.
    python3 "$nitrofs_extractor" "$root_dir/fat_data.bin" "$root_dir/fat.bin" "$root_dir/_file_IDs.txt" "data/data_localize_us.acf" "$reconstructed_acf" # Reconstruct the localization ACF at its validated FAT offsets.
    source_acf="$reconstructed_acf" # Use the validated reconstructed archive as the source.
fi

cp -- "$source_acf" "$editable_acf" # Copy the archive so extraction never alters the source file.
"$acftool" --extract "$editable_acf" # Extract and decompress all ACF entries plus filelist.json.
mv -- "$editable_acf" "$original_acf" # Preserve the untouched archive before any rebuild can replace editable.acf.

python3 - "$archive_dir/filelist.json" "$mes_manifest" "$mes_count" <<'PY' # Select the first 275 real archive files while skipping unused/dummy ACF entries.
import json
import sys
from pathlib import Path

filelist_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
required_count = int(sys.argv[3])
data = json.loads(filelist_path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit("filelist.json is not a JSON object")
entries = [name for name, state in data.items() if state is not None]
if len(entries) < required_count:
    raise SystemExit(f"localization ACF has only {len(entries)} real entries; expected at least {required_count}")
manifest_path.write_text("\n".join(entries[:required_count]) + "\n", encoding="utf-8")
PY

converted=0 # Track the number of MES files successfully converted to JSON.
while IFS= read -r entry_name; do # Convert the exact archive entries recorded in the generated MES manifest.
    [[ -n "$entry_name" ]] || continue # Ignore accidental blank manifest lines.
    entry_path="$archive_dir/$entry_name" # Resolve the extracted ACF payload by its exact filelist name.
    require_file "$entry_path" # Reject missing extracted resources before conversion.
    index="${entry_name%%.*}" # Keep the original four-digit ACF index as the editable JSON filename.
    "$ra3mes" --to-json "$entry_path" "$json_dir/$index.json" # Convert the MES payload into editable JSON.
    ((converted += 1)) # Record the successful conversion.
done < "$mes_manifest"

if (( converted != mes_count )); then # Require the documented retail localization MES count exactly.
    printf 'converted %d MES files; expected %d\n' "$converted" "$mes_count" >&2
    exit 1
fi

python3 "$cataloguer" "$archive_dir" "$json_dir" "$catalog_path" # Generate metadata for every ACF entry.
printf 'extracted %d Guardian Signs MES files\n' "$converted" # Report the completed text conversion count.
printf 'editable text: %s\n' "$json_dir" # Report where JSON text can be modified.
printf 'resource catalog: %s\n' "$catalog_path" # Report where archive metadata can be inspected.
printf 'untouched archive: %s\n' "$original_acf" # Report the preserved original for recovery and comparison.
