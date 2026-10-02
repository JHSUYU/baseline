# HDFS 3.4.3: graph, basic-block, and branch feedback on ten checks

This campaign reruns the frozen first ten HDFS candidates in `selected10.json`
and `mapped10.json`. Each check has its own healthy seed and up to three
crash/reboot trials. The workload chosen for each check is recorded in
`out_coverage10/progress.json`; the campaign uses the same specialized
workloads that reached these checks in the earlier HDFS pilot.

The Java agent assigns a stable `#BB<n>` identifier to each basic block in an
instrumented method and records conditional branch outcomes as `#B<n>` plus
`true` or `false`. Detailed events carry the JVM process and method span, so
the graph builder can count blocks and branch outcomes inside the target
check's causal closure. The HDFS package also emits first-hit, process-local
`GLOBAL_BLOCK` and `GLOBAL_BRANCH` events. Those contribute to exploration
coverage; they do not create causal edges or prove that a target check ran.
The broad channel currently covers HDFS classes and conditional jumps, not
switch arms or exception edges.

For this ten-check experiment, `analyze_checks.py` maps a compiled guard for
each target. The exact source-line throw remains a separate fatal oracle.
In particular, a mapped guard may execute safely; an exception at another
location does not count as a coordination failure. Each run writes
`result.json` and `feedback.json`, separating total and newly observed block
and branch coverage, both globally and inside the target closure.
The controller freezes fault matching when the workload returns; events from
the later correctness checker are excluded from graph and coverage feedback
using the recorded workload-end timestamp. A sequence counts as matched only
when every planned action was injected before that boundary.

To reproduce from `/users/ZhenyuLi/baseline/crashfuzz`:

```sh
cd agent && mvn -q -DskipTests package && cd ..
PYTHONPATH=src python3 examples/hdfs_random10/run_coverage10.py \
  --start 1 --limit 10 --runs-per-target 4
PYTHONPATH=src python3 examples/hdfs_random10/summarize_coverage10.py
```

Runs are sequential because they share a named HDFS Docker network and four
node containers. The summary is `coverage10.json`; raw per-run state, traces,
fault schedules, checker outputs, and feedback remain in `out_coverage10/`.
