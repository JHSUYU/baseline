#!/usr/bin/env bash
set -u

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-07/actor-v2
lock=/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock
cd "$case_dir" || exit 1
rm -f campaign-v4-node2.exit
exec > >(tee -a "$case_dir/campaign-v4-node2.log") 2>&1
trap 'printf "%s\n" "$?" > "$case_dir/campaign-v4-node2.exit"' EXIT

exec 9>>"$lock"
while true; do
  flock -x 9
  running_java=$(pgrep -c java || true)
  free_kib=$(df -P -k "$case_dir" | awk 'NR==2 {print $4}')
  if (( running_java <= 2 && free_kib >= 10485760 )); then
    break
  fi
  flock -u 9
  printf 'waiting for Solr JUnit slot: java=%s free_kib=%s\n' "$running_java" "$free_kib"
  sleep 10
done

# Keep the shared startup lock until this campaign's first JVM appears. The
# existing V2 runner then owns each trial and writes its atomic checkpoint.
initial_java=$running_java
python3 campaign_v4.py &
runner=$!
for _ in $(seq 1 300); do
  running_java=$(pgrep -c java || true)
  if (( running_java > initial_java )) || ! kill -0 "$runner" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
flock -u 9
wait "$runner"
