#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
input_acf="${1:-$root_dir/data/data_localize_us.acf}" # Accept an explicit user-supplied ACF or use the current extracted archive.
workspace="${2:-$root_dir/work/localization}" # Keep editable outputs in the ignored local workspace.
acftool="$root_dir/tools/bin/acftool" # Use the locally pinned ACF utility.
ra3mes="$root_dir/tools/bin/ra3mes" # Use the locally pinned Guardian Signs text converter.
cataloguer="$root_dir/tools/catalog_localization.py" # Build a metadata catalogue after extraction.
editable_acf="$workspace/editable.acf" # Give acftool a temporary archive name that maps to the editable directory.
original_acf="$workspace/original.acf" # Preserve an untouched local copy for comparison and recovery.
archive_dir="$workspace/editable" # acftool extracts editable.acf into this directory.
json_dir="$workspace/json" # Store human-editable MES JSON files separately from binary resources.
catalog_path="$workspace/catalog.csv" # Store non-content resource metadata for analysis.
mes_count=275 # Guardian Signs retail localization archives begin with 275 MES entries.

require_file() { # Fail early when a required file is unavailable.
    [[ -f "$1" ]] || { printf 'missing required file: %s\n' "$1" >&2; exit 1; }
}

require_executable() { # Fail early when a required local tool has not been built.
    [[ -x "$1" ]] || { printf 'missing required tool: %s\nrun tools/setup_guardian_tools.sh first\n' "$1" >&2; exit 1; }
}

require_file "$input_acf" # Confirm the localization archive exists.
require_file "$cataloguer" # Confirm the catalogue script exists.
require_executable "$acftool" # Confirm the ACF extractor/rebuilder is installed.
require_executable "$ra3mes" # Confirm the MES converter is installed.
command -v python3 >/dev/null 2>&1 || { printf 'missing required command: python3\n' >&2; exit 1; } # Require Python for catalogue generation.

if [[ -e "$workspace" ]] && [[ -n "$(find "$workspace" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then # Refuse to overwrite an existing editing session.
    printf 'workspace is not empty: %s\nremove it or choose another workspace path\n' "$workspace" >&2
    exit 1
fi

mkdir -p "$workspace" "$json_dir" # Create the local editing workspace.
cp -- "$input_acf" "$editable_acf" # Copy the archive so extraction never alters the source file.
"$acftool" --extract "$editable_acf" # Extract and decompress all ACF entries plus filelist.json.
mv -- "$editable_acf" "$original_acf" # Preserve the untouched archive before any rebuild can replace editable.acf.

converted=0 # Track the number of MES files successfully converted to JSON.
for ((i = 0; i < mes_count; ++i)); do # Convert the documented first 275 localization entries.
    index="$(printf '%04d' "$i")" # Match acftool's four-digit archive entry naming.
    shopt -s nullglob # Allow an empty glob to become an empty array instead of a literal string.
    matches=("$archive_dir/$index".*) # Find the extracted file regardless of detected extension.
    shopt -u nullglob # Restore the default shell glob behavior.

    if (( ${#matches[@]} != 1 )); then # Require one unambiguous archive entry for each MES index.
        printf 'expected one extracted entry for index %s, found %d\n' "$index" "${#matches[@]}" >&2
        exit 1
    fi

    "$ra3mes" --to-json "${matches[0]}" "$json_dir/$index.json" # Convert the MES payload into editable JSON.
    ((converted += 1)) # Record the successful conversion.
done

python3 "$cataloguer" "$archive_dir" "$json_dir" "$catalog_path" # Generate metadata for every ACF entry.
printf 'extracted %d Guardian Signs MES files\n' "$converted" # Report the completed text conversion count.
printf 'editable text: %s\n' "$json_dir" # Report where JSON text can be modified.
printf 'resource catalog: %s\n' "$catalog_path" # Report where archive metadata can be inspected.
printf 'untouched archive: %s\n' "$original_acf" # Report the preserved original for recovery and comparison.
