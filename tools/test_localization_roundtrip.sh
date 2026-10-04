#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
source_acf="${1:-$root_dir/data/data_localize_us.acf}" # Test the supplied localization archive or the current extracted archive.
workspace_root="$(mktemp -d)" # Isolate generated game data from the repository checkout.
workspace="$workspace_root/workspace" # Store the editable round-trip test workspace here.
verify_root="$workspace_root/verify" # Store the rebuilt archive verification extraction here.
marker="Pokengineering roundtrip test" # Use deterministic ASCII text that ra3mes can encode safely.
acftool="$root_dir/tools/bin/acftool" # Use the locally pinned ACF utility.
ra3mes="$root_dir/tools/bin/ra3mes" # Use the locally pinned Guardian Signs MES converter.

cleanup() { # Remove all proprietary/generated test data when the test exits.
    rm -rf -- "$workspace_root"
}
trap cleanup EXIT # Guarantee cleanup on both success and failure.

[[ -x "$acftool" ]] || { printf 'missing acftool; run tools/setup_guardian_tools.sh first\n' >&2; exit 1; } # Require the ACF utility.
[[ -x "$ra3mes" ]] || { printf 'missing ra3mes; run tools/setup_guardian_tools.sh first\n' >&2; exit 1; } # Require the MES converter.
[[ -f "$source_acf" ]] || { printf 'missing localization archive: %s\n' "$source_acf" >&2; exit 1; } # Require an input archive.

bash "$root_dir/tools/extract_localization.sh" "$source_acf" "$workspace" # Extract the ACF and convert all retail MES entries to JSON.

read -r file_index string_index < <(python3 - "$workspace/json" <<'PY' # Locate the first editable string without printing copyrighted text.
import json
import sys
from pathlib import Path

json_dir = Path(sys.argv[1])
for path in sorted(json_dir.glob("*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data:
        first_key = next(iter(data))
        print(path.stem, first_key)
        raise SystemExit(0)
raise SystemExit("no editable localization strings found")
PY
)

python3 "$root_dir/tools/set_localization_text.py" "$workspace" "$file_index" "$string_index" "$marker" # Change one string in the editable JSON.
bash "$root_dir/tools/rebuild_localization.sh" "$workspace" # Rebuild the modified ACF archive.

mkdir -p "$verify_root" # Create an isolated verification directory.
cp -- "$workspace/rebuilt_data_localize_us.acf" "$verify_root/rebuilt.acf" # Copy the rebuilt archive under a predictable extraction name.
"$acftool" --extract "$verify_root/rebuilt.acf" # Re-extract the rebuilt archive to prove it is structurally readable.

shopt -s nullglob # Allow an empty glob to become an empty array instead of a literal string.
verify_matches=("$verify_root/rebuilt/$file_index".*) # Find the modified MES payload after re-extraction.
shopt -u nullglob # Restore the default shell glob behavior.

if (( ${#verify_matches[@]} != 1 )); then # Require one unambiguous verification entry.
    printf 'expected one rebuilt entry for index %s, found %d\n' "$file_index" "${#verify_matches[@]}" >&2
    exit 1
fi

"$ra3mes" --to-json "${verify_matches[0]}" "$verify_root/verified.json" # Decode the rebuilt MES payload again.
python3 - "$verify_root/verified.json" "$string_index" "$marker" <<'PY' # Verify the edited string survived the complete ACF round trip.
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
expected = sys.argv[3]
data = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(data, dict) or data.get(key) != expected:
    raise SystemExit("modified localization string did not survive the ACF round trip")
print("localization ACF/MES round trip verified")
PY
