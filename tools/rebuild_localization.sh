#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
workspace="${1:-$root_dir/work/localization}" # Accept an existing localization editing workspace.
acftool="$root_dir/tools/bin/acftool" # Use the locally pinned ACF rebuilder.
ra3mes="$root_dir/tools/bin/ra3mes" # Use the locally pinned Guardian Signs MES converter.
archive_dir="$workspace/editable" # Rebuild from acftool's extracted resource directory.
json_dir="$workspace/json" # Read human-edited localization JSON files from this directory.
mes_manifest="$workspace/mes_entries.txt" # Reuse the exact MES archive filenames selected during extraction.
temporary_acf="$workspace/editable.acf" # acftool writes the rebuilt archive beside the editable directory.
rebuilt_acf="$workspace/rebuilt_data_localize_us.acf" # Keep the finished archive under an explicit output name.
mes_count=275 # Guardian Signs retail localization archives contain 275 leading MES files.

require_file() { # Fail early when a required file is unavailable.
    [[ -f "$1" ]] || { printf 'missing required file: %s\n' "$1" >&2; exit 1; }
}

require_executable() { # Fail early when a required local tool has not been built.
    [[ -x "$1" ]] || { printf 'missing required tool: %s\nrun tools/setup_guardian_tools.sh first\n' "$1" >&2; exit 1; }
}

require_executable "$acftool" # Confirm the ACF extractor/rebuilder is installed.
require_executable "$ra3mes" # Confirm the MES converter is installed.
require_file "$archive_dir/filelist.json" # Confirm the extracted ACF metadata is intact.
require_file "$mes_manifest" # Confirm the extraction step recorded the exact MES entry names.

converted=0 # Track the number of JSON files converted back into MES payloads.
while IFS= read -r entry_name; do # Rebuild only the archive entries previously proven to be localization MES resources.
    [[ -n "$entry_name" ]] || continue # Ignore accidental blank manifest lines.
    entry_path="$archive_dir/$entry_name" # Resolve the exact extracted ACF payload name preserved in filelist.json.
    require_file "$entry_path" # Refuse to build if an extracted resource is missing.
    index="${entry_name%%.*}" # Recover the original four-digit archive index from its filename.
    json_path="$json_dir/$index.json" # Resolve the editable JSON for this MES entry.
    require_file "$json_path" # Refuse to build an incomplete localization workspace.
    "$ra3mes" --to-mes "$json_path" "$entry_path" # Replace the extracted MES payload while preserving its filelist name.
    ((converted += 1)) # Record the successful conversion.
done < "$mes_manifest"

if (( converted != mes_count )); then # Require the documented retail localization MES count exactly.
    printf 'rebuilt %d MES files; expected %d\n' "$converted" "$mes_count" >&2
    exit 1
fi

rm -f -- "$temporary_acf" "$rebuilt_acf" # Remove stale outputs so this build cannot be mistaken for an older result.
"$acftool" --build "$archive_dir" # Repack all resources using acftool's original compression-state metadata.
mv -- "$temporary_acf" "$rebuilt_acf" # Give the finished archive an explicit modding output name.

printf 'rebuilt %d Guardian Signs MES files\n' "$converted" # Report the completed text conversion count.
printf 'rebuilt archive: %s\n' "$rebuilt_acf" # Report the ACF ready for reinjection into a user-owned ROM.
