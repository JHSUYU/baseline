# Completed Solr cases: fault actor identity audit (2026-10-07)

Independent, read-only review of the **13 Solr cases currently marked
`quality_complete`**. I inspected the final probe/selector source, campaign
plans, and at least one raw applied-fault/target sequence for each high-risk
family. This review does not alter case statuses or discard old trials.

## Decision for the checklist owner

Temporarily revoke `quality_complete` for **SOLR-01, 05, 06, 07, 10, 18, 19,
21, 31, 34, 39, and 40**. SOLR-39 and SOLR-40 reuse the SOLR-10 campaign and
have the same selector gap. The old data show real injected exceptions and
subsequent target checks; they do not meet the requested cross-run **runtime
actor identity** standard. Mark them `actor_audit_pending` (or equivalent)
until a corrected probe/selector and separate V2 effective-trial count are
reviewed. Preserve every old plan, trace, coverage result, duration, and bug
candidate as **legacy coarse-identity evidence**. Do not add old trial counts
to V2's denominator.

**SOLR-15** can remain a reviewed *positive protective control*. Its original
multi-node chaos JUnit reached the exact target throw under two ordered native
ZK faults. The raw trace/replay identify the same *logical parent leader*
live-znode path, both faults occur in one thread, and source/original test
review establishes a deliberate recovery abort. This supports that specific
outcome, not a claim that its broader one-Jetty ZK campaign has per-client
actor identity. See the case's
[`native-chaos-fault-02/audit.json`](../cases/SOLR-14/independent/supplemental/shardsplit/native-chaos-fault-02/audit.json)
and [`solr15-native-candidate-source-review.json`](../cases/SOLR-14/independent/supplemental/shardsplit/solr15-native-candidate-source-review.json).

## Path/callsite selectors: SOLR-05/06/07/10/19 and shared 39/40

These probes all enter `FeedbackProbe.io(String operation, String path)` and
count hits across the embedded cluster JVM. Their I/O trace records sequence,
time, operation, path, and sometimes callsite, but no `SolrZkClient` receiver,
reader, logical node, or physical node. The exception and later target check
therefore establish **temporal order only**. The original workloads create
multiple Jettys: `AddReplicaTest` uses 3, `TestPullReplica` uses at least 2,
and `TimeRoutedAliasUpdateProcessorTest.test` uses 4.

| Case | Final selector source | Raw example: applied exception → later target check |
|---|---|---|
| SOLR-05 | [`FeedbackProbe.java:88`](../cases/SOLR-05/probe/FeedbackProbe.java), lines 88–119: operation/path/ordinal; callsite only logged | [`trial-003/events.tsv`](../cases/SOLR-05/evidence/campaign/trial-003/events.tsv): `GET_DATA /collections/testAddMultipleReplicas/state.json` ordinal 44 at seq 784 → `core_node14` check seq 902 |
| SOLR-06 | [`FeedbackProbe.java:92`](../cases/SOLR-06/independent/probe/FeedbackProbe.java), lines 92–123: operation/path/global ordinal plus caller, but still no actor | [`trial-003/events.tsv`](../cases/SOLR-06/independent/evidence/campaign/trial-003/events.tsv): `GET_DATA /collections/pull_replica_test_create_delete/state.json` ordinal 46, `ZkStateReader.fetchCollectionState` at seq 1484 → shard2/core_node11 and other replica checks from seq 1595 |
| SOLR-07 | [`FeedbackProbe.java:88`](../cases/SOLR-07/independent/probe/FeedbackProbe.java), lines 88–119: operation/path/ordinal; callsite only logged | [`trial-002/events.tsv`](../cases/SOLR-07/independent/evidence/campaign/trial-002/events.tsv): same collection-state `GET_DATA` ordinal 67 at seq 1062 → replica_p13 check seq 1093 |
| SOLR-10, 39, 40 | [`FeedbackProbe.java:88`](../cases/SOLR-10/work/probe/FeedbackProbe.java), lines 88–119: operation/path/ordinal; shared run | [`trial-001/events.tsv`](../cases/SOLR-10/work/evidence/campaign/trial-001/events.tsv): `SET_DATA /aliases.json` ordinal 2 at seq 3112 → SOLR-10 `myalias` check seq 3122 and SOLR-40 check seq 3145 |
| SOLR-19 | [`FeedbackProbe.java:88`](../cases/SOLR-19/independent/probe/FeedbackProbe.java), lines 88–119: operation/path/ordinal; callsite only logged | [`trial-001/events.tsv`](../cases/SOLR-19/independent/evidence/campaign/trial-001/events.tsv): collection-state `GET_DATA` ordinal 72 at seq 1012 → replica_t12/core_node17 check seq 1043 |

In SOLR-06 the caller is checked at injection but its hit counter is still
incremented for every operation/path hit before the caller predicate. A caller
site is shared by different `ZkStateReader` instances across nodes; it does
not name the reader. The other four probes do not check the logged caller at
all. The target event does carry the collection/shard/replica or alias value,
but the I/O event has no field to join it to the same actor. These cases
cannot be repaired by recounting the existing TSV files.

## Other completed cases

**SOLR-01 (three-Jetty HTTP client).** The target is
`BaseHttpClusterStateProvider.getAliases` after LISTALIASES requests to live
nodes. [`FeedbackProbe.io`](../cases/SOLR-01/independent/probe/FeedbackProbe.java)
logs the HTTP `endpoint` at lines 87–95, but lines 98–100 match only operation,
resource, call ordinal, and attempt ordinal. The endpoint's runtime URL is
not normalized into a stable node/role identity and does not participate in
the predicate. In [`trial-001/events.tsv`](../cases/SOLR-01/independent/evidence/campaign/trial-001/events.tsv),
the injected first attempt at seq 4 is sent to `127.0.0.1:41363`, the second
attempt at seq 5 uses `127.0.0.1:34789`, and the target check follows at seq 6.
The exact destination of the selected attempt across JUnit runs is unproved.

**SOLR-18 (two-Jetty alias manager).**
[`Solr18Probe.aliasIo`](../cases/SOLR-18/independent/src/Solr18Probe.java)
matches operation, path, normalized **thread-name role**, and ordinal (lines
42–47, 80–91). It does not include the `SolrZkClient` receiver or the
`AliasesManager` object; the latter's `identityHashCode` appears only on target
events. In `/users/ZhenyuLi/solr18-independent-runs/trial-002/events.tsv`,
plan `SolrZkClient.getData:/aliases.json:zkCallback-N-thread-N@@1` is applied
on `zkCallback-37-thread-3` at seq 22. The same normalized role occurs on
callbacks 35 and 58 at seq 24–25; the selected target manager
`1452200188` reaches its equality guard on callback 58 at seq 26. The trace
cannot join the faulted callback to that manager's ZK reader. This is a
concrete within-run role collision, not just a hypothetical cross-run risk.

**SOLR-21 (one Jetty; smaller residual gap).**
[`Probe.nativeEntry`](../cases/SOLR-21/independent/src/research/solrreload/Probe.java)
uses a reload-core or collection path source, callsite, path, and ordinal;
`physicalNode` is emitted after the match (lines 153–203). The 80-plan state
contains 175 applied steps: 149 `SOLR/RELOAD_CORE/...` and 23 collection
steps have a logged physical node matching the exact target core in the same
run. Three collection steps, trials **12, 66, 72**, have empty
`physicalNode` in both healthy seeds and the faulted run; all three trials
were counted as strict and post-target. The original JUnit uses
`configureCluster(1)`, so this is a client/reader provenance gap rather than
a demonstrated wrong-Jetty fault. The existing 80/80 target-retaining count
cannot establish 80/80 actor-matched trials. Raw traces are on node2 under
`cases/SOLR-21/independent/campaign/trials/` (see state trial numbers 12,
66, 72); retain the other within-run node matches as evidence.

**SOLR-31 (multiple Jettys).**
[`Probe.nativeEntry`](../cases/SOLR-31/independent/src/research/solrforce/Probe.java)
matches callsite, request shard or collection-path source, resource, and
ordinal; the physical node is logged only after matching (lines 151–195).
Its 80-plan state contains 194 selected fault steps, 32 collection-scoped;
21 selected step keys occur on **2–4 distinct physical nodes** in the second
healthy seed. Raw node2 trial 3 trace
`cases/SOLR-31/independent/campaign/trials/0003-01171de540482340fe7e/attempt-01/events.jsonl`
applies `LeaderElector.checkIfIamLeader#getChildren` at seq 1637 on
`n:127.0.0.1:38235__%2Ftg` with collection-only source. The target force
leader guard follows at seq 2794, but its event has no physical node. This
does not bind the fault to the target request's server/reader.

**SOLR-34 (four data Jettys plus coordinator).**
[`Probe.nativeEntry`](../cases/SOLR-34/independent/src/research/solrcoord/Probe.java)
matches callsite, coordinator-request or collection-path source, path, and
ordinal; it logs but does not match the physical node (lines 152–199).
Its 80-plan state contains 190 selected steps, **81 collection-scoped**;
7 selected step keys occur on two physical nodes in the second healthy seed.
Raw node2 trial 3 trace
`cases/SOLR-34/independent/campaign/trials/0003-0017e75a184fd9842a28/attempt-01/events.jsonl`
applies a collection-scoped `ZkStateReader.LazyCollectionRef.get#exists`
at seq 1380 on `n:127.0.0.1:43609_solr`; the exact synthetic-collection
guard follows at seq 1500 on **different node** `127.0.0.1:35977_solr`.
The timing alone cannot establish the fault's relationship to that request.

## Counting and next step

`strict_injection` in these existing result files should be read as
**selector-level** strictness. `target_after_fault` means the named target
check ran later. Neither count should be silently presented as actor-matched
effective trials. Coverage and I/O feedback are real observations from the
original JUnit runs and remain useful for V2 prioritization.

A minimal V2 passes the actual `SolrZkClient` receiver to the ZK probe and
registers it with a stable `ZkController`/reader role and logical node or
replica. Include actor identity in both ordinal counting and the fault
predicate, and exclude unresolved actors. HTTP faults should match a stable
logical destination node/role in addition to call/attempt. Alias callbacks
must bind the client/manager instance, not only the thread-name pattern.
Calibrate unchanged healthy cluster JUnit runs, re-run to the existing
per-case effective budget with separate V2 checkpoints, and audit the exact
post-fault target identity. No new-bug conclusion follows from this audit.
