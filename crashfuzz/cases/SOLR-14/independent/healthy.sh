#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out_name="${1:-healthy-01}"
mkdir -p "$here/$out_name"
set +e
python3 "$here/run.py" "$here/$out_name" > "$here/$out_name/driver.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$here/$out_name/driver.exit"
exit "$rc"
