#!/bin/bash
# Rerun every TLC counterexample from the published copies (publish/baseline/specula/{new,known}-bugs/*/tlc/RERUN.md).
cd /bulk/specula-adhoc/publish/baseline/specula
export PATH=/bulk/specula-adhoc/jdk/jdk-21.0.13+9/bin:$PATH
run() {
  r=$1/tlc/RERUN.md
  [ -f $r ] || { printf '%s\tno TLC (code review)\n' "$1"; return; }
  cmd=$(awk '/^```$/{f=!f; next} f' $r | sed 's/   # from specula\///')
  out=$(cd /bulk/specula-adhoc/publish/baseline/specula && timeout 7200 bash -c "$cmd" 2>&1)
  res=$(grep -oE 'Invariant [A-Za-z0-9_]+ is violated|No error has been found|Error: .{0,80}' <<<"$out" | head -1)
  st=$(grep -oE '[0-9,]+ distinct states found' <<<"$out" | tail -1)
  printf '%s\t%s\t%s\n' "$1" "${res:-NO RESULT}" "$st"
}
export -f run
ls -d new-bugs/*/ known-bugs/*/ | sed 's#/$##' | xargs -P 6 -I{} bash -c 'run {}' | sort
