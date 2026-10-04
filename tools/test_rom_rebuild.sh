#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root from the test location.
test_root="$(mktemp -d)" # Isolate all generated ROM and replacement data outside the repository checkout.
original_acf="$test_root/original_localize.acf" # Store the correctly aligned original localization archive for the size-change test.
replacement_acf="$test_root/replacement_localize.acf" # Store a deliberately size-changed stand-in replacement.
baseline_rom="$test_root/baseline.nds" # Store a no-modification reconstruction for exact metadata checks.
modified_rom="$test_root/modified.nds" # Store the replacement-bearing reconstruction for shifted-FAT checks.
marker='POKENGINEERING_ROM_REBUILD_TEST' # Append deterministic bytes so the replacement changes size without exposing original dialogue.

cleanup() { # Remove generated proprietary and reconstructed data regardless of test result.
    rm -rf -- "$test_root" # Delete all temporary ACF and ROM outputs.
}
trap cleanup EXIT # Guarantee cleanup on both success and failure.

python3 "$root_dir/tools/extract_nitrofs_file.py" "$root_dir/fat_data.bin" "$root_dir/fat.bin" "$root_dir/_file_IDs.txt" "data/data_localize_us.acf" "$original_acf" # Recover the known-good localization archive from the validated raw FAT payload.
cp -- "$original_acf" "$replacement_acf" # Preserve the original archive while creating a deterministic size-changing replacement.
printf '%s' "$marker" >> "$replacement_acf" # Increase file ID 0x23 so every later NitroFS FAT range must move.

python3 "$root_dir/tools/rebuild_nds.py" --components "$root_dir" --output "$baseline_rom" --trim # Reconstruct an unmodified trimmed ROM from the current extracted components.
python3 "$root_dir/tools/validate_nds.py" "$baseline_rom" --components "$root_dir" # Independently validate the baseline header, fixed regions, overlay FAT entries, and NitroFS ranges.

python3 - "$root_dir" "$baseline_rom" <<'PY' # Prove a no-replacement rebuild preserves original header and FAT metadata exactly.
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
rom = Path(sys.argv[2])
header = (root / "header.bin").read_bytes()
with rom.open("rb") as source:
    rebuilt_header = source.read(len(header))
    fat_offset = struct.unpack_from("<I", rebuilt_header, 0x48)[0]
    fat_size = struct.unpack_from("<I", rebuilt_header, 0x4C)[0]
    source.seek(fat_offset)
    rebuilt_fat = source.read(fat_size)
if rebuilt_header != header:
    raise SystemExit("baseline ROM header differs from the extracted original header")
if rebuilt_fat != (root / "fat.bin").read_bytes():
    raise SystemExit("baseline ROM FAT differs from the extracted original FAT")
if rom.stat().st_size != struct.unpack_from("<I", header, 0x80)[0]:
    raise SystemExit("baseline trimmed ROM size does not match the original used-ROM size")
print("baseline ROM metadata preserved exactly")
PY

python3 "$root_dir/tools/rebuild_nds.py" --components "$root_dir" --output "$modified_rom" --replace "data/data_localize_us.acf=$replacement_acf" --trim # Rebuild with a larger file ID 0x23 so later NitroFS addresses must shift.
python3 "$root_dir/tools/validate_nds.py" "$modified_rom" --components "$root_dir" --expect "data/data_localize_us.acf=$replacement_acf" # Verify the replacement bytes and complete rebuilt structure independently.

python3 - "$root_dir" "$modified_rom" "$replacement_acf" <<'PY' # Verify the exact FAT shift caused by the size-changing replacement.
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
rom = Path(sys.argv[2])
replacement = Path(sys.argv[3])
original_fat_data = (root / "fat.bin").read_bytes()
original_fat = [struct.unpack_from("<II", original_fat_data, offset) for offset in range(0, len(original_fat_data), 8)]
file_ids = {}
for line in (root / "_file_IDs.txt").read_text(encoding="utf-8").splitlines():
    if ":::" not in line:
        continue
    raw_id, path = line.split(":::", 1)
    try:
        file_id = int(raw_id, 16)
    except ValueError:
        continue
    file_ids[path.replace("\\", "/").lstrip("/")] = file_id
localize_id = file_ids["data/data_localize_us.acf"]
next_id = localize_id + 1
old_start, old_end = original_fat[localize_id]
old_size = old_end - old_start
delta = replacement.stat().st_size - old_size
if delta <= 0:
    raise SystemExit("replacement test did not increase the localization archive size")
with rom.open("rb") as source:
    header = source.read(0x4000)
    fat_offset = struct.unpack_from("<I", header, 0x48)[0]
    fat_size = struct.unpack_from("<I", header, 0x4C)[0]
    used_size = struct.unpack_from("<I", header, 0x80)[0]
    source.seek(fat_offset)
    rebuilt_fat_data = source.read(fat_size)
rebuilt_fat = [struct.unpack_from("<II", rebuilt_fat_data, offset) for offset in range(0, len(rebuilt_fat_data), 8)]
new_start, new_end = rebuilt_fat[localize_id]
if new_start != old_start or new_end - new_start != replacement.stat().st_size:
    raise SystemExit("replacement FAT entry does not describe the exact replacement bytes")
if rebuilt_fat[:localize_id] != original_fat[:localize_id]:
    raise SystemExit("FAT entries before the replacement changed unexpectedly")
old_next_start, old_next_end = original_fat[next_id]
new_next_start, new_next_end = rebuilt_fat[next_id]
if (new_next_start, new_next_end) != (old_next_start + delta, old_next_end + delta):
    raise SystemExit("the first FAT entry after the replacement did not shift by the replacement size delta")
original_used_size = struct.unpack_from("<I", (root / "header.bin").read_bytes(), 0x80)[0]
if used_size != original_used_size + delta:
    raise SystemExit("rebuilt used-ROM size did not shift by the replacement size delta")
if rom.stat().st_size != used_size:
    raise SystemExit("trimmed modified ROM does not end at its rebuilt used-ROM size")
print(f"size-changing replacement shifted subsequent NitroFS data by {delta} bytes")
PY

printf 'Nintendo DS ROM rebuild/reinjection test passed\n' # Report a complete baseline and size-changing filesystem rebuild success.
