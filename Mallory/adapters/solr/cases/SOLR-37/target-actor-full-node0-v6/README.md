# SOLR-37 strict target-actor continuation

The target is `DistributedZkUpdateProcessor.doDefensiveChecks` at source lines
994–995. The check rejects a child shard range that is outside its parent
shard's range. The selected real I/O is `ZkStateReader.fetchCollectionState`
reading `/collections/collection1/state.json` from a `StateWatcher` callback.
The injected exception is ZooKeeper `ConnectionLossException`, which the
watcher catches. The JUnit workload is `ShardSplitTest#test` on Solr 8.11.4.

The sealed v5 pilot used a healthy run whose named target actor was shard-4.
Its r0001 and r0002 had exact matched/applied watcher faults at ordinals 33
and 31, followed by 100 and 116 same-actor target checks. Neither reached
the target throw. Its r0003–r0006 did not match a fault: the actual target
actor moved to shard-2 and shard-4 had only 18–20 watcher doors. This is
actor drift, not evidence that the candidate frontier is exhausted.

The raw r0003 trace, although its scheduled fault was unmatched, was a
fault-free execution of the target path. Offline graph reconstruction found
164 observed event-time paths on shard-2 from the qualified collection-state
watcher read through the exact published `ClusterState` reference, processor
consumption and field assignment to the @994 guard. The five qualified
shard-2 ordinals are 22, 26, 29, 31, and 33. The proof and exact v5 trace
digest are in `shard2-observed-closure.json`.

The v6 checkpoint import verifies the sealed v5 archive and individual
member hashes, retains valid trial IDs 0–2 and their coverage/edge state,
and keeps the next ID at 7. It discards the four unmatched attempts from
the resumed novelty state while preserving their sealed evidence. Neither
valid v5 fault sequence is queued again. The new frontier includes the five
shard-2 points, three unmatched shard-4 points, and the pending two-fault
shard-4 sequence. Each new trial analyzes the actual target actor without
the v5 shard-4-only feedback binding. The case-local audit still requires
the same named node, epoch, watcher resource and exact reader reference for
door, match and apply; post-fault @994 target checks must also have an
observed event-time path through that reader's exact `ClusterState`.

The cumulative budget is 17 fault trials and 3600 recorded trial seconds,
allowing up to 15 new fault trials after the two valid v5 trials. Depth is
at most three. Invalid plans consume budget but contribute no coverage,
causal edges or descendants. The controller has no GO by default.

Offline commands:

```sh
python3 run_campaign.py --preflight-only
python3 run_campaign.py --dry-run-reconstruct
python3 -m unittest -v test_run_campaign.py
```

Dispatch must issue the exact SHA-bound `admission-full-node0.json` receipt
and run this package in an isolated node0 tmux lane. The runner enforces
node0, source/runtime hashes, lane locks, memory and disk gates, and an
absence of another user JVM before it creates the v6 output or starts Java.
