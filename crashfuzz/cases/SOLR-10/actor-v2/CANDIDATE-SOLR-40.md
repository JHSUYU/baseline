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
read loss reproduced here. [SOLR-12413](https://issues.apache.org/jira/browse/SOLR-12413)
concerns ignoring a manually recreated `/aliases.json` at startup because
its ZK version equals the initial local version; this trial uses the
Collections API and loses a runtime watch read after alias creation. This is
a scoped duplicate check, not proof of
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

## One underlying failure with the original retry, after V10b completion

After the 757-trial V10b campaign reached all three budgets, a separate
five-run control used the **unchanged original JUnit and routed-alias class**.
It retained the trial-481 collection-state callsite/path/physical `node1`
selector with occurrence 10, then injected **one**
`ConnectionLossException` from the underlying `keeper.getData` for that same
client/manager's `/aliases.json` watch read. The ordinary
`SolrZkClient.getData(..., retryOnConnLoss=true)` path invokes the original
`ZkCmdExecutor.retryOperation`; subsequent attempts call the real ZooKeeper
read. The old receipt field `unmodified_second_selector` identifies the
trial-481 reference selector but is *not* an additional plan fault in these
five runs. The isolated build and raw files are in
`evidence/lowlevel-single-retry-v10/`; the original source revision is
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. The JUnit class SHA-256
remained `288ade17cb538b6226d1a61b863569a2b7bace75a228e58d60f18d5d2fed5749`.

| Runs | Underlying alias read failures | Same-reader target after failure | Retry returned successfully | Original JUnit |
| --- | ---: | --- | --- | --- |
| 1–2 | 1 each | present properties at 453/488 ms | yes, about 1502 ms | pass |
| 3 | 1 | no subsequent same-reader target | yes, about 1502 ms | pass |
| 4–5 | 1 each | **missing properties at 184/189 ms**, target exception | no success before test teardown | fail, routed-alias 500 |

Every run applied the first fault and the one underlying alias read failure
on the exact same live physical node, client and alias manager. Both failing
runs retained ZooKeeper transaction records containing `myalias` and
`router.name=time`. Independent raw-file recount found zero discrepancies;
`evidence/lowlevel-single-retry-v10/control-audit.json` (SHA-256
`8a25ed89f97881d76f4a14afabd9ab5869315d4fdc2f675f920985d240982b13`)
records event order, elapsed milliseconds, JUnit outcomes, and all trace,
manifest, JUnit-log and JaCoCo SHA values. Node0 and node1 copies passed
the same audit.

The two failures occur **before** the 1500 ms retry delay expires. The test
then aborts and closes the embedded cluster, so these runs do not establish
whether the retry would later have succeeded or whether a watch would remain
lost. They do show that a single lower-layer read failure can delay alias
cache refresh long enough for the unchanged `/update` to reach the same
missing-properties guard and return 500. The passing runs show that timing
and prior cache state matter. This models a synthetic one-call ZooKeeper
read failure, not a measured production network disconnection. The
fault-induced observation is reproducible; novelty remains unconfirmed.

## F0-only and post-retry timing controls

An independent five-run negative control kept the **unchanged original JUnit**
and V4 actor hook and injected only the same occurrence-10 collection-state
`EXISTS_WATCH` fault (`F0`). All five runs strictly applied it; four reached
the SOLR-40 guard on the same physical node, client, and alias manager. All
observed properties were present, all five JUnit runs passed, and no target
exception occurred. This bounded control does not prove that `F0` alone can
never expose the failure, but it narrows attribution of the prior two-fault
observations. Raw files and identities are in `evidence/first-fault-only-v10/`.

The lower-layer five-run control above could not observe cache state after
retry in its two failing runs: the original JUnit aborts on the 500 before
the 1500 ms retry delay ends. To test that timing distinction, a separate,
clearly labelled **timing control** retained the original JUnit byte for byte
but added a bounded gate immediately *before* `getAliasProps` reads the local
cache. If the selected reader's one underlying alias read has failed, the
gate waits up to four seconds for that same client's real
`ZkCmdExecutor.retryOperation` to return successfully and then waits 100 ms
for `AliasesManager.process` to apply the data. It changes target timing by
design and is not a replay of the original production request schedule.

The clean V11b build hashes the probe, `SolrZkClient`, target processor, and
original JUnit class before every continuation. In five fresh runs, the same
`F0` and one underlying `/aliases.json` read failure applied on the same live
reader, and genuine retry succeeded. Four runs reached the same-reader
SOLR-40 check **after** retry success; every one observed present properties
and passed the original JUnit. The fifth had no subsequent same-reader target
check and passed. Thus, with this gate, the observed missing-properties
condition did **not** persist after the successful read and cache refresh.
It does not exclude a longer-lived failure after genuine retry exhaustion or
a different network/watch sequence. The full raw recount on node0 and node1
agreed at `evidence/control-audit-v11b.json` SHA-256
`d15f65762c7ce53c072ac88f1cab4d6fe059619e29c1e36bfbb300dfd0ac317f`.

The initial V11 continuation had a control-build error: recompiling its
probe removed the timing method while leaving the target class that invoked
it. Runs 2–5 failed with `NoSuchMethodError`; they are preserved under
`evidence/delayed-retry-v11/` with `INVALID-BUILD-REENTRY.json` and are
excluded from every SOLR-40 bug and timing count. V11b uses a separate clean
build and output directory.

Source review explains the boundary. `ZkCmdExecutor.retryOperation` catches
`ConnectionLossException` and sleeps 1500 ms before its next attempt;
`AliasesManager.process` sets the aliases cache only after `getData` returns.
`RoutedAliasUpdateProcessor.getAliasProps` reads that cache immediately and
throws when the selected alias has no properties. Its wrapper converts the
underlying `RoutedAlias.newAliasMustExistException` (503) to a 500 response;
the original JUnit update does not retry that request. Therefore the
two 184/189 ms failures in the unmodified-timing lower-layer control fit a
transient stale-cache window **during** retry. Neither these synthetic
one-call failures nor the delayed control demonstrate a permanent lost watch
after retry exhaustion or a real network disconnection. They strengthen the
reproduced candidate but leave novelty pending; `new_bug=false` remains.

## Alias-read-only control and terminal classification

The final isolated control removed `F0` entirely: the original JUnit and
`RoutedAliasUpdateProcessor` classes remained byte-identical, and there was
no V4 plan fault. A probe changed only the lower ZooKeeper call, throwing
**one** synthetic `ConnectionLossException` before `keeper.getData` on the
physical `jetty:node2` `AliasesManager` watch read of `/aliases.json`. The
original `ZkCmdExecutor.retryOperation` then ran. We chose node2 from both
fresh V4 healthy traces, where its alias watch read preceded a SOLR-40 check
on the same live client and manager. An exploratory node1 run did not reach a
postfault target on that reader and is preserved separately under
`evidence/alias-read-only-v12/`; it contributes no outcome claim.

Five node2 runs were completed with separate scratch directories and the
original JUnit. All five had exactly one underlying alias read failure and
zero plan faults. Trial 3 reached the same-reader SOLR-40 `missing` guard
**202 ms** after the underlying read failure, before the 1500 ms retry delay
ended; the target exception and original JUnit 500 followed. `CREATEALIAS`
returned `status=0` at 15031 ms, before the failing `/update` at 15130 ms;
the retained ZooKeeper transaction log contains `collection.myalias` and
`collection_metadata.myalias.router.name=time`. Trial 4 reached that reader's
guard after the fault with present properties and passed. The other three
had no postfault same-reader SOLR-40 check, and all passed. The five raw runs
were recounted on node0 and node1 with zero discrepancies; their shared
`evidence/alias-read-only-v12b/control-audit.json` SHA-256 is
`f25b01e821503789c6cf0d19aa04bcd25705306b3fab091d414fcee802ff6610`.

Three fresh exact-build replays used the same physical node2 selection, the
same isolated class SHA values, no `F0`, and a newly started original JUnit
cluster each time. Replay 1 again reached the same-reader `missing` guard
and original JUnit 500 before retry; alias creation returned success and its
ZooKeeper transaction log retained the routed metadata. Replay 2 reached
the same-reader guard with present properties and passed. Replay 3 had no
postfault same-reader check and passed. Its independent raw audit SHA-256 is
`8d6eab1cd85980ee62777b231f5d6b0cba2566527007a1df1708c26e099a11e3`.
The exact source and class hashes, trace, JUnit log, JaCoCo file, and retained
ZooKeeper transaction logs are in
`evidence/alias-read-only-v12b{,-replay}/`.

This source path supports a **reproduced, fault-induced transient stale-cache
failure candidate** even without the collection-state fault. The relevant
chain is `CreateAliasCmd.call:77-87` (initial creation expected to work after
its 100 ms propagation delay), `ZkCmdExecutor.retryOperation:68-96` (read
retry delayed 1500 ms), `AliasesManager.process:2302-2322` (cache update
only after that read returns), and `RoutedAliasUpdateProcessor.getAliasProps:
129-135` (checks local cached properties without refresh). The latter's
underlying 503 is caught by `RoutedAliasUpdateProcessor.wrap:119-124` and
returned as 500. `BaseCloudSolrClient:968-1005` retries communication errors
and selected 503 route errors, but not this 500; the failing original JUnit
log records `retry=0 ... commError=false errorCode=500`.

The timing gate showed present properties in four post-retry checks, whereas
both alias-read-only failures ended the JUnit before retry completed. Thus,
the evidence establishes an externally visible failed update in the
synthetic one-call fault model, but **does not establish a permanent lost
watch, post-retry failure, or an unreported issue in current Solr**. The
closed ASF issues compared above do not exactly describe this path, but that
limited duplicate search is not a novelty proof. We stop the bounded control
campaign here with `reproduced_candidate_novelty_pending`, `new_bug=false`.
