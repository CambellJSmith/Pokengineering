#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root from the tool location.
workspace="${1:-$root_dir/work/localization}" # Use the localization editing workspace by default.
output_rom="${2:-$root_dir/work/guardian_signs_modded.nds}" # Write the reconstructed ROM into the ignored work directory by default.
mode="${3:-}" # Accept an optional --trim mode for emulator-oriented output.
rebuilt_acf="$workspace/rebuilt_data_localize_us.acf" # Use the archive produced by the localization rebuild milestone.
rebuilder="$root_dir/tools/rebuild_nds.py" # Resolve the deterministic Nintendo DS ROM rebuilder.
validator="$root_dir/tools/validate_nds.py" # Resolve the independent rebuilt-ROM validator.

[[ -f "$rebuilt_acf" ]] || { printf 'missing rebuilt localization archive: %s\nrun tools/rebuild_localization.sh first\n' "$rebuilt_acf" >&2; exit 1; } # Require a completed localization rebuild before assembling the ROM.
[[ -f "$rebuilder" ]] || { printf 'missing ROM rebuilder: %s\n' "$rebuilder" >&2; exit 1; } # Require the reconstruction tool.
[[ -f "$validator" ]] || { printf 'missing ROM validator: %s\n' "$validator" >&2; exit 1; } # Require post-build structural validation.
command -v python3 >/dev/null 2>&1 || { printf 'missing required command: python3\n' >&2; exit 1; } # Require Python 3 for the ROM toolchain.

python3 - "$rebuilt_acf" <<'PY' # Reject an accidental non-ACF input before writing a large ROM image.
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.read_bytes()[:4] != b"acf\0":
    raise SystemExit(f"rebuilt localization archive does not begin with acf\\0: {path}")
PY

extra_args=() # Build optional ROM-output arguments without unsafe string expansion.
if [[ "$mode" == "--trim" ]]; then # Support a smaller image that ends at the header's used-ROM size.
    extra_args+=("--trim") # Pass trim mode directly to the Python rebuilder.
elif [[ -n "$mode" ]]; then # Reject unknown third arguments instead of silently ignoring them.
    printf 'unsupported build mode: %s\nexpected --trim or no third argument\n' "$mode" >&2
    exit 1
fi

mkdir -p "$(dirname "$output_rom")" # Create the ignored output directory when needed.
python3 "$rebuilder" --components "$root_dir" --output "$output_rom" --replace "data/data_localize_us.acf=$rebuilt_acf" "${extra_args[@]}" # Rebuild the Nintendo DS image with the modified localization archive at FAT file ID 0x23.
python3 "$validator" "$output_rom" --components "$root_dir" --expect "data/data_localize_us.acf=$rebuilt_acf" # Independently verify fixed sections, header CRC, FAT geometry, and replacement bytes.
printf 'modded ROM validated: %s\n' "$output_rom" # Report the image ready for emulator smoke testing.
