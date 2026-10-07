# SOLR-19 V3 campaign checkpoint: r101–r120

The unchanged Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas` cluster
JUnit continued from the r100 checkpoint. The selected target is
`CoreContainer.create`'s `coreNodeName == null` guard at
`CoreContainer.java:1329–1330`. The case-local source overlay injects
ZooKeeper `ConnectionLossException` only after an ordered exact
operation/path/caller/dynamic-actor/occurrence I/O match.

The r101–r120 event traces, original JUnit logs, JaCoCo data, manifests,
and trial ledgers are archived as `v3-campaign-r101-r120.tar.gz`
(1,659,442 bytes; SHA-256
`79257c6257b2a6dbf77c4c2de43fed9b18f2b088465da344c4e41b475d577adc`).
Its manifest records 100 individual file hashes. Node1 and node0 copies
match. The independent `audit_archive_v3.py` receipt
`v3-campaign-r101-r120-audit.json` checked each file and the same-run
CREATE sender, ZooKeeper client bind, exact I/O selector, ordered fault
application, and target actor lineage.

| r101–r120 measure | Value |
| --- | ---: |
| Original JUnit attempts | 20 |
| Strict ordered identity matches | 11 |
| Strict injections with later same-core, same-sender target | 10 |
| Selected target exceptions | 0 |
| Original JUnit failures | 16 |
| Total JUnit elapsed time | 2,210.782 s |
| New production probe IDs in scheduler feedback | 4 |
| New normalized I/O behavior identities | 0 |
| Maximum ordered fault depth | 7 |
| Independent strict identity/target lineage issues | 0 |

Most failed original JUnits spent roughly 132–136 seconds waiting for an
asynchronous collection-operation status after ZooKeeper fault injection.
This batch includes long attempts with incomplete fault matching and one
strict attempt that lost the postfault target; neither contributes to the
effective budget. r114 added four new production probes, but it occurred
before the prescribed final-eight-effective extension window. No trial
triggered the selected `coreNodeName` missing exception.

At r120, the campaign had **120 attempts, 84 strict injections, 72 effective
target-retaining trials, zero selected target exceptions**, 6,085.733 seconds
of original-JUnit time, and 436 new production probe IDs above the two
healthy seeds. Node1 tmux `solr19-v3-full` continues at r121; base budget is
80 effective trials with at most eight ordered faults. This receipt is an
intermediate checkpoint, not a terminal classification.
