# SOLR-07 V5: offline handoff and productive-parent scheduling

V5 is a separate controller for the original `AddReplicaTest.testAddMultipleReplicas`
cluster JUnit. It uses the existing actor-bound ZK exception probe, exact target
selector, JaCoCo feedback, and V2 checkpoint format. It does not change the
JUnit, Java agent, healthy calibration, or live V4 scheduler.

## Current state and evidence

- V4 continues under its own checkpoint and budget. V5 has **not** been activated.
- `campaign_v5.py` and `test_campaign_v5.py` have offline tests; no test invokes
  a cluster JUnit. Re-run them on node2 after copying this revision.
- A read-only node2 check at V4 selected 116 found 59 queued descendants with
  18 distinct exact prefix parents. All 18 parents passed the raw V5 filter:
  exact injection, effective post-fault check, original JUnit success, no
  recorded target throw, and a later `corePresent=true` check on the same
  SolrZkClient/Jetty actor. Four of those 18 also had a same-thread guard.
  The live V4 queue can change; these numbers are not handoff counts.
- A read-only copy of V4 selected 176 had 36 effective trials and 50 queued
  descendants, with no remaining roots. From selected 150 to 176, V4 consumed
  26 plans and added nine children. At that recent rate, queue exhaustion is
  likely before the selected cap of 320, though future effective trials can
  change the rate. The V5 handoff therefore accepts a natural, audited
  `queue_exhausted` stop and backfills only previously omitted plans.
  The matching copied event traces show 828 distinct unqueued/unseen omitted
  plans across 32 parents at that snapshot. This is a planning inventory;
  final activation verifies the live run receipts, JUnit logs, and raw hashes.

## Selection rule

For four out of five selections, prefer a multi-fault child whose exact
`(target, sequence[:-1])` parent is a completed passing/effective trial with a
raw, same-client, same-actor, post-fault `corePresent=true` target check. The
fifth selection explores a one-fault healthy root. If no eligible child exists,
select a root. Other descendants are fallback only after both groups empty.
Within the selected group, balance tested first-fault I/O families and immediate
parents, prefer a direct same-thread fault-to-guard continuation, and age any
waiting entry to service after 20 selection rounds. `parent_gain=0` remains
eligible when the parent is effective; it only means no new coverage/I/O family.

The pass plus `corePresent=true` rule is an **active-compatible proxy**. The raw
Probe rows have no wall-clock timestamp that can prove their position relative
to the JUnit `###Ending` log entry. Target throws are never automatically bugs.
`paired_post_fault_throws` narrows a candidate to a guard after the final fault
on the same thread and controller, but source review, original JUnit outcome,
and exact replay must still rule out `CoreContainer.shutdown` teardown behavior.
The reviewed trial 38/48/64 throws remain teardown candidates, not new bugs.

## Switch only after V4's natural stop

1. Confirm the V4 tmux/process and any original JUnit JVM have exited after a
   completed trial. Do not terminate an in-flight JUnit. Verify `state.json`
   has `stopped=true` with `effective_budget_met`, `selected_trial_cap`, or
   `queue_exhausted`. For the last reason, the queue must be empty while both
   budgets remain unmet.
2. On node2, run `python3 campaign_v5.py freeze` from this directory. The
   command rejects a live V4 process or SOLR-07 JUnit, an unaccounted next trial directory, a
   duplicate/orphan queue plan, a changed V4 hash, and the V2 80-to-128
   extension write gap. It creates read-only `handoff-v5/state-*.json` and
   `raw-*.json` files. The latter pins SHA256 of every completed trial's event
   trace, run receipt, trial receipt, fault plan, JUnit log, and JaCoCo file.
3. Use the `audit_command` printed by `freeze` to run
   `audit_v2_checkpoint.py` against the frozen state. It must exit zero with
   `errors=[]`, and its selected/effective counts must match the snapshot.
   Set the resulting audit JSON read-only with `chmod 444 <audit-file>`.
4. Decide a **new explicit** effective-trial cap, selected-plan cap, and
   max-fault depth from the frozen audit. The first two must exceed the frozen
   effective and selected counts, respectively. Fault depth cannot decrease or
   exceed ten. Then run:

   ```text
   python3 campaign_v5.py activate \
     --snapshot handoff-v5/state-....json \
     --manifest handoff-v5/raw-....json \
     --audit handoff-v5/audit-....json \
     --effective-budget NEW_EFFECTIVE_CAP \
     --max-selected NEW_SELECTED_CAP \
     --max-faults NEW_MAX_FAULTS \
     --backfill-cap 512
   ```

   Activation rechecks all frozen raw hashes, fault-plan fields, JUnit exits,
   applied counts, V2 agent/calibration hashes, and both scheduler hashes.
   If the frozen queue is empty, it reads passing, effective, same-client parent
   traces and recovers only I/O points beyond V2's first three choices (first
   six when the parent had novelty), before the next matching target guard;
   that guard must report `corePresent=true`.
   If an explicit larger fault-depth cap opens a parent that V4 could not
   expand, its full post-fault window is eligible.
   It excludes completed plans and repeats, balances candidate parents, and
   adds at most `min(backfill cap, new selected cap - frozen selected count)`
   plans. The configurable per-fill cap defaults to 512 and cannot exceed 512.
   This retains the original actor, target, fault kind, and max-fault bound.
   If no such plan exists, activation leaves the live V4 checkpoint unchanged
   and reports `plan-exhausted`. Only after a nonempty audited queue is ready
   does it update the checkpoint and invoke the unchanged V2 runner. The
   frozen raw inventory remains SHA-bound for later refill. If V5 naturally
   empties its queue before its budgets, it re-derives still-unseen plans from
   that inventory and records each refill in the checkpoint. When no plan
   remains, it records `plan_exhausted` as the terminal reason. An exclusive
   V5 controller lock is held until that runner exits.

5. If the V5 controller later exits unexpectedly, use `python3 campaign_v5.py
   continue`. It verifies handoff hashes and the original frozen raw files.
   An existing `trial-(selected_count+1)` directory blocks restart because V2
   writes trial artifacts before its state commit. Reconcile that raw in-flight
   attempt manually against the last durable receipt; do not let V2 overwrite
   it or count it twice. The same exclusive lock prevents a second V5 runner
   from taking that number. Completed V5 trials must have raw files, matching
   trial/run receipts, and fault plans before continuation.

Do not run `activate` or `continue` while V4 remains active. The independent
offline tests are `python3 -m unittest -v test_campaign_v5.py`.
