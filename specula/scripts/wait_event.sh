#!/usr/bin/env bash
# wait_event.sh <system> [seconds] -- block until a case of the system finishes, needs the operator,
# or hits an ERROR/Traceback line, or the time runs out (default 580 s).  Prints what changed.
system=${1:?usage: wait_event.sh <system> [seconds]}
limit=${2:-540}
dir=/bulk/specula-adhoc/${system}
snap=${dir}/.wait-snapshot
[[ -f ${snap} ]] || : > "${snap}"
current() {
  awk -F'\t' 'FNR>1 && ($2=="done" || $2 ~ /^needs operator/ || $2 ~ /^exit/ || $2=="crashed") {print $1"\t"$2}' "${dir}"/queue-status.*.txt 2>/dev/null
  grep -lE "Traceback|^ERROR" "${dir}"/logs/*.log 2>/dev/null | sed 's/$/\tERROR-line/'
}
end=$((SECONDS + limit))
while (( SECONDS < end )); do
  now=$(current | sort)
  new=$(comm -13 "${snap}" <(echo "${now}"))
  if [[ -n ${new} ]]; then
    echo "${now}" > "${snap}"
    echo "CHANGED:"; echo "${new}"
    head -qn1 "${dir}"/queue-status.*.txt
    exit 0
  fi
  sleep 30
done
echo "no change"; head -qn1 "${dir}"/queue-status.*.txt
