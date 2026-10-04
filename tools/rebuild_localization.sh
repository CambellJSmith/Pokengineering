#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
workspace="${1:-$root_dir/work/localization}" # Accept an existing localization editing workspace.
acftool="$root_dir/tools/bin/acftool" # Use the locally pinned ACF rebuilder.
ra3mes="$root_dir/tools/bin/ra3mes" # Use the locally pinned Guardian Signs MES converter.
archive_dir="$workspace/editable" # Rebuild from acftool's extracted resource directory.
json_dir="$workspace/json" # Read human-edited localization JSON files from this directory.
temporary_acf="$workspace/editable.acf" # acftool writes the rebuilt archive beside the editable directory.
rebuilt_acf="$workspace/rebuilt_data_localize_us.acf" # Keep the finished archive under an explicit output name.
mes_count=275 # Guardian Signs retail localization archives begin with 275 MES entries.

require_file() { # Fail early when a required file is unavailable.
    [[ -f "$1" ]] || { printf 'missing required file: %s\n' "$1" >&2; exit 1; }
}

require_executable() { # Fail early when a required local tool has not been built.
    [[ -x "$1" ]] || { printf 'missing required tool: %s\nrun tools/setup_guardian_tools.sh first\n' "$1" >&2; exit 1; }
}

require_executable "$acftool" # Confirm the ACF extractor/rebuilder is installed.
require_executable "$ra3mes" # Confirm the MES converter is installed.
require_file "$archive_dir/filelist.json" # Confirm the extracted ACF metadata is intact.

converted=0 # Track the number of JSON files converted back into MES payloads.
for ((i = 0; i < mes_count; ++i)); do # Rebuild the documented first 275 localization entries.
    index="$(printf '%04d' "$i")" # Match acftool's four-digit archive entry naming.
    json_path="$json_dir/$index.json" # Resolve the editable JSON for this MES entry.
    require_file "$json_path" # Refuse to build an incomplete localization workspace.

    shopt -s nullglob # Allow an empty glob to become an empty array instead of a literal string.
    matches=("$archive_dir/$index".*) # Find the existing ACF entry regardless of detected extension.
    shopt -u nullglob # Restore the default shell glob behavior.

    if (( ${#matches[@]} != 1 )); then # Require one unambiguous archive entry for each MES index.
        printf 'expected one extracted entry for index %s, found %d\n' "$index" "${#matches[@]}" >&2
        exit 1
    fi

    "$ra3mes" --to-mes "$json_path" "${matches[0]}" # Replace the extracted MES payload while preserving its filelist name.
    ((converted += 1)) # Record the successful conversion.
done

rm -f -- "$temporary_acf" "$rebuilt_acf" # Remove stale outputs so this build cannot be mistaken for an older result.
"$acftool" --build "$archive_dir" # Repack all resources using acftool's original compression-state metadata.
mv -- "$temporary_acf" "$rebuilt_acf" # Give the finished archive an explicit modding output name.

printf 'rebuilt %d Guardian Signs MES files\n' "$converted" # Report the completed text conversion count.
printf 'rebuilt archive: %s\n' "$rebuilt_acf" # Report the ACF ready for reinjection into a user-owned ROM.
