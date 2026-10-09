#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
max_trials="${1:?max trial count required}"
max_faults="${2:?max ordered fault count required}"
mkdir -p "$here/campaign"
set +e
python3 "$here/fuzz.py" --max-trials "$max_trials" --max-faults "$max_faults" \
  > "$here/campaign/driver-${max_trials}.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$here/campaign/driver-${max_trials}.exit"
exit "$rc"
