# SOLR-07 V5 trial 298: exact target throw review

**Disposition (2026-10-07):** same teardown-race family as V4 trials 038/048/064/247/252; `candidate_reviewed`, `novelty=pending`, `new_bug=false`. This is a real exact fault and target receipt, but the original JUnit test failed its initial collection CREATE with a client HTTP timeout and ended before the core disappeared during `@AfterClass` shutdown. No `ADDREPLICA` operation was reached. This review read only the completed trial-298 files on node2; it did not touch the running V5 scheduler or rerun JUnit.

## Immutable trial receipt

The six files in `node2:/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-07/actor-v2/campaign/trial-298/` were complete when read and had these SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `events.jsonl` | `2eba07e9088f7bcbb498c48209202ddf4fa6cbbe2e81ed047d8f78282bd58ed2` |
| `junit.log` | `14b2db00897f1f6a6a130289a97be3819c0113ba05093f4dcf3214507a0e5587` |
| `run.json` | `05e8f51b5b8bf04dcc1f0ddbf1ab859d0ab8260705371cf4f017716981f1636f` |
| `trial.json` | `02a725fdcb696976916251bc3ccd7600d835bfdaed661348eed8edfa51acf7ba` |
| `fault.properties` | `bbda472e85d5bf7d3608d3c5bdedb8240a22b1723f22128941014a7c9d852404` |
| `jacoco.exec` | `b8f53054a1b806f29769e19825db37d24d7491a92c0f1bde023399ecfa3abef7` |

`trial.json` records two of two applied synthetic `CONNECTION_LOSS` faults, `exact_injection=true`, `effective=true`, `target_after_fault=true`, `target_exception=true`, JUnit exit 1, 99.692 seconds, and zero new coverage/families. The unchanged test is `AddReplicaTest#testAddMultipleReplicas`, Solr revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9`, agent SHA-256 `1f3b830ed5c053eb4a31e04a778fc6cd8b845f5691ade1e7c07c8fb460507cb4`.

## Identity and sequence

`events.jsonl` event 420 applied step 1 at `ZkStateReader$LazyCollectionRef.get:811`, `EXISTS_WATCH@15`; event 434 applied step 2 at `ZkStateReader.fetchCollectionState:1641`, `GET_DATA@5`. Both use path `/collections/testAddMultipleReplicas/state.json`, actor `JETTY/node1`, physical node `127.0.0.1:36691_solr`, ZK client identity `63389335`, and HTTP thread 176. `TARGET_CHECK` event 530 and `TARGET_THROW` event 531 retain that node/client/thread, the exact core `testAddMultipleReplicas_shard1_replica_n1`, target key `SOLR/CORE/testAddMultipleReplicas/shard1/core_node2/testAddMultipleReplicas_shard1_replica_n1`, and leader key `JETTY/node1/testAddMultipleReplicas_shard1_replica_n1`. The guard reports `eligible=true;isLeader=true;corePresent=false;replicaType=NRT` and throws `SolrCore is no longer available to register` at `ZkController.register:1326`. Thus neither a wrong actor nor an approximate target match explains the receipt.

The `junit.log` chronology is decisive about the enclosing test phase:

| Time from start | Log lines | Observation |
| --- | --- | --- |
| 8429–8981 ms | 168, 181 | Initial collection `CREATE` reaches node3; node1 begins CoreAdmin `CREATE` for the selected core. |
| 10566 ms | 206–225 | Synthetic `ConnectionLossException` at `Probe.io`, inside `ZkStateReader.fetchCollectionState` → `getLeaderUrl` → `ZkController.register` on node1/thread 176. |
| 98338 ms | 270 | `###Ending testAddMultipleReplicas` on the test worker. |
| 98454–98475 ms | 274–280 | node1 `CoreContainer` shuts down and the selected core logs `CLOSING SolrCore`. |
| 98501–98505 ms | 342–405 | The same node1/thread 176 registration catch reaches `ZkController.unregister:1763` / `register:1371`, sees session expiration, then logs completion of the original CoreAdmin `CREATE` request. |
| 98526–98540 ms | 406–419 | Overseer logs duplicate collection CREATE/`collection already exists` while teardown is underway; this is after the test ended. |
| End | 525 | JUnit failure is `Timeout occurred while waiting response from server at http://127.0.0.1:41417/solr`. |

The JUnit log has zero `action=ADDREPLICA` entries. In original `AddReplicaTest.java:64–68`, `cloudClient.request(create)` precedes all add-replica operations (`:70–122`); trial 298 remained in that first request. The event file has no timestamp, so the target instruction's precise time relative to the log's core-close line is inferred from the same-thread registration catch at 98501 and original source flow. In the original Solr source, `CoreContainer.registerCore:1249–1269` adds the core to `solrCores` before synchronous `ZkContainer.registerInZk:202–241`; `ZkController.register:1310–1326` waits for the leader, then reacquires the core. `SolrCloudTestCase.shutdownCluster:287–295` invokes `MiniSolrCloudCluster.shutdown:632–652`; `CoreContainer.shutdown:1034–1090` calls `SolrCores.close:88–124`, which clears the core map before closing the core. A pending registration then finds no core at `cc.getCore`, and the `register:1371` catch attempts unregister. This matches the observed order and the five V4 receipts reviewed in `v4-five-target-throw-source-review.md` (frozen V4 state SHA-256 `dbbc09bf3fed05208f90373c1f5ee017b39c6a7386f7823d37ebe0ac526b5380`).

The earlier client timeout may warrant an independent recovery study under a reproducible strict ConnectionLoss sequence. This trial does not establish that the target guard fails while the cluster is meant to remain active, nor that the later duplicate CREATE during shutdown is a novel coordination defect. Record this as one further exact target observation within the previously classified shutdown family, not as a new bug.
