#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
catalog_dir="$root_dir/work/game_acf/graphics_catalog"
preview_dir="$root_dir/work/game_acf/graphics_previews"
output_dir="$root_dir/work/game_acf/graphics_identification"
first_preview="$(find "$preview_dir/candidates" -type f -name '*.png' -print -quit 2>/dev/null || true)"

if [[ ! -f "$preview_dir/candidate_previews.csv" || -z "$first_preview" ]]; then
    printf 'full rendered graphics previews are required.\n' >&2
    printf 'Generate them first with:\n\n  rm -rf work/game_acf/graphics_previews\n  bash tools/render_game_graphics.sh\n\n' >&2
    exit 1
fi

rm -rf "$output_dir"
python3 "$root_dir/tools/identify_graphics.py" "$catalog_dir" "$preview_dir" "$output_dir" "$@"

printf 'automatic graphics index: %s\n' "$output_dir/identified_candidates.csv"
printf 'automatic graphics families: %s\n' "$output_dir/families.csv"
printf 'browseable graphics gallery: %s\n' "$output_dir/index.html"
