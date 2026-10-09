# SOLR-36/37 fault actor identity audit (2026-10-07)

This is an independent, read-only audit of the original `ShardSplitTest#test`
campaign. It does not change the campaign, its checkpoint, or the case results.
The counts below are a **snapshot at 104 completed ZooKeeper plans** on node2 at
2026-10-07T03:31:52Z. The checkpoint `campaign/state.json` then had SHA-256
`986d1b8a9029d47834d317de0a599719d0cb50d3df8c9f8955697b9d007ec5c9`.
The live checkpoint may advance; use `trial_number <= 104` to reproduce these
snapshot counts.

## Finding

The ZooKeeper probe injects an exception inside a real `SolrZkClient` retry
callable, but its selector does **not** include the `SolrZkClient` object or a
stable physical/logical node identity. The ASM hook passes only `path` and
`api` to `Probe.nativeEntry` (`independent/src/research/solrsubshard/Agent.java`,
lines 39–55). `Probe.nativeEntry` derives `sourceKey` from thread MDC
`collection/shard/replica` or, when those are missing, from the collection part
of the ZK path (`Probe.java`, lines 165–175 and 193–214). Its ordinal key and
fault predicate use marker, call site, source key, path, and ordinal. The
`physicalNode` is written to the trace *after* matching; it does not constrain
the injection (`Probe.java`, lines 178–190 and 215–229).

This matters because the original JUnit embeds several Jetty nodes in one JVM.
Different nodes can execute the same ZK call site against the same collection
path. A `SOLR/COLLECTION/collection1` source key identifies a collection, not
the node or reader making the call. Existing `audit_identity.py` checks that a
target child reaches its guard after the fault; for collection-scoped faults it
explicitly accepts a guard on *either* child (lines 24–60). It does not audit
the ZK actor across healthy and faulted runs. Thus `strict_injection` currently
means selector-level matching, not necessarily same-actor matching for these
collection-scoped steps.

## Snapshot measurements and raw evidence

I read node2's `independent/campaign/state.json`, each completed plan's
`fault_sequence` and raw `attempt-*/events.jsonl`, and the frozen
`independent/healthy-02/events.jsonl`. The healthy trace SHA-256 is
`33a3d8e17a99980f30b0bc9b3915ecb0a2de5ef31d66a7a6e23d6e82769bf630`.
For each applied replica-scoped event, I compared its `physicalNode` after
removing the MDC `n:` prefix with the physical node logged by that **same
run's** `TARGET_ENTER` for the exact `collection/shard/replica`.

| Measure through trial 104 | Result | Meaning |
|---|---:|---|
| Completed ZK plans / applied fault steps | 104 / 245 | Snapshot, not the terminal budget |
| Replica-scoped steps with exact same-run child node match | 207 / 207 | Strong child-replica evidence in the observed run; still no ZK client object identity in the selector |
| Collection-scoped steps | 38 | No logical actor in the selector; one such step per affected plan |
| Selected step keys seen on at least two nonempty physical node strings in healthy-02 | 20 / 245 | Direct evidence that key alone can denote multiple nodes |
| Selected step keys with no nonempty physical-node sample in healthy-02 | 5 / 245 | No seed-node mapping for these keys |

The counts are over selected **steps**, so repeated keys in different plans
are counted repeatedly. The 20 and 5 groups are diagnostic and need not be
disjoint from the 38 collection-scoped steps. They do not by themselves prove
that any specific injected exception landed on the wrong node. They prove the
selector lacks the information needed to rule that out. The 207 same-run
replica matches do not prove that a particular `SolrZkClient`/`ZkStateReader`
instance was the one used in a seed or replay.

An inspectable example is trial 78: its plan selects
`ZkShardTerms.ensureTermNodeExist -> SolrZkClient.makePath` on
`/collections/collection1` with `sourceKey=SOLR/COLLECTION/collection1`.
The raw event is sequence 1087 in node2's
`independent/campaign/trials/0078-70db6987171e903945b7/attempt-01/events.jsonl`.
The [trial 78 source review](../cases/SOLR-36/independent/campaign/candidate-0078-review.md)
establishes that this event ran in a shard2 core's Jetty, whereas the later
SOLR-36 guard/throw ran on shard1_0/core_node11 on another Jetty. This gives
temporal order and an exact target throw, not a proven direct relationship.
The candidate was already classified as a protective retry, not a confirmed
new bug.

## Prepared HTTP stage

The separate parent-to-child HTTP probe takes the actual destination
`Replica` from `SolrCmdDistributor.Req`; it constructs the selector's
`sourceKey` from `collection/shard/child replica` and matches the target guard
to that same child (`rpc-stage/src/research/solrsubshard/Probe.java`, lines
170–209; `rpc-stage/fuzz_rpc.py`, `analyze`). That is stronger destination
identity than the collection-scoped ZK selector. In each of the two passing
healthy HTTP traces, each of the four command/child families has one observed
sender MDC shard/replica pair, `shard1/core_node3`. The healthy trace SHA-256
values are `ecc8b3065134015130f0444fcad89131cf7f52d32bb2b7cc18c6ca52cbb9e506`
and `476d10320159d02757933212dee4ed789abcca5a34675c3564348796561e2a4c`.
However, `senderShard` and `senderReplica` are logged in `detail`, not included
in the HTTP selector/ordinal. A future trial must verify the sender remains the
same, or add the logical sender replica to the match, before claiming strict
source-and-destination identity.

## Minimal correction

1. Pass the `SolrZkClient` receiver (`this`) from the ZK ASM hook into the
   probe. Register each `ZkController.zkClient` with its `ZkController` node
   identity and derive a stable logical actor/role from the node's actual core
   assignments. Include that actor in both the ordinal key and fault selector;
   do not inject when it cannot be resolved. Runtime port numbers are evidence
   for within-run validation but are not cross-run keys.
2. Calibrate two unchanged original healthy JUnit runs under the new agent,
   intersect exact actor-aware selectors, and give the corrected campaign a
   separate checkpoint and effective-trial denominator. Keep the earlier
   campaign as coarse-identity evidence without silently adding its 38
   collection-scoped plans to an actor-matched count.
3. For HTTP, record and match the parent sender's logical replica as well as
   the actual child `Replica`; retain the existing exact child target oracle.

This audit makes no new-bug claim. The HTTP stage and replica-scoped ZK traces
still provide useful evidence, subject to the stated identity limits.
