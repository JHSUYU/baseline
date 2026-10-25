# SOLR-19 V3 campaign checkpoint: r081–r100

The unchanged Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas` cluster
JUnit continued on node1 from the r080 checkpoint, using exact ordered
operation/path/caller/dynamic-actor/occurrence ZooKeeper I/O selectors and
`ConnectionLossException` injection. The selected target remains the
`CoreContainer.create` `coreNodeName == null` guard at
`CoreContainer.java:1329–1330`.

The completed r081–r100 event traces, JUnit logs, JaCoCo data, manifests,
and per-trial ledgers are archived in `v3-campaign-r081-r100.tar.gz`
(1,982,874 bytes; SHA-256
`bea39ed29d9c4c23cfa5f1b877fb5ba8a510605bea932ee2fe0b0eabe1430248`).
The manifest records 100 individual file hashes; the node0 copy matches
the node1 archive hash. `audit_archive_v3.py` independently checked those
bytes and each trial's same-run CREATE sender, ZooKeeper bind, exact I/O
selector, ordered fault application, and same-core target actor lineage.
The machine receipt is `v3-campaign-r081-r100-audit.json`.

| r081–r100 measure | Value |
| --- | ---: |
| Original JUnit attempts | 20 |
| Strict ordered identity matches | 15 |
| Strict injections with later same-core, same-sender target | 13 |
| Selected target exceptions | 0 |
| Original JUnit failures | 5 |
| Total JUnit elapsed time | 941.250 s |
| New production probe IDs in scheduler feedback | 9 |
| New normalized I/O behavior identities | 4 |
| Maximum ordered fault depth | 8 |
| Independent strict identity/target lineage issues | 0 |

The five failed original JUnits were r083, r084, r088, r092, and r096,
each taking about 133–136 seconds in the known asynchronous status wait
family. r084 was strict but lost the target afterward, so it is an attempt
only. None yielded the selected target exception. r083 and r087 contributed
2 and 7 new production probe IDs; r088 contributed four new normalized I/O
behavior identities. Hit ordinal and generated ZooKeeper sequence numbers
are excluded from the I/O novelty identity.

At r100, the campaign had 100 attempts, 73 strict injections, 62 effective
target-retaining trials, zero selected target exceptions, 3,874.951 seconds
of original-JUnit time, and 432 new production probe IDs above the two
healthy seeds. Node1 tmux `solr19-v3-full` continues from r101 toward the
80-effective/max8 budget. This receipt is an intermediate checkpoint.
