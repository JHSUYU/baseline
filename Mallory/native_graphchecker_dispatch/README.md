# Native GraphChecker 102-check dispatcher

This package reads the original 102-case inventory and the pinned three-host
ownership map. It is separate from the former custom-graph campaigns and their
import table. It never counts those old runs as native completion.

For each case, place a validated `native_graphchecker_campaign` config at
`CONFIG_ROOT/CASE-ID.json`. Its original JUnit class and method must match the
inventory. The case's one-time original recording and concolic weave are
prepared before dispatch. The dispatcher neither chooses I/O points by hand
nor creates a substitute target. A missing config remains
`needs_native_preparation` in the checklist.

On each owner host, run one case at a time. `run-next` checks the physical host
name (`node0`, `node1`, or `node2`) and uses a host lock plus a case lock.
`native_graphchecker_campaign` has its own trial lock and resumes at the last
closed trial. Repeating the command advances to the next unfinished case. A
terminal native checkpoint is never run again, even when a receipt is damaged;
such a case is reported as `receipt_error` for inspection.

```bash
python3 -m Mallory.native_graphchecker_dispatch run-next \
  --host node1 --config-root /ABS/CONFIG_ROOT \
  --state-root /ABS/NATIVE_STATE_ROOT
```

Read the 102-row table from node0. `--remote` asks node1 and node2 to audit
their own local state over the existing SSH connection and refuses missing or
version-mismatched responses. Paths passed to the command must exist with the
same spelling on all hosts. Without `--remote`, `status` reads only the local
filesystem; use `--host` for an owner-only view.

```bash
python3 -m Mallory.native_graphchecker_dispatch status \
  --config-root /ABS/CONFIG_ROOT --state-root /ABS/NATIVE_STATE_ROOT \
  --remote --format tsv --out /ABS/data/mallory/native-102-results.tsv
```

The table always retains the 102-case denominator. Each row includes source
file, function, line, check code, original JUnit, owner, elapsed JUnit time,
fault trials, strict injections, post-fault target retention, exact target
throws, candidate count, and receipt path. `tested_candidate` and
`tested_no_target_throw` require a closed native budget, reached healthy
target, and audited original SessionReader/ClosurePlanner summaries. A closed
budget with no strict target-retained fault trial is `tested_inconclusive`.
`native_blocked` is terminal but not a completed fuzz check.

For a case with no suitable **original cluster JUnit**, record a reviewed
terminal disposition in a separate JSON file, then pass `--reviews FILE` to
both `run-next` and `status`:

```json
{
  "schema_version": 1,
  "no_eligible_original_cluster_junit": {
    "HBASE-32": {
      "reason": "Source review found no original cluster test reaching the target",
      "evidence_paths": ["/ABS/path/to/source-review.md"]
    }
  }
}
```

The review file is accepted only when every evidence file exists. This
disposition is terminal for scheduling, but `native_tested_complete` remains
false. It cannot override an existing native checkpoint.

The terminal audit checks the recording-derived admission, pinned weave and
static scope files, exact per-trial fault plan and ordered `FAULT_DOOR` /
`FAULT_APPLIED` receipts, landed native session bytes, target occurrence in
the original closure, target throw receipts, and recomputed graph delta. An
assertion failure or JUnit exit code cannot stand in for `TARGET_THROW`.

Receipt-level tests (no live distributed JUnit):

```bash
python3 -m unittest Mallory.native_graphchecker_dispatch.test_checklist -v
```
