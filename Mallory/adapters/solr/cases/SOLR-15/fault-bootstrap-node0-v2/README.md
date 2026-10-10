# SOLR-15 runtime-qualified parent lookup bootstrap

This isolated v2 package corrects the v1 selector's terminal mismatch. In v1
trial `r0001`, the planned native ordinal 42 applied at `/overseer/queue`
(`FAULT_APPLIED` event `:1595`), while the second `SplitShardCmd.split` parent
lookup was native event `:1898`, ordinal 47, at
`/live_nodes/127.0.0.1:42553_`. An ordinal from a prior run cannot identify
this operation when unrelated ZooKeeper calls shift its position.

The case-local agent makes the selection **before injection**. On one Java
thread, it observes the line-164 caller door, binds its immediately following
native `exists` path only if it is one direct child of `/live_nodes/`, then
requires the line-523 caller door on the same node, epoch and split occurrence.
Only the immediately following native door on that same path is a `second`
candidate. A `retry` candidate requires an applied `second` fault and the
same node, epoch, split occurrence, thread and bound path. Other native paths,
including `/overseer/queue`, cannot consume either selector fault. No desired
path means no fault. The plan's `solr15_parent_lookup` phase deliberately
replaces the cross-run `door_ordinal`; the observed ordinal remains in receipts
for diagnosis.

The controller still independently checks each trial's JUnit physical
shard registration, first and second caller relation, same parent path,
`SOLR15_PARENT_CANDIDATE` before `FAULT_MATCHED` and `FAULT_APPLIED`, strict
actor/epoch/occurrence/thread identity, and ordered second/retry receipts.
It credits exact `SplitShardCmd.split@536` only if observed after all selected
faults on that same execution. A missing retry or desired path ends bootstrap
safely; no target observation is inferred from fault application. A line-538
throw, if later observed, is Solr's expected protective abort per the v1
source review, not a bug claim.

This package retains the original `ShardSplitTest#testSplitWithChaosMonkey`,
the pinned target-absent controller, the v38 Solr adapter, 12-trial and
2400-second budget, and node0 lock/admission gates. Its output directory is
`data/mallory/solr15_fault_bootstrap_node0_v2`. It does not use v1 output for
runtime selection; v1 evidence is read only in preflight regression checks.

Offline verification:

```sh
cd Mallory/adapters/solr/cases/SOLR-15/fault-bootstrap-node0-v2
python3 -B -m unittest -v test_seed_selector.py
python3 -B run_campaign.py --preflight-only
cd agent && mvn -q test package
```

The sealed agent binary is `agent/release/mallory-agent.jar`; its source,
test receipt and digest are pinned in `agent/release/manifest.json`. The
isolated Java test suite passed 4/0/0/0. No Solr cluster JUnit or fault
campaign was launched while preparing this package. Runtime execution
requires a node0 steward GO receipt matching `admission-request.json` and
the case-local preflight. The faulted target and resource receipts must be
audited before any research outcome is claimed.
