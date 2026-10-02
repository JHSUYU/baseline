# HDFS 3.4.3: archived pre-epoch ten-check run

This report and `coverage10_pre_epoch.json` / `branches10_pre_epoch.json`
preserve the first coverage run. Its raw `out_coverage10/` directory was
archived locally as `out_archive/out_coverage10_pre_epoch.tar.zst` (with a
SHA-256 sidecar) before the same ten checks were rerun with strict process
epoch matching. References below to `out_coverage10/`, `coverage10.json`, and
`branches10.json` describe that archived run.

This campaign reruns the frozen first ten HDFS candidates in `selected10.json`
and `mapped10.json`. Each check has its own healthy seed and fault trials
(three for most checks, five for candidate 07). The workload is recorded in
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

A detailed branch event records a stable `method#B<n>` site, `true` or
`false` outcome, node, process, invocation span, and timestamp. The graph
associates it with that invocation. For a target check T, we traverse the
graph backward from T across call, return, message, asynchronous, and
observed-state edges. A branch is *closure related* when its invocation is
in that backward closure. We compare `(node role, branch site, outcome)`
features with those already seen for the same check, and save per-run counts
in `result.json` and new-feature counts in `feedback.json`; the exact events
remain in `traces/`. `export_branch10.py` replays the graph analysis and
exports the exact accepted branch features to `branches10.json`, checking
its counts against each run's feedback. This is a conservative method-region approximation:
membership does not prove that the branch outcome caused T. The mapped
guard's outcome and exact throw site are therefore checked separately.

For this ten-check experiment, `analyze_checks.py` maps a compiled guard for
each target. The exact source-line throw remains a separate fatal oracle.
In particular, a mapped guard may execute safely; an exception at another
location does not count as a coordination failure. Each run writes
`result.json` and `feedback.json`, separating total and newly observed block
and branch coverage, both globally and inside the target closure.
The controller arms fault matching only after cluster preparation and freezes
it when the workload returns. Preparation and checker events are excluded
from graph and coverage feedback using the recorded workload start and end
timestamps. A sequence counts as matched only when every planned action was
injected within that window. Broad first-hit JVM coverage can miss a block
executed again in the workload if the same JVM already emitted its first-hit
event during preparation; detailed target-region probes do not use that
first-hit filter.

To reproduce from `/users/ZhenyuLi/baseline/crashfuzz`:

```sh
cd agent && mvn -q -DskipTests package && cd ..
PYTHONPATH=src python3 examples/hdfs_random10/run_coverage10.py \
  --start 7 --limit 1 --runs-per-target 6 --max-site-occurrence 1
PYTHONPATH=src python3 examples/hdfs_random10/run_coverage10.py \
  --start 1 --limit 10 --runs-per-target 4
PYTHONPATH=src python3 examples/hdfs_random10/summarize_coverage10.py
PYTHONPATH=src python3 examples/hdfs_random10/export_branch10.py
```

Runs are sequential because they share a named HDFS Docker network and four
node containers. The summaries are `coverage10.json` and `branches10.json`;
raw per-run state, traces,
fault schedules, checker outputs, and feedback remain in `out_coverage10/`.

## Completed experiment

All ten selected checks completed. There were 32 attempted fault trials:
25 injected the entire planned sequence, 3 injected only a prefix, and 4
injected nothing. All 31 individual injections used exact node, site,
context, ordinal, and phase matching. Of the 25 fully matched trials, 21
reached the configured target guard. None reached its exact throw site, and
none had a checker failure. The target closures gained 14 previously unseen
branch outcomes across the fully matched trials.

| Draw | Full matches | Target reached after full match | New closure branch outcomes |
| ---: | ---: | ---: | ---: |
| 1 | 3 | 0 | 0 |
| 2 | 2 | 1 | 2 |
| 3 | 2 | 2 | 0 |
| 4 | 3 | 3 | 0 |
| 5 | 2 | 2 | 0 |
| 6 | 2 | 2 | 0 |
| 7 | 4 | 4 | 3 |
| 8 | 2 | 2 | 8 |
| 9 | 3 | 3 | 1 |
| 10 | 2 | 2 | 0 |

Draw 2 illustrates recovery-specific reachability: its healthy workload did
not execute the guard, but one exactly matched crash/reboot trial did, with
two new closure branch outcomes. The guard's observed outcome was safe, the
exact throw did not execute, and the checker passed. This is new recovery
behavior, not evidence of a new HDFS bug. The other runs also provide no
reproduced target failure. The raw run records and `branches10.json` support
the per-target counts above.
