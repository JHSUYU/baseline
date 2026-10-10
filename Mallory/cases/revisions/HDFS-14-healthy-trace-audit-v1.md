# HDFS-14 healthy trace audit

Source: Hadoop 3.4.3, `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite`.
Trial: node2 `/tmp/mallory-hdfs14-token-password-v1-node2-healthy/trials/r0000`.
The compressed trace SHA-256 is
`e79f3409f6e8be30cf504eaf6d2aa36b68d8543182a11745bc5f440f5e8c214e`;
its decompressed SHA-256 is
`673f18d7bd6f8d8dc89d76843c5e0ccef172df130be46413cbc0e0dec5a8b062`.
The two parameterized JUnit instances passed (2 tests, 0 failures, 0 errors).

The selected target is the six-argument
`BlockTokenSecretManager.checkAccess` password comparison at lines 411–412.
Four exact checks occurred at event sequences 185, 204, 376, and 390 on
`hdfs-cluster-2/dn0` and `hdfs-cluster-4/dn0`. The observed key-map data flow
is:

| Actor | Initial `allKeys` writes | Heartbeat IOException door | Key read before selected check |
| --- | --- | --- | --- |
| cluster-2/dn0 | 119–121, key 602214408 at 121 | 129 | 184 → 185 and 203 → 204 |
| cluster-4/dn0 | 324–326, key 726186945 at 325 | 334 | 375 → 376 and 389 → 390 |

The graph has 142 observed edges and 12 candidate sampled-state edges. All
seven configured typed doors have `in_closure=false`. Recomputing
`OccurrenceGraph.event_path(door, check, include_candidates=True,
require_edge=True)` for all 7 doors × 4 checks yielded zero witnesses. The
same-DataNode heartbeat door is before the check in wall-clock order, but it
occurs **after** the key write consumed by that check. The client SASL response
and NameNode data-encryption-key doors also lack an event-time path to the
selected password comparison. This result does not establish that no possible
fault sequence could reach the check; it establishes that the healthy trace
does not justify a full campaign with its configured doors.

The earlier registration RPC is a source-backed diagnostic alternative.
`BPServiceActor.register` calls `DatanodeProtocolClientSideTranslatorPB`
`.registerDatanode` at line 829, catches a plain `IOException`, sleeps one
second, and retries at lines 840–845. The healthy trace has DataNode RPC
send/receive events 113–116 and 318–321 before
`BPOfferService.registrationSucceeded` adds the initial exported block keys
at line 430. `BPServiceActor.register` calls `registrationSucceeded` after
the successful RPC at line 852. A separate v2 healthy-only package adds a
typed door at this exact call and a `register` region. Its runtime trace must
show a named, event-time path before fault trials can be justified.

`BlockTokenSecretManager.retrievePassword` retrieves `allKeys[keyId]` at
lines 509–516 and throws its own `InvalidToken` if the key is absent. The
HDFS-14 comparison at 411–412 requires a key to exist and the recomputed
password to differ from the token password. A dropped registration or key
update therefore cannot be equated with the selected exception without
separate source and postfault evidence.
