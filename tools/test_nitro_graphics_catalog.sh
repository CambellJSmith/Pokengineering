#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
catalog_dir="$root_dir/work/game_acf/graphics_catalog"
temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT

python3 "$root_dir/tools/test_nitro_graphics_previews.py"
python3 "$root_dir/tools/test_guardian_graphics_variants.py"
python3 "$root_dir/tools/render_guardian_graphics.py" "$catalog_dir" "$temp_dir/previews" --metadata-only

python3 - "$catalog_dir" "$temp_dir/previews" <<'PY'
import csv
import json
import sys
from collections import Counter
from pathlib import Path

catalog_dir = Path(sys.argv[1])
preview_dir = Path(sys.argv[2])
with (catalog_dir / "resources.csv").open("r", encoding="utf-8", newline="") as source:
    resources = list(csv.DictReader(source))
with (preview_dir / "resource_inspection.csv").open("r", encoding="utf-8", newline="") as source:
    inspections = list(csv.DictReader(source))
with (preview_dir / "candidate_previews.csv").open("r", encoding="utf-8", newline="") as source:
    candidates = list(csv.DictReader(source))
with (preview_dir / "unresolved.csv").open("r", encoding="utf-8", newline="") as source:
    unresolved = list(csv.DictReader(source))
with (preview_dir / "format_anomalies.csv").open("r", encoding="utf-8", newline="") as source:
    anomalies = list(csv.DictReader(source))
summary = json.loads((preview_dir / "summary.json").read_text(encoding="utf-8"))

if summary["resources_inspected"] != len(resources) or len(inspections) != len(resources):
    raise SystemExit("renderer did not inspect every graphics catalogue resource")
if summary["resource_parse_errors"] != 0:
    failures = [row for row in inspections if row["parse_status"] != "ok"]
    grouped = Counter((row["kind"], row["error"]) for row in failures)
    print("retail Nitro parse-error groups:", file=sys.stderr)
    for (kind, error), count in grouped.most_common():
        example = next(row["logical_path"] for row in failures if row["kind"] == kind and row["error"] == error)
        print(f"  {count:5d}  {kind:4s}  {error}  example={example}", file=sys.stderr)
    raise SystemExit(f"retail Nitro resources have {len(failures)} parse errors")
if summary["resources_parsed"] != len(resources):
    raise SystemExit("renderer did not parse every graphics catalogue resource")
expected = Counter(row["kind"] for row in resources)
if summary["parsed_formats"] != dict(sorted(expected.items())):
    raise SystemExit("parsed format counts do not match graphics catalogue")
if summary["semantic_pairings_claimed"] != 0:
    raise SystemExit("renderer claimed semantic pairings")
if summary["metadata_only"] is not True:
    raise SystemExit("retail CI did not run in metadata-only mode")
if summary["atomic_previews_written"] != 0:
    raise SystemExit("metadata-only mode unexpectedly wrote atomic previews")
if list(preview_dir.rglob("*.png")):
    raise SystemExit("metadata-only mode unexpectedly wrote PNG files")
if len(candidates) != summary["candidate_rows"]:
    raise SystemExit("candidate preview summary count is inconsistent")
if len(unresolved) != summary["unresolved_rows"]:
    raise SystemExit("unresolved preview summary count is inconsistent")
if len(anomalies) != summary["format_anomalies"]:
    raise SystemExit("format anomaly ledger count is inconsistent")
if any(row["semantic_pairing_proven"].lower() != "false" for row in candidates):
    raise SystemExit("candidate preview was incorrectly marked as a proven semantic pairing")
if not candidates:
    raise SystemExit("renderer found no structurally valid candidate previews")
if not anomalies:
    raise SystemExit("retail Guardian Signs compatibility anomalies were not recorded")

print(f"retail Nitro resources parsed: {len(resources)}")
print(f"structurally valid candidate previews: {len(candidates)}")
print(f"explicit unresolved candidate records: {len(unresolved)}")
print(f"recorded retail format anomalies: {len(anomalies)}")
print("Guardian Signs Nitro graphics metadata validation passed")
PY
