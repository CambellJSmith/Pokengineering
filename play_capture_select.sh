#!/usr/bin/env bash
# Build the Capture Select ROM and launch it in DeSmuME.
#   ./play_capture_select.sh            # build (if needed) + launch
#   REBUILD=1 ./play_capture_select.sh  # force a full rebuild
# Needs: python3, keystone-engine (pip), console-setup-linux (menu font), desmume.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
BASE=work/debug/guardian_signs_debug.nds
PATCH=work/capture_select/capture_select_patch.json
ROM=work/capture_select/capture_select.nds

if [[ "${REBUILD:-0}" == 1 || ! -f "$BASE" ]]; then
    bash tools/build_debug_rom.sh
fi
python3 tools/capture_select/build_patch.py
python3 tools/patch_code_rom.py "$BASE" --patches "$PATCH" --output "$ROM"

EMU="${DESMUME:-}"
if [[ -z "$EMU" ]]; then
    for c in desmume desmume-glade desmume-cli; do
        command -v "$c" >/dev/null && { EMU="$c"; break; }
    done
fi
[[ -n "$EMU" ]] || { echo "DeSmuME not found (apt install desmume, or set DESMUME=/path)"; echo "ROM: $ROOT/$ROM"; exit 1; }
echo "==> Launching $ROM in $EMU (title screen: SELECT opens Capture Select)"
exec "$EMU" "$ROM"
