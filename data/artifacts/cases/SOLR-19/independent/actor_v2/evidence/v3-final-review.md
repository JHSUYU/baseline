# SOLR-19 V3 final source and raw-trace review

The workload was the unchanged Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas`
from source commit `e27f44e`. It starts three embedded Jetty nodes, creates a
collection, and adds replicas. Both actor-qualified healthy seeds passed the
original JUnit and each reached the exact selected guard nine times. The
selected check is `CoreContainer.create(String, Path, Map, boolean)` at
`solr/core/src/java/org/apache/solr/core/CoreContainer.java:1329–1330`:
`cd.getCloudDescriptor().getCoreNodeName() == null`. The throwing branch
raises `SolrException(SERVER_ERROR, "non legacy mode coreNodeName missing ...")`.

The case-local overlay used the original JUnit and source, plus runtime
CREATE sender, receiver, descriptor, file-state, target, and ZooKeeper I/O
probes. Faults were `KeeperException.ConnectionLossException` at an ordered
operation, path, caller, same-run producer/owner actor, and occurrence. A
strict match required every planned exception to apply in order to its
intended actor. An effective trial additionally required the **same core and
CREATE sender** to reach this exact guard after the last fault. JaCoCo Solr
production probes and stable normalized I/O identities guided mutations.
No GraphChecker graph, skeleton, or static closure selected or judged these
faults.

| Final measure | Value |
| --- | ---: |
| Original JUnit attempts | 134 |
| Strict ordered identity matches | 92 |
| Strict matches with later same-core/same-sender guard | 80 |
| Selected throwing-guard outcomes | 0 |
| Original JUnit passes / failures | 73 / 61 |
| Total original JUnit time | 7,276.230 s |
| Maximum fully applied fault sequence | 8 |
| New production probe IDs used for feedback | 436 |
| New normalized I/O identities | 19 |
| Distinct injected operation/path/caller triples | 18 |

The raw archives contain **897 exact `TARGET_GUARD` events**. Every one has
detail `present`; none has `missing`. The standard `coreNodeName` parameter
was present in all 897, the `property.coreNodeName` override field was empty
in all 897, and the `EXTRA_PROPERTIES_FILE` probe reported `false` for all
897 corresponding descriptors. These are observations of this workload and
fault scope, not a claim that the throwing branch is impossible in Solr.
The final eight effective trials were r121, r122, r126, r128, r129, r131,
r133, and r134. Each added zero new production probes and zero stable I/O
families. The predefined extension condition therefore did not hold, and
the campaign stopped at 80 effective trials rather than extending to 128.

`CoreAdminOperation.CREATE_OP` copies request parameters with
`buildCoreParams` before calling `CoreContainer.create`. Its new
`CoreDescriptor` loads optional external properties and constructs a
`CloudDescriptor`; `CloudDescriptor` reads `coreNodeName`, turning missing
or empty into null. The selected guard runs before the subsequent
`checkIfCoreNodeNameAlreadyExists` ZooKeeper operation and core-properties
write. The original create/add-replica producer paths set a standard
replica name, but source also permits a `property.coreNodeName` override
or external properties file. Runtime probes observed neither override.
Thus the injected ZooKeeper connection losses caused recovery/status
behavior, including 61 failed original JUnits, without showing the selected
missing-name exception. Failure of an asynchronous `processAndWait` status
assertion is a workload outcome, not this selected target exception.

The two pilot rounds were independently re-audited from the raw archive.
The remaining r003–r134 rounds were independently checked from archives
against their per-file SHA-256 manifests: 0 strict-identity disagreements,
0 target actor-lineage issues, and 0 target exceptions. The final immutable
checkpoint SHA-256 is
`7cad968a37e0a47d12a4126333ec16e09345e3d12e23dd9de8a8fe942220f3e2`.
The last archive, `v3-campaign-r121-r134.tar.gz`, has SHA-256
`16544a21b3013b8cfbf0d61e1b01353e8a26c68b166e995c34f0bcac2aa9fca9`
on node1 and node0. The independent receipt is `v3-final-audit.json`;
`v3-campaign-r001-r134-union-coverage.json` recomputes JaCoCo from all
archived runs.

The healthy production coverage union was 4,482 methods and 5,588 branches.
The healthy-plus-all-attempts union reached 4,543 methods and 5,808
branches (+61/+220). The healthy-plus-80-effective-trials union reached
4,532 methods and 5,773 branches (+50/+185). The selected create method
itself has 24 JaCoCo branches; counting covered branches anywhere in that
method cannot stand in for the exact guard outcome, which is established
by the raw events above.

**Classification: quality complete for this bounded, actor-qualified
original-JUnit campaign; `bug_mark=none`.** No new bug is confirmed for
SOLR-19. The result covers observed ZooKeeper I/O in this test. It does not
claim exhaustive behavior for other workloads or fault kinds, and it does
not treat a fault-induced JUnit failure as proof of the selected exception.
