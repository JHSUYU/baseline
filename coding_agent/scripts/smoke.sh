#!/usr/bin/env bash
# smoke.sh <case> -- start the case's container and run its starting test inside it (no agent).
set -uo pipefail
c=$1; R=/bulk/codingagent
python3 -I -c "
import sys; sys.argv=['x','$c']
exec(open('$R/bin/driver.py').read().split('if __name__')[0])
container_up(); print(' '.join(exec_env()))" > $R/cases/$c/logs/exec-env.txt
cmd=$(sed -n 's/^cd [^ ]* && //p' $R/cases/$c/prompt.md | head -1)
tree=$(ls -d $R/cases/$c/agent/{hadoop,hbase,zookeeper,lucene-solr} 2>/dev/null)
docker exec $(cat $R/cases/$c/logs/exec-env.txt) -w $tree ca-$c bash -c "source ../env.sh; $cmd" > $R/cases/$c/logs/smoke.log 2>&1
echo "$c exit=$?"; grep -E 'Tests run:|BUILD|Tests summary|tests failed|BUILD (SUCCESSFUL|FAILED)' $R/cases/$c/logs/smoke.log | tail -4
