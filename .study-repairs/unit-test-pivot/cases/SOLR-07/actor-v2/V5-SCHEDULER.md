# SOLR-07 V5: offline handoff and productive-parent scheduling

V5 is a separate controller for the original `AddReplicaTest.testAddMultipleReplicas`
cluster JUnit. It uses the existing actor-bound ZK exception probe, exact target
selector, JaCoCo feedback, and V2 checkpoint format. It does not change the
JUnit, Java agent, healthy calibration, or live V4 scheduler.

## Current state and evidence

- V4 continues under its own checkpoint and budget. V5 has **not** been activated.
- `campaign_v5.py` and `test_campaign_v5.py` passed 10/10 offline tests both
  locally and on node2. No test invokes a cluster JUnit.
- A read-only node2 check at V4 selected 116 found 59 queued descendants with
  18 distinct exact prefix parents. All 18 parents passed the raw V5 filter:
  exact injection, effective post-fault check, original JUnit success, no
  recorded target throw, and a later `corePresent=true` check on the same
  SolrZkClient/Jetty actor. Four of those 18 also had a same-thread guard.
  The live V4 queue can change; these numbers are not handoff counts.

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

## Switch only after V4's natural budget stop

1. Confirm the V4 tmux/process and any original JUnit JVM have exited after a
   completed trial. Do not terminate an in-flight JUnit. Verify `state.json`
   has `stopped=true` with `effective_budget_met` or `selected_trial_cap`.
2. On node2, run `python3 campaign_v5.py freeze` from this directory. The
   command rejects a live V4 process, an unaccounted next trial directory, a
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
     --max-faults NEW_MAX_FAULTS
   ```

   Activation rechecks all frozen raw hashes, fault-plan fields, JUnit exits,
   applied counts, V2 agent/calibration hashes, and both scheduler hashes.
   Only then does it update the checkpoint and invoke the unchanged V2 runner.

5. If the V5 controller later exits unexpectedly, use `python3 campaign_v5.py
   continue`. It verifies handoff hashes and the original frozen raw files.
   An existing `trial-(selected_count+1)` directory blocks restart because V2
   writes trial artifacts before its state commit. Reconcile that raw in-flight
   attempt manually against the last durable receipt; do not let V2 overwrite
   it or count it twice.

Do not run `activate` or `continue` while V4 remains active. The independent
offline tests are `python3 -m unittest -v test_campaign_v5.py`.
