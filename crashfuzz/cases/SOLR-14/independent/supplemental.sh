#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
run_name="${1:-healthy-01}"
out="$here/supplemental/shardsplit/$run_name"
mkdir -p "$out"
set +e
SOLRSPLIT_SUPPLEMENTAL_RUN="$run_name" python3 "$here/supplemental_smoke.py" > "$out/driver.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$out/driver.exit"
exit "$rc"
