# SOLR-40: routed alias cache misses after a lost alias watch read

Status: **reproduced fault-induced failure candidate; novelty not yet established**.
The unchanged `TimeRoutedAliasUpdateProcessorTest.test` uses its original
four-node embedded cluster. The tested source is Solr 8.11.4 commit
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. The original JUnit class
SHA-256 is `288ade17cb538b6226d1a61b863569a2b7bace75a228e58d60f18d5d2fed5749`,
and the actor probe class SHA-256 is
`8146a455d16ca8c3702e7180d388fb60a9a428ae0c49045b876e54ca529c8947`.
Two original and two instrumented healthy runs passed, reached SOLR-40, and
recorded no target exception. Their raw traces, logs, JaCoCo data and hashes
are under `evidence/healthy-*-v4-*` and `evidence/healthy-summary-v4.json`.

## Trigger and observation

The one-fault plan injects `KeeperException.ConnectionLossException` at the
first `SolrZkClient.getData("/aliases.json")` from
`ZkStateReader$AliasesManager.process:2312` on the actual `jetty:node3`
client. The hook records the live Solr node, `SolrZkClient`, and
`AliasesManager` identities. In the failing executions, the later SOLR-40
guard `RoutedAliasUpdateProcessor.getAliasProps:133-135` reads an empty
local `myalias` properties map on **that same client and manager** and throws
`RoutedAlias.newAliasMustExistException`. The `/update` request returns 500,
and the unchanged JUnit fails on its first document add after initial
`CREATEALIAS`.

The embedded ZooKeeper transaction logs retained for each failing run contain
`/solr/aliases.json` with `collection.myalias` set to the created collection
and `collection_metadata.myalias.router.name=time`. The original candidate's
JUnit log shows `CREATEALIAS status=0` at 15281 ms followed by the failing
`/update` at 15360 ms. The alias creation command returns only after its
`setData` succeeds. This supports a persisted alias with an out-of-date
node-local cache, rather than a failed alias write. The target hook directly
observes the empty local properties map; it does not inspect the full cache.

| Evidence | Strict injection | Same-reader target exception | ZK alias metadata | JUnit elapsed | Raw receipt |
| --- | --- | --- | --- | ---: | --- |
| Campaign trial 18 | yes | yes | present | 19.766 s | `evidence/campaign-v4/trial-018/` |
| Fresh replay 5 | yes | yes | present | 17.872 s | `evidence/candidate-solr40-v4/replay-005/` |
| Fresh replay 7 | yes | yes | present | 17.721 s | `evidence/candidate-solr40-v4/replay-007/` |
| Fresh replay 8 | yes | yes | present | 18.326 s | `evidence/candidate-solr40-v4/replay-008/` |

Ten fresh JUnit replays of the **same** fault selector all matched and applied
the fault. Seven reached SOLR-40 on the faulted client; three of those reached
the empty-properties branch and failed. The other runs either routed the
update to another client, updated the alias cache before the guard, or had the
alias writer on the faulted node, where `setIfNewer` populated its cache.
Thus the condition is timing and placement dependent. `replay_candidate.py`
and `evidence/candidate-solr40-v4/summary.json` retain the full ten-run
classification and SHA-256 of each trace, JUnit log, JaCoCo file, build,
original JUnit class and hook class. The raw ZooKeeper logs and their hashes
are retained on node2 in the corresponding failed-run scratch directories;
the receipts extract the exact alias values and transaction-log offsets.

## Source interpretation and limits

In Solr 8.11.4, `CreateAliasCmd.call:77-87` explicitly distinguishes the
immediate usability expected after **initial alias creation** from the normal
eventual propagation of later alias modifications. It sleeps 100 ms after
writing. `AliasesManager.process:2302-2322` catches the injected connection
loss after the watch read and logs a warning without retrying or visibly
re-registering the watch on that path. `RoutedAliasUpdateProcessor.getAliasProps`
then reads the cached aliases and fails on an empty map without a ZK refresh.
The same catch-and-return shape is still present in the local Apache Solr
checkout at commit `56ec140e3636d5f4150fa87fbf7103529536ac99`,
`solr/solrj-zookeeper/src/java/org/apache/solr/common/cloud/ZkStateReader.java:2091-2112`.
That current-source comparison supports the mechanism; it does not establish
that this is an unreported bug in current Solr.

The related closed ASF issues [SOLR-12256](https://issues.apache.org/jira/browse/SOLR-12256)
and [SOLR-12258](https://issues.apache.org/jira/browse/SOLR-12258) discuss
alias synchronization or unresolved-alias retry. They do not directly
document the one-shot watch read loss reproduced here. This is a scoped
duplicate check, not proof of novelty. The injected exception is a one-shot
application-level `ConnectionLossException`; a production ZooKeeper
disconnection, later client reconnect, or other watch registrations might
change recovery behavior. The failure and exact target condition are proven
for the unchanged four-node embedded-cluster test under this fault model.

The campaign trial-18 raw trace SHA-256 is
`778d1ce04f02b7ce0dc252886c4a81d99ba6548de8ea8e166d1b744c3c285501`;
its JUnit log SHA-256 is
`c52a7630403900364b59b6ee433b4d18cd42c029cd458b3bb6800abc86b28987`,
and its retained ZooKeeper transaction-log SHA-256 is
`0f8aa55315abb1d3ff3e8c4ecbe41915f55dab0530d9c17fe1866fe80621fe9c`.
The three replay transaction-log hashes are in their per-run receipts.
