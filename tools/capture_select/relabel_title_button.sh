#!/usr/bin/env bash
# Build a base ROM whose title-menu "Ranger Net" button reads "Capture Select".
# (The button's action is changed by the code patch from build_patch.py.)
#   tools/capture_select/relabel_title_button.sh [OUT_ROM]
# Needs work/localization (tools/extract_localization.sh) and tools/bin (acftool, ra3mes).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/work/capture_select/base_relabelled.nds}"
WS="$ROOT/work/capture_select/localization"
rm -rf "$WS"; mkdir -p "$WS"
cp -r "$ROOT/work/localization/json" "$ROOT/work/localization/editable" "$ROOT/work/localization/mes_entries.txt" "$WS/"
python3 "$ROOT/tools/set_localization_text.py" "$WS" 232 6 "Capture Select" >/dev/null
bash "$ROOT/tools/rebuild_localization.sh" "$WS" >/dev/null
python3 "$ROOT/tools/rebuild_nds.py" --components "$ROOT" --output "$OUT" --trim \
    --replace "data/data_localize_us.acf=$WS/rebuilt_data_localize_us.acf"
echo "$OUT"
