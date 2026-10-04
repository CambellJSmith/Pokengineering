#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
catalog_dir="${1:-$root_dir/work/game_acf/graphics_catalog}"
output_dir="${2:-$root_dir/work/game_acf/graphics_previews}"
renderer="$root_dir/tools/render_guardian_graphics.py"

[[ -f "$renderer" ]] || { printf 'missing renderer: %s\n' "$renderer" >&2; exit 1; }
[[ -f "$catalog_dir/resources.csv" ]] || { printf 'missing graphics catalogue: %s\n' "$catalog_dir/resources.csv" >&2; exit 1; }
[[ -f "$catalog_dir/adjacent_runs.csv" ]] || { printf 'missing graphics run catalogue: %s\n' "$catalog_dir/adjacent_runs.csv" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf 'missing required command: python3\n' >&2; exit 1; }

if [[ -e "$output_dir" ]] && [[ -n "$(find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    printf 'preview directory is not empty: %s\nremove it or choose another output path\n' "$output_dir" >&2
    exit 1
fi

python3 "$renderer" "$catalog_dir" "$output_dir"
printf 'Nitro graphics previews: %s\n' "$output_dir"
printf 'preview index: %s\n' "$output_dir/candidate_previews.csv"
printf 'format anomaly ledger: %s\n' "$output_dir/format_anomalies.csv"
printf 'unresolved candidates: %s\n' "$output_dir/unresolved.csv"
