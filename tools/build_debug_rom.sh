#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/work/debug"
OUT_ROM="$OUT_DIR/guardian_signs_debug.nds"

mkdir -p "$OUT_DIR"

echo "==> Rebuilding Guardian Signs ROM"

python3 "$ROOT/tools/rebuild_nds.py" \
    --components "$ROOT" \
    --output "$OUT_ROM" \
    --trim

echo
echo "==> Validating rebuilt ROM"

python3 "$ROOT/tools/validate_nds.py" \
    "$OUT_ROM" \
    --components "$ROOT"

echo
echo "==> ROM ready:"
echo "$OUT_ROM"
