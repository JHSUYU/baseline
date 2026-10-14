# SOLR-09 original GraphChecker context-boundary audit

This is a read-only reanalysis of pinned `DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup` healthy trial `r0000`. It does not replay JUnit, change the static plan or alter a running campaign.

## Evidence and root cause

The frozen trial is at `/proj/silentfailure-PG0/mallory/solr09-native-prep-v1/campaign-prep/campaign/trials/r0000`. Its `original-graph/summary.json` recorded 30 paired exchange receives, 0 call-stack fallback anchors, 17 pairs without a `REGION`-to-`REGION` edge, 5 region edge families and 5 closure edge families. The trace contains 159 ZooKeeper sends and 23 receives, plus 7 `SOLR_HTTP` sends and 7 matching receives. All seven HTTP sends are under original GraphChecker `ROLE.WAKE` or `ROLE.EXECUTOR_TASK` occurrence addresses. The old summarizer required a `REGION.*` producer and therefore omitted their causal handoffs even though the message pairs were observed.

This is a type distinction in the original engine, not a missing HTTP header. `OccurrenceAddress.ROLE_REGION` is explicitly work under no region; `Identity.roleOccurrence` and `RowRuntime.ambientActivation` record it as an ambient activation. The Solr GraphChecker source patch transports the producer endpoint through the HTTP request and imports it in `SolrDispatchFilter`. Five of the seven paired HTTP receives are followed by eleven exact selected Finalizer plan occurrences whose context names the corresponding producer endpoint and `SOLR_HTTP` transport. The other two pairs have no such selected receive anchor and remain unclassified. Pairing is unambiguous in this frozen trial.

The static receipt at `/proj/silentfailure-PG0/mallory/solr09-native-prep-v1/static-receipt.json` reports `communication_ports=0` and the recorded plan has 172 rows and nine catalog gaps. The skeleton's separate OUT/IN port inventory is not the receipt's selected communication-port count. The nine gaps include a Solr ZooKeeper `getData(...).return` admission gap. Neither an HTTP ROLE handoff nor a paired ZooKeeper receive proves that a missing ZooKeeper value-flow import reached the target check. This patch makes no such inference.

## General correction

`region_state_graph.py` now emits `contextBoundaryEdgeFamilies` for a paired `ROLE.*` sender to a selected `REGION.*` receiver only when the sender's exact endpoint address matches its physical source, its endpoint ID is unique among observed sends, the receiver has an exact `Anchor:<endpointId>@<transport>` context, and the send, receive and receiver activation occur in order. This is a typed context-to-region observation. It does not enter `edgeFamilies`, `closureEdgeFamilies`, `closureOccurrenceIds` or the fault-door membership filter. The existing `unmappedPairedExchanges` continues to mean pairs lacking a `REGION`-to-`REGION` edge, including these typed boundary pairs.

The region-state delta reports newly observed typed boundary families only when both healthy and faulted summaries contain the new field. The campaign novelty corpus stores these families separately from region closure edges and awards two points per new family versus four for a region closure edge. Repeating a family gives zero additional points. A legacy healthy snapshot with no boundary field earns no synthetic novelty on comparison.

## Frozen-trace regression

The offline regression verifies the saved plan, trace, manifest, target receipt, fault-event and engine JAR SHA-256 pins before computing a summary. The retired `/dev/shm` static sidecars are replaced only by their attested digest values and previously published exact selected occurrence IDs; no source resolver or runtime is launched.

| Frozen trial | Typed pairs | Typed families | Region edges | Closure edges | Legacy unmapped pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| SOLR-09 `r0000` | 5 | 7 | 5 | 5 | 17 |
| SOLR-07 `r0000` | 21 | 19 | 17 | 15 | 129 |
| HBASE-01 `r0000` | 0 | 0 | 0 | 0 | 258 |

The SOLR-07 and HBASE-01 rows are cross-case checks against overgeneralizing the Solr handoff. SOLR-07's region-edge totals also include the existing general exact-anchor receiver fallback; its old saved summary predates that fallback. HBASE-01 has paired HBase RPC messages but no valid selected receiver anchor, so this change does not invent an edge.

Targeted validation: `python3 -m unittest Mallory.native_graphchecker_feedback.test_region_state_graph Mallory.native_graphchecker_campaign.test_campaign -q` passed 43 tests, with 2 environment-dependent skips. The synthetic tests also reject mismatched physical senders, wrong transport anchors and reused endpoint IDs. No new target exception or bug is claimed by this graph correction.
