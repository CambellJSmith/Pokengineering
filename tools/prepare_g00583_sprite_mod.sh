#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
payloads="$root_dir/work/game_acf/graphics_catalog/payloads"
output_dir="${1:-$root_dir/work/game_acf/mods/G00583_bank_0001}"

python3 "$root_dir/tools/edit_ncer_sprite.py" export \
  "$payloads/acf_2140__acf_0002.ncgr" \
  "$payloads/acf_2140__acf_0001.nclr" \
  "$payloads/acf_2140__acf_0003.ncer" \
  1 \
  "$output_dir"

printf 'G00583 edit workspace: %s\n' "$output_dir"
printf 'Edit PNGs only in: %s/pieces\n' "$output_dir"
printf 'Use the reference image only as a visual guide: %s/reference_bank_0001.png\n' "$output_dir"
