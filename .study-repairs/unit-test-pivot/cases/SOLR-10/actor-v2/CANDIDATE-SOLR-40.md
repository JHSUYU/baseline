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
guard `RoutedAliasUpdateProcessor.getAliasProps:132-134` reads an empty
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
| Campaign trial 36, physical `jetty:node4` reader | yes | yes | present | 18.867 s | `evidence/campaign-v4/trial-036/` |
| Campaign trial 163, three ordered faults on `jetty:node2` | yes | yes | present | 20.221 s | `evidence/campaign-v4/trial-163/` |
| Campaign trial 271, collection-state read then alias watch read on `jetty:node3` | yes | yes | present | 20.791 s | `evidence/candidate-solr40-v7/trial-271/` |
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
alias synchronization or unresolved-alias retry. SOLR-12258 even discusses a
historical failure of this same test's V2 collection-configuration request;
its described endpoint and mechanism differ from the post-create routed
`/update` guard in this trial. [SOLR-13059](https://issues.apache.org/jira/browse/SOLR-13059)
tracks a separate `testSliceRouting` failure to see a newly created
collection. These issues do not directly document the one-shot alias watch
read loss reproduced here. This is a scoped duplicate check, not proof of
novelty. The injected exception is a one-shot
application-level `ConnectionLossException`; a production ZooKeeper
disconnection, later client reconnect, or other watch registrations might
change recovery behavior. The failure and exact target condition are proven
for the unchanged four-node embedded-cluster test under this fault model.
In particular, `SolrZkClient.getData(..., retryOnConnLoss=true)` normally
passes the underlying ZooKeeper read through `zkCmdExecutor.retryOperation`.
This probe throws at method entry, so it models a **final visible I/O failure**
and bypasses that internal retry interval. A full client reconnect invokes
`ZkStateReader.createClusterStateWatchersAndUpdate`, which calls
`refreshAliases` and re-registers the alias watch. Those paths may repair a
real disconnection before the next update request; the present trial does not
establish behavior for every production network outage.

The campaign trial-18 raw trace SHA-256 is
`778d1ce04f02b7ce0dc252886c4a81d99ba6548de8ea8e166d1b744c3c285501`;
its JUnit log SHA-256 is
`c52a7630403900364b59b6ee433b4d18cd42c029cd458b3bb6800abc86b28987`,
and its retained ZooKeeper transaction-log SHA-256 is
`0f8aa55315abb1d3ff3e8c4ecbe41915f55dab0530d9c17fe1866fe80621fe9c`.
The three replay transaction-log hashes are in their per-run receipts.
Campaign trial 36 independently reached the same selected guard on another
physical reader; its ZooKeeper transaction-log SHA-256 is
`f71bfb1eb252a35fc1699cdf178a44cc06d942e1af2e7be33d27398d84d5ae92`.
Trial 163 applied `GET_CHILDREN_STAT` and `EXISTS_WATCH` faults on collection
state, then a final `GET_DATA /aliases.json` failure in
`AliasesManager.process`, all on the same live `jetty:node2` client and
manager. The subsequent guard took the same empty-properties branch and the
unchanged JUnit received the same routed-alias 500. `CREATEALIAS` returned
success and the retained ZooKeeper transaction log contained
`collection.myalias` and `collection_metadata.myalias.router.name=time`;
that log's SHA-256 is
`5ea4c46e2e3b3e876f6f2d6d8f0326d09df40f61176650129a9ccf0d8712e28d`.
The raw trace SHA-256 is
`d0aa02c76244884181fd321723f80fdb48a955f5fe14c82ac37e031c95163485`.
This is additional evidence for the same selected cache-miss candidate,
not evidence of a distinct bug; the three-fault plan has not been separately
replayed. Node2's campaign checkpoint is frozen after trial 189. The
single-writer continuation runs on node1 from the verified migration receipt,
using `evidence/campaign-v4/state.json` there. The node1 V7 amendment adds
52 healthy-trace-backed `LazyCollectionRef#get` occurrences for SOLR-39;
it leaves the SOLR-40 target oracle and earlier plans unchanged. The
boundary, source hashes, raw pilot runs, and actor-drift classification are
recorded in `evidence/campaign-v4/node1-handoff-calibration/v7-pilot-audit.json`.

Trial 271 is another instance of the same cache-miss mechanism. Both planned
faults were applied in order to one live `jetty:node3` client and manager:
first the collection-state `EXISTS_WATCH`, then the alias watch callback's
`GET_DATA /aliases.json`. The later SOLR-40 target on that same reader saw
empty properties, and the unchanged JUnit received the routed-alias 500.
`CREATEALIAS` returned status 0; the retained ZooKeeper transaction log on
node1 contains `collection.myalias` and `router.name=time` (log SHA-256
`b4265e1a2512b27b54810d56a9a44d2f7e3bde53351fa2ada58c7bfe5ca3d01b`).
The two-fault selector has not been separately replayed. Its source-level
interpretation follows the single-fault replays and controls below; it does
not establish a distinct or newly reported issue. The
`evidence/candidate-solr40-v7/trial-271-review.json` receipt records exact
trace, JUnit, JaCoCo, source, and transaction-log hashes. The raw trace,
JUnit log and JaCoCo file are mirrored on node0; the original ZooKeeper log
remains on node1.

## Isolated cache-refresh control

To test whether the empty local cache actually causes the selected exception,
we copied the Solr source and V4 class directory to a separate build path on
node2. The only production change was in `getAliasProps`: when the local alias
properties are empty, call `aliasesManager.update()` and reread the same map
before the existing target marker and guard. This variant kept the original
JUnit class and fault hook byte for byte identical. Its route class SHA-256 is
`1267cbbaa701b754a6eed163310567e5dde2d4fff70ed54752520f2f12eb4c4c`;
the unchanged original JUnit and hook hashes are in
`evidence/causal-control-v4/build-receipt.json`.

Five fresh runs with the same `jetty:node3` watch-read selector all injected
strictly. Four reached SOLR-40 on the faulted live reader; none took its
empty-properties branch. In three of the four, a same-client
`AliasesManager.update#getData` appeared between the injected failure and the
first same-reader target check, which then reported properties present. The
fourth already saw present properties without a control-path refresh. Three
of the four same-reader JUnit runs passed; one failed later with a different
`expected:<4> but was:<2>` assertion and no SOLR-40 exception. The fifth run
routed the post-fault target to another reader and does not test this guard's
same-reader causal path. Therefore this control supports the local-cache
mechanism for the selected exception, while making no claim that one refresh
repairs every consequence of the injected fault.

The complete five-run classification, class/source hashes, and raw trace,
JUnit, and JaCoCo SHA-256 values are in
`evidence/causal-control-v4/summary.json`. A passing same-reader control run's
raw `control-003/{events.tsv,junit.log,jacoco.exec,receipt.json}` is retained
here; all five raw runs remain on node2 under the same evidence directory.
`probe/causal_control.py` rebuilds the variant only in its isolated source
and class directory.

## Lower-layer retry control

A second independent build moved the synthetic `ConnectionLossException`
inside the underlying `keeper.getData` call for one `jetty:node3`
`/aliases.json` watch read. The original `SolrZkClient.getData` entry hook
observed the call without injecting; its real `ZkCmdExecutor.retryOperation`
made four failing attempts before returning the final exception. This tests
the retry behavior omitted by the V4 entry hook. The unchanged test and
`RoutedAliasUpdateProcessor` classes retained their V4 hashes; only the
isolated `SolrZkClient` and probe classes changed. Exact hashes are in
`evidence/lowlevel-control-v4/build-receipt.json`.

Three fresh runs exhausted all four underlying attempts on the same live
reader. None reached SOLR-40 **after the fourth failure**. The test did reach
SOLR-40 on that reader during the retry interval, but all those checks saw
present properties: another `AliasesManager.update#getData` refreshed the
same local cache before the first target check in each run. Two JUnit runs
passed; the third failed a different `expected:<4> but was:<2>` assertion,
without a SOLR-40 exception. This control therefore neither reproduces nor
refutes the post-failure stale-cache outcome when the real retry machinery
runs: the unchanged workload does not present a same-reader target after
retry exhaustion in these three trials. It narrows the claim to the original
injection model. All retry markers, target orderings, natural refreshes,
JUnit outcomes, source hashes and raw trace/JaCoCo SHA values are recorded in
`evidence/lowlevel-control-v4/summary.json`; a representative raw run is
retained alongside it. The worker retains all three raw runs.

## Trial 481 and an independent exact-plan replay

Campaign trial 481 applied two ordered faults on one live `jetty:node1`
`SolrZkClient` and `AliasesManager`: occurrence 15 of the collection-state
`LazyCollectionRef#get` watch check, then the first subsequent
`AliasesManager.process#getData("/aliases.json")`. The same reader later
reached the SOLR-40 missing-properties guard and exception. Its unchanged
JUnit returned a routed-alias 500 after `CREATEALIAS status=0`; the retained
ZooKeeper transaction log contains the created alias and `router.name=time`.
This is the same selected cache-miss mechanism as trials 18, 36, 163 and 271,
not a second bug. The original trial trace, JUnit log and JaCoCo SHA-256 values
are in `evidence/candidate-solr40-v9/trial-481-review.json`; its original ZK
transaction log remains on node1 under `evidence/campaign-v4/trial-481/scratch`.

Three independent runs of the **exact trial-481 selectors** used the unchanged
test and original V4 hook. All three strictly injected both faults into the
same live client and manager. Two reached the missing-properties branch on
that reader and failed the original JUnit; the third saw present properties
and passed. Both failing runs retained `/aliases.json` transaction records
with `collection.myalias` and `collection_metadata.myalias.router.name=time`.
The full per-run identities, guard outcomes and raw file hashes are in
`evidence/candidate-solr40-v9/{summary.json,trial-481-review.json}`. Their
original ZooKeeper logs remain on node1 in each replay's `scratch` directory.

## Trial-481 lower-layer retry comparison

An isolated build retained the original JUnit and routed-alias production
class byte for byte. It moved the second synthetic failure from the
`SolrZkClient.getData` entry to its underlying `keeper.getData` call, so the
real `ZkCmdExecutor.retryOperation` runs. The isolated classes and source are
under `~/solr40-lowlevel-trial481-v9` on node1; class hashes are in
`evidence/lowlevel-trial481-v9/build-receipt.json`. In two exact-plan runs,
the physical reader executed fewer than 15 matching collection-state I/O
operations. Neither first fault applied, so these runs give no result about
the lower-layer path.

We then used occurrence 10 of the **same** collection-state I/O callsite,
path, and physical actor, explicitly labelling the selector variation. All
three runs applied that first fault and reached the lower-layer alias watch
read on the same live reader. Runs 1 and 3 each logged four underlying
`ConnectionLossException` attempts, consistent with retry exhaustion, and
had no same-reader target check after them. Run 2 reached the missing alias
properties guard and JUnit 500 about 210 ms after the first lower-layer
failure. Since `ZkCmdExecutor` delays its next retry by 1500 ms, that target
occurred **during** the retry interval, before exhaustion; only one attempt
was recorded before the test failed. Its ZK log also contains the persisted
alias metadata. `evidence/lowlevel-trial481-v9-ordinal10/control-audit.json`
separates these outcomes and hashes every raw trace, log, JaCoCo file and
receipt. This control shows an overlapping target check can observe stale
metadata during retry, but it does not demonstrate the same target after an
actual network disconnection has exhausted Solr's retries. Novelty remains
pending and this candidate is not marked as a confirmed new bug.
