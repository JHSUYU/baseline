# SOLR-05 upstream POST-write observation

This review separates the selected `ZkController.register` null guard from a
different failure of the original `AddReplicaTest.testAddMultipleReplicas`.
The selected guard did **not** throw in any upstream trial or replay.

## Raw result and independent replay

The final two original JUnit healthy runs exited 0. The two instrumented
healthy runs also exited 0, each with nine selected checks and nine unique
replica additions. The independent upstream campaign stopped when its queue
was empty: 18 attempts, 18 strict one-fault injections, nine exact
post-fault selected guards, zero selected throws, and 349.965 seconds of
trial time. The nine PRE-write injections all lost the same-replica target;
they are not effective feedback trials. All nine POST-write injections kept
it. The original test failed after eight POST injections because the
observed replica count exceeded its assertion (five 9→10, three 4→5);
the ninth timed out waiting for an active collection. These are **not**
counted as selected-guard exceptions. The raw trace/JUnit/JaCoCo/plan audit
has zero errors at `evidence/campaign/audit.json`.

Trial 001 selected `STATE_SET_DATA_POST` on
`/collections/testAddMultipleReplicas/state.json` for `core_node18`,
core `testAddMultipleReplicas_shard1_replica_p13`. Its raw
`IO_APPLIED_CONNECTION_LOSS` was event 1022 on the Overseer writer,
client 450432609, reader 1111847475, writer 552601664. The same
replica's original target guard ran at event 1092 on the intended receiver
node, client 1927133770, reader 317124118, and found the replica present.
Between them, event 1037 recorded a new pending `core_node19` for the
**same core and receiver node**, on a new writer. The original JUnit
reported `expected:<9> but was:<10>`.

The plan was replayed **outside the campaign denominator** in
`evidence/replay-post-001` with separate scratch and the unchanged original
JUnit. The replay exited 1 in 17.869 seconds with the same 9→10 assertion.
`replay-audit.json` verifies one unique matched/applied fault, the exact
Overseer writer/client/reader and intended replica-host binding, a later
same-replica guard with `last_fault=F0`, and a second pending `core_node19`
for the same core and receiver. Jetty ports and object IDs changed across
runs, while the logical selector and failure were the same. The second
write reached its POST observation point, so its `setData` returned
successfully. The replay retains raw trace, JUnit log, JaCoCo data, plan,
elapsed time, and SHA-256 receipt.

## Source explanation and scope

In the pinned Solr 8.11.4 source, `AddReplicaCmd.java:247-260` queues an
`ADDREPLICA` state update; its `coreNodeName` can be absent. `SliceMutator.java:84-89`
allocates a fresh core-node ID when the message lacks that field.
`ZkStateWriter.java:261-269` calls `SolrZkClient.setData` for `state.json`,
then updates its local state; its pending-update map is cleared later at
line 284. The POST hook throws `ConnectionLossException` **only after**
the real `setData` succeeds. This models an ambiguous outcome reported to
the caller after a committed write. `Overseer.java:261-285` removes the
queue item after processing/writing; on an exception its fallback path
reprocesses queued work (`Overseer.java:194-214`). The repeated
`ADDREPLICA` message has no fixed `coreNodeName`, so source and trace
support a second ID for the same core. This source path explains the
observed 10th replica; it is an inference from the stated code and events,
not a claim of a selected null-guard failure.

The original JUnit asserts four and then nine replicas in
`AddReplicaTest.java:74-122`; it expects a different capacity request to
fail. Existing `ZkStateWriterTest` cases exercise batching and stale
versions, but a search of that test and `OverseerTest` found no test for
this committed-write/ambiguous-result retry sequence.

## Public issue comparison

- [SOLR-8722](https://issues.apache.org/jira/browse/SOLR-8722) records that
  `ADDREPLICA` needed to wait for its state change, with a same-core-name
  risk. It was fixed before 8.11.4 and addresses a different timing path.
- [SOLR-9818](https://issues.apache.org/jira/browse/SOLR-9818) records extra
  replicas when the **Admin UI client** retries non-idempotent requests after
  losing connection. It is open and has the same visible symptom, but this
  replay issued one original JUnit request and retried the **internal
  Overseer state queue** after a successful ZK write.
- [SOLR-7982](https://issues.apache.org/jira/browse/SOLR-7982) discusses
  duplicate core-node names across shards; the IDs here are distinct and
  refer to one core on one node. It does not establish equivalence.

Public overlap leaves novelty unresolved. The separate extra-replica
observation is **replayed candidate evidence**, not a marked new bug. The
selected SOLR-05 guard remains untriggered under these observed I/O roots.
The stage stopped below its nominal 80-effective budget because the
verified queue was exhausted; completed plans were not repeated to fill it.
