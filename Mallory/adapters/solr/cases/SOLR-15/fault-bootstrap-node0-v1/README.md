# SOLR-15 same-parent fault bootstrap

This isolated package keeps the unchanged Solr 8.11.4
`ShardSplitTest#testSplitWithChaosMonkey` JUnit and the pinned Mallory
target-absent controller and path-aware agent. The healthy run is intentionally
**target absent**. `source-review.md` explains the source condition and the
earlier CrashFuzz two-fault replay on the same JUnit.

At runtime, `seed_selector.py` discovers the current run's parent leader live
znode by following `SplitShardCmd.split`'s line-164 and line-523 caller doors
to their path-aware native `SolrZkClient` events on one actor, thread, split
occurrence and registered shard address. The first candidate is the native
door immediately under the second caller lookup. If its typed
`ConnectionLossException` yields a same-split, same-path native retry, the
second candidate adds a fault at that retry. The planned fault points include
actor, epoch, site and door ordinal. Each trial rechecks the actual
`FAULT_MATCHED` and `FAULT_APPLIED` path against **that trial's** parent
leader path. This matters because Jetty ports, and hence literal znode names,
can change across JUnit trials. A path or ordering mismatch stops the
bootstrap and is not credited as a target-retaining trial.

The pinned agent matches site/actor/epoch/ordinal before applying a fault and
records the ZooKeeper path in the receipt; it does not prefilter by path. The
case-local post-trial gate rejects any off-path application. No path match is
claimed merely from the point ordinal. After an effective faulted run first
observes exact `SplitShardCmd.split@536`, the pinned core builds its causal
graph and coverage feedback from that trace, binds the target actor, and
continues with its usual scheduler. Without that exact observation, the run
stops after the same-path two-fault attempt. Reproducing the line-538 throw
would be a candidate observation; the earlier source review classifies this
specific abort as expected protection, not a new bug.

Budget: at most 12 fault trials, 2400 seconds overall, 480 seconds per trial,
at most three faults per sequence. Only the first two fault trials may use
the target-absent bootstrap; later trials require an observed exact target.
The package uses a fresh output directory, retains per-trial receipts and
checkpoints for resume, and uses the existing node0 Solr/ZooKeeper locks.

Offline checks:

```sh
python3 -B run_campaign.py --preflight-only
python3 -B -m unittest -v test_seed_selector.py
```

Runtime execution requires a separate node0 steward GO receipt matching
`admission-full-node0.json` with `go=true`. No JVM has been launched by this
package. No checklist row should be promoted until the faulted target and
resource receipts are audited.
