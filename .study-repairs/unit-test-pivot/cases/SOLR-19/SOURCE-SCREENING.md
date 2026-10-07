# SOLR-19 source screening for the current exception-injection workload

Selected site: Solr 8.11.4 `CoreContainer.create(String, Path, Map, boolean)` at
`solr/core/src/java/org/apache/solr/core/CoreContainer.java:1329-1330`. In
non-legacy mode it throws when the new `CoreDescriptor` has no `coreNodeName`.
The unchanged cluster workload is `AddReplicaTest.testAddMultipleReplicas`.
Its existing instrumented healthy trace
(`independent/evidence/healthy-instrumented/events.tsv`) records nine
nonthrowing guards. Their core names are `core_node2`, `core_node7`,
`core_node6`, `core_node8`, `core_node14`, `core_node15`, `core_node16`,
`core_node17`, and `core_node18`; these arise during the test's collection
creation and replica additions. This trace lacks a full sender-to-receiver
actor join, so it is screening evidence rather than an actor-aware seed.

## Value path in that workload

1. Collection creation enters `CreateCollectionCmd`. In its non-legacy branch,
   it waits for a replica entry, then sets `CoreAdminParams.CORE_NODE_NAME` from
   that entry **before** submitting the CoreAdmin request
   (`CreateCollectionCmd.java:346-363`). A missing map entry fails before the
   request is submitted.
2. Replica addition enters `AddReplicaCmd`. In non-legacy mode, it waits for the
   replica entry and sets `CORE_NODE_NAME` from its name before building and
   sending the CoreAdmin request (`AddReplicaCmd.java:245-266, 285-303`). The
   later conditional assignment does not remove that parameter when the
   optional `createReplica.coreNodeName` is null.
3. The receiver's `CoreAdminOperation.CREATE_OP` calls
   `CoreAdminHandler.buildCoreParams` and then `CoreContainer.create`
   (`CoreAdminOperation.java:73-95`). `buildCoreParams` copies a nonempty
   standard `CORE_NODE_NAME` request value into the
   `CoreDescriptor.CORE_NODE_NAME` property, but then copies `property.*`
   request values and can overwrite the same key
   (`CoreAdminHandler.java:236-260`). `AddReplicaCmd` also appends these
   properties after setting the standard name
   (`OverseerCollectionMessageHandler.java:615-620`).
4. `CoreDescriptor` copies request properties, then `loadExtraProperties()`
   may read `conf/solrcore.properties` (or a configured path) and overwrite
   them again (`CoreDescriptor.java:185-244`). `CloudDescriptor` finally reads
   `coreNodeName` from the resulting properties and turns missing/empty into
   null (`CloudDescriptor.java:61-69`). The selected guard checks that value
   before `checkIfCoreNodeNameAlreadyExists` and later core creation I/O
   (`CoreContainer.java:1326-1335`).

For these two request producers, an exception in the state lookup can prevent
the create RPC. A constructed `Replica` has a nonnull name: its constructor
requires it (`Replica.java:148-160`), but does not reject an empty string.
Even a nonempty standard RPC field does not prove the guard's value because
`property.coreNodeName` or an external properties file can override it. The
unchanged test does not visibly request either override, but the existing
healthy trace does not capture the full sender-to-receiver request and file
state. The earlier 128 graph-free fault trials had coarse actor identities and
remain historical evidence only; they do not make the V2 check quality
complete.

**Decision pending runtime evidence.** The current source analysis cannot
justify `source_excluded`: two concrete override paths remain. A V2 adapter
should bind the sender's CoreAdmin create request to the receiving
`CoreContainer` and exact core, record both the standard and `property.*`
values, and observe any external properties file read before this guard. The
healthy trace's nine receiving guards lack that join. If an injection removes
the entire RPC or aborts descriptor construction, record `lost_target`
instead of treating an unrelated JUnit failure as this check's outcome.
