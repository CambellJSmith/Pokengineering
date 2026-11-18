#!/usr/bin/env bash
# Build the Capture Select ROM and launch it in DeSmuME.
#   ./play_capture_select.sh            # build (if needed) + launch
#   REBUILD=1 ./play_capture_select.sh  # force a full rebuild
# Needs: python3, keystone-engine (pip), desmume.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
BASE=work/debug/guardian_signs_debug.nds
PATCH=work/capture_select/capture_select_patch.json
ROM=work/capture_select/capture_select.nds

if [[ "${REBUILD:-0}" == 1 || ! -f "$BASE" ]]; then
    bash tools/build_debug_rom.sh
fi
# Generated inputs the patch builder reads (first run only)
[[ -f work/code_analysis/executables/overlays/overlay_028.bin ]] || bash tools/analyze_game_code.sh
[[ -d work/game_acf/archive ]] || bash tools/extract_game_data.sh
[[ -d work/localization ]] || bash tools/extract_localization.sh
python3 tools/capture_select/build_patch.py
# Title menu: "Ranger Net" button relabelled "Capture Select" (falls back to the plain base)
LABELLED=work/capture_select/base_relabelled.nds
if [[ "${REBUILD:-0}" == 1 || ! -f "$LABELLED" ]]; then
    bash tools/capture_select/relabel_title_button.sh "$LABELLED" >/dev/null || LABELLED="$BASE"
fi
python3 tools/patch_code_rom.py "$LABELLED" --patches "$PATCH" --output "$ROM"

EMU="${DESMUME:-}"
if [[ -z "$EMU" ]]; then
    for c in desmume desmume-glade desmume-cli; do
        command -v "$c" >/dev/null && { EMU="$c"; break; }
    done
fi
[[ -n "$EMU" ]] || { echo "DeSmuME not found (apt install desmume, or set DESMUME=/path)"; echo "ROM: $ROOT/$ROM"; exit 1; }
echo "==> Launching $ROM in $EMU (title menu: tap Capture Select, or press SELECT)"
exec "$EMU" "$ROM"
