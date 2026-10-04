#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$root_dir/work/code_analysis"

rm -rf "$output_dir"
python3 "$root_dir/tools/analyze_nds_code.py" --root "$root_dir" --output "$output_dir" "$@"

printf '\nCode analysis outputs:\n'
printf '  %s\n' "$output_dir/summary.json"
printf '  %s\n' "$output_dir/memory_map.csv"
printf '  %s\n' "$output_dir/overlays.csv"
printf '  %s\n' "$output_dir/static_initializers.csv"
printf '  %s\n' "$output_dir/strings.csv"
printf '  %s\n' "$output_dir/ghidra_targets.csv"
