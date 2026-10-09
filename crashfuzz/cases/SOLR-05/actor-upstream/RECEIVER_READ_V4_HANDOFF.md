# SOLR-05 receiver state-read handoff

The upstream writer campaign's 18-plan queue is exhausted, but this does not
exhaust the I/O observed between its state write and the selected
`ZkController.register` guard. Its `relevant()` predicate admits only
`actor=overseer_writer_for_replica`, so it excludes the receiving Solr node's
`ZkStateReader.fetchCollectionState:1641` ZooKeeper `GET_DATA` on
`/collections/testAddMultipleReplicas/state.json`.

I checked both existing instrumented healthy traces without changing their
workload. Each has nine `STATE_SET_DATA_POST` events followed by a selected
guard for the same replica. For all 9/9 pairs in each trace, the recorded
`target_node` performs this state read after the write and before the guard.
For example, healthy-actor-001 has `core_node18` POST at sequence 1019,
receiver read at 1020, and same-replica guard at 1046. The receiver node in
the POST and the read is `127.0.0.1:39327_solr`; the guard records the same
node. The second healthy trace independently shows 9/9 such pairs with fresh
Jetty ports. These observations come from
`evidence/healthy-actor-{001,002}/events.tsv`.

This is a concrete next I/O family for a separate V4 campaign. Its selector
must bind the writer's replica/core and intended `target_node` to the actual
receiving node's ZooKeeper client/reader, then match the exact state read and
require that **the same replica's** selected guard executes after the final
fault. The read events currently have no replica field; an unqualified
`GET_DATA` on the same path is insufficient identity evidence. Calibrate two
fresh unchanged original cluster JUnits with the V4 instrumentation, preserve
the old 18 attempts in their own checkpoint, and count only new strictly
applied, target-retaining trials toward this stage's budget. A selected throw
requires replay and source review before a new-bug mark.
