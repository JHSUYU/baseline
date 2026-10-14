#!/usr/bin/env bash
BASE=/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2
HOST=${1:-$(hostname -s)}
"$BASE/run-host-once.sh" "$HOST"
CODE=$?
printf '\nNative queue host %s finished with exit %s. Rerun: %s/run-host-once.sh %s\n' "$HOST" "$CODE" "$BASE" "$HOST"
exec bash --noprofile --norc
