# HDFS 3.4.3: 50 randomly selected coordination candidates

This experiment samples **50 of the 532** HDFS candidates marked `YES` by
GraphChecker. `selected50.json` is the frozen sample. It preserves the first
ten checks from `../hdfs_random10/selected10.json` and draws 40 more without
replacement from the other 522 using the same seeded random generator. The
selection is fixed before measuring coverage or fault outcomes.

The completed experiment and per-site outcomes are in [`RESULTS.md`](RESULTS.md).
The machine-readable aggregate is [`audit50.json`](audit50.json).

`mapped50.json` maps each source site to its compiled HDFS 3.4.3 method and
an exact throw or precondition-call oracle. The source location alone is not
enough when several bytecode instructions map to the same line. For each
check, the agent records method entry, branch outcomes, field accesses,
message events, and the selected oracle. `run_batch50.py` runs one healthy
seed and bounded crash/reboot trials for each reachable check. The fault
scheduler uses the causal graph and the configured target anchor's backward
closure to rank candidate fault points; it retains exploration outside the
closure. For an explicit precondition call the anchor is that call. For a
throw site with no reliable single branch mapping, the current campaign
anchors the closure at method entry and separately audits the guarding
branch. This gives weaker guidance for those sites and is reported as such.

The trial result distinguishes four events:

1. The enclosing method ran.
2. The selected guard or precondition call ran.
3. A scheduled fault matched an instrumented point.
4. The target threw, and the outcome was reproducible on replay.

Method entry alone is not check coverage. An exception outside the exact
oracle is not evidence that the selected coordination check failed.
One selected BlockReceiver source line (draw 40) contains three compiled
`athrow` instructions. The current line-based hook groups those three, so
that draw needs bytecode-offset instrumentation before attributing any
future exception to one individual instruction.

The initial discovery workloads are `normal`, `special` (short circuit and
RAM_DISK), `cache`, and `rich`. Additional workloads exercise snapshots,
disk balancing, quorum journals, encryption zones, and corrupt-block
reporting. `run_recovery50.py` searches selected checks whose healthy seed
does not reach the target: a matched crash can expose recovery behavior that
is absent from the healthy execution.

The experiment runs HDFS in containers on the dedicated CloudLab node.
Each campaign uses the same container names and network, so run discovery,
batch, and recovery commands **sequentially**.

```sh
cd /users/ZhenyuLi/baseline/crashfuzz
PYTHONPATH=src python3 examples/hdfs_random50/discover50.py normal
PYTHONPATH=src python3 examples/hdfs_random50/run_batch50.py --start 11 --limit 40 --runs-per-target 2
PYTHONPATH=src python3 examples/hdfs_random50/analyze50.py
PYTHONPATH=src python3 examples/hdfs_random50/audit_all50.py
```

The results also include the first ten focused campaigns and follow-up
workloads described in `RESULTS.md`; the commands above reproduce the
main additional batch and refresh its audit, not the full set of trials.

The first ten checks and their focused workloads are under
`../hdfs_random10/`. The additional batch state is in
`out_batch/progress.json`; raw traces, fault schedules, graph feedback, and
checker outputs are retained under each candidate's run directory. The
coverage audit is `out_batch/check_coverage.json`.
