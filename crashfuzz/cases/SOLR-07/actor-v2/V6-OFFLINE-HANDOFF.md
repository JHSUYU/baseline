# SOLR-07 V6 offline handoff

This is a standby continuation for the original
`AddReplicaTest.testAddMultipleReplicas` JUnit. It does not run while V5 is
active. The implementation is `campaign_v6.py`; its tests use temporary
synthetic trial directories and never start JUnit.

## Activation gate

V5 must exit normally with `effective_count < 80` and a final
`selected_trial_cap` or `plan_exhausted` checkpoint. A `queue_exhausted`
checkpoint is **intermediate** in V5: its controller still owns a possible
refill, so V6 rejects it. V6 also rejects an active V5 lock, a matching JUnit
process, a changed `state.json`, a pending next trial directory, any missing
or changed raw file, an unsealed or failing independent audit, or an empty
inventory. The source build, agent, calibration, and V5 scheduler hashes must
still match.

On the same node and absolute case path as the V5 campaign, after its process
has exited:

```sh
python3 campaign_v6.py freeze
```

This produces immutable `handoff-v6/state-N-SHA.json`, `raw-N-SHA.json`, and
`inventory-N-SHA.json`. The manifest SHA-pins six files for **every**
completed trial: `events.jsonl`, `run.json`, `trial.json`, `fault.properties`,
`junit.log`, and `jacoco.exec`. A repeated freeze with the same checkpoint is
idempotent. Each file is written to a temporary file, fsynced, sealed
read-only, then published atomically. A stale temporary file from an
interruption is not a frozen artifact.

Run the `audit_command` printed by `freeze` independently, review its
`errors=[]`, then seal the resulting audit file read-only (`chmod 444`). The
auditor recomputes strict injection, target outcomes, JaCoCo coverage, and
I/O families from raw trial evidence. V6 additionally checks the saved
fault plan, applied count, JUnit run identity, and each trial receipt against
the frozen ledger. `verify` repeats the entire handoff check without starting
JUnit:

```sh
python3 campaign_v6.py verify \
  --snapshot handoff-v6/state-N-SHA.json \
  --manifest handoff-v6/raw-N-SHA.json \
  --inventory handoff-v6/inventory-N-SHA.json \
  --audit handoff-v6/audit-N-SHA.json
```

Only after the independent audit and `verify` pass, `activate` with those same
four paths starts V6. Run it in a dedicated tmux session. If its process
stops, use `python3 campaign_v6.py continue`; never re-run `activate` against
an already activated state. The V6 controller holds both V5 and V6 locks for
its lifetime.

## Selection and recovery

The frozen V5 queue, completed trial ledger, and seen plan IDs are retained.
New root plans must be observed on the selected target actor and the same
SolrZkClient as a later `corePresent=true` target guard in a passing, strict,
effective V5 trial. Tier 0 requires the I/O to occur **after** the final
injected fault and before that guard in at least two distinct source trials.
One-witness post-fault roots and pre-fault roots are lower tiers. The provisional
selected-359 inventory had 15 tier-0 roots; the frozen inventory is rebuilt
when V5 actually ends. V6 schedules four shallow root/pair selections and one
eligible legacy selection per five attempts, with family and parent diversity.
New pair plans arise only from a passing, strict, effective one-fault parent.

At handoff selected count `N`, the explicit budget is 80 effective total or
`N+256` selected total, with at most eight faults in existing legacy plans;
new V6 plans have depth at most two. Plan identity includes the complete
target and ordered fault sequence. Already seen or queued identities are
never enqueued again. A target throw is a source-review candidate, not a bug
verdict.

If a process dies after writing `trial-(selected_count+1)` but before the
atomic state commit, `continue` refuses that unaccounted directory. Preserve
and review its raw evidence; do not rerun its trial ID. A completed V6 trial
does not fail the frozen V5 `N+1` gate: resume checks the **live** next ID,
the complete V6 trial receipts, and the frozen source SHA independently.

Offline validation:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_campaign_v6.py
```
