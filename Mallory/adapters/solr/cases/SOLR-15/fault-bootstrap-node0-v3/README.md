# SOLR-15 v3 checkpoint-safe continuation

V2 observed the exact protective `SplitShardCmd.split@536` check and line-538
throw after two resource-qualified `ConnectionLossException` faults at the
second parent leader lookup and its retry. Trial `r0003` replayed the same
plan, with a fresh parent `/live_nodes` path and JUnit 1/0/0. These are
observations of Solr's expected guard, not a new bug claim.

V2 ended with `fault_resource_mismatch` at `r0004`: the first two faults
applied to the parent path, but its ordinal-only third fault did not apply.
Its target observation cannot validate the three-fault plan. The pinned core
had 11 post-target depth-three candidates; `r0004` selected one, leaving 10.
The v3 offline replay reproduces the exact plans selected for `r0001` through
`r0004` and every saved checkpoint field before v2 cleared the queue. It then
replays `r0004` with no target or coverage credit, removing its two new edge
fingerprints. A fresh output copies the five original trial directories byte
for byte, starts at `r0005`, and retains their 444.302 seconds and four fault
trials against the original 12-trial, 2400-second budget. Neither valid
`r0002` nor `r0003` is rerun.

The ten queued plans include one dynamic-closure third fault at the bound
parent path and nine outside-closure exploration points. Every native
ZooKeeper third fault is checked against its actual path before injection.
The parent candidate binds the current trial's parent path; other native
points have an explicit literal resource, actor, epoch, occurrence and ordinal
from their source door. Nonnative points retain exact actor, epoch,
occurrence and ordinal. The outside-closure tier is recorded separately and
is not treated as a causal target closure. Cross-run occurrence tokens may
make some exploratory plans unmatched; those trials are dropped without
credit, not silently broadened.

The two `/overseer/queue` points come from `r0002` on shard-2. Each is
paired with its exact observed native path and feedback door event. That
feedback marks both outside the dynamic target closure, and the pinned
scheduler labels them `bounded_exploration`; v3 records those source event
IDs and graph labels in its reconstruction receipt. Their eligibility is
limited to this explicit exploration tier and exact runtime resource.

For each new trial, the controller independently verifies the first two
same-parent receipts, the third fault's resource or occurrence identity, and
an exact target check after all three applied faults on the selected
execution. A target exception candidate additionally requires the exact
line-538 throw after that check. An unmatched or invalid depth-three plan
consumes one trial slot, keeps `raw-result.json`, contributes no coverage or
edge novelty, and cannot spawn child plans. The full search remains incomplete
until the v3 run reaches its bounded terminal status and its receipts are
audited.

Offline checks:

```sh
cd Mallory/adapters/solr/cases/SOLR-15/fault-bootstrap-node0-v3
python3 -B -m unittest -v test_prepare_checkpoint.py
python3 -B run_campaign.py --preflight-only
cd agent && mvn -q test package
```

The v3 package uses the original unchanged
`ShardSplitTest#testSplitWithChaosMonkey`, a fresh output at
`data/mallory/solr15_fault_bootstrap_node0_v3`, the node0 Solr/ZooKeeper
locks, and a matching case-local steward GO receipt. Preparation and offline
tests launch no Solr cluster JUnit or fault campaign. V2 trial evidence and
its checkpoint are read only; source hashes are sealed in
`source-receipt.json`, and the reconstructed queue in
`reconstruction-receipt.json`.
