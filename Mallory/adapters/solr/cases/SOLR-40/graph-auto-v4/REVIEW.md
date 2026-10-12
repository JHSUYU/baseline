# SOLR-40 strict-closure result

The original four-node JUnit passed in healthy trial r0000. Runtime target
class attestation and the `@133:callthrow:7` site catalog passed. The healthy
backward closure contained seven eligible alias-watch read doors. The
scheduler tested all seven as one-fault plans, then stopped with
`queue_exhausted` after 220.6 seconds. No trial recorded the target exception.

The two ordinal-1 watcher faults both applied, but the subsequent target
check occurred on a different node: r0006 faulted node2 and checked node4;
r0007 faulted node4 and checked node2. These trials therefore do not refute
the same-node candidate established by the separate directed v3b replay.
This campaign did not use that replay plan. Its raw checkpoint, trial results,
site catalogs, and traces are under
`data/mallory/solr40_graph_auto_v4_node0/SOLR-40/`.
