# SOLR-19 V3 campaign checkpoint: r041–r060

This is a continuation of the unchanged Solr 8.11.4
`AddReplicaTest.testAddMultipleReplicas` original JUnit, release commit
`e27f44e`, with the selected `CoreContainer.create` `coreNodeName == null`
guard. The controller uses only exact operation/path/caller/dynamic-actor/
occurrence selectors and injects ZooKeeper `ConnectionLossException` at the
ordered matched I/O. Completed r041–r060 raw files were archived on node1
without stopping the trial scheduler, copied to node0, and audited there.

`v3-campaign-r041-r060.tar.gz` is 13,856,500 bytes with SHA-256
`81fd168add5c5b8fa6ced5b2e4c3e6a11b45e8a7f7820c6df6d42a7dfef5e216`.
The manifest contains a separate SHA-256 for each of 100 files: the event
trace, original JUnit log, JaCoCo execution data, runner manifest, and trial
ledger for every completed trial. `audit_archive_v3.py` rechecked every
archived byte and the same-run sender, ZooKeeper-client bind, exact I/O
identity, ordered match/application, and same-core target actor lineage.
`v3-campaign-r041-r060-audit.json` is the machine-readable independent
receipt.

| r041–r060 measure | Value |
| --- | ---: |
| Original JUnit attempts | 20 |
| Strict ordered identity matches | 16 |
| Strict injections with later same-core, same-sender target | 11 |
| Selected target exceptions | 0 |
| Original JUnit failures | 10 |
| Total JUnit elapsed time | 922.578 s |
| New production probe IDs in scheduler feedback | 255 |
| New normalized stable I/O families | 2 |
| Maximum ordered fault depth | 8 |
| Independent strict identity/target lineage issues | 0 |

r041/r042/r045/r049/r050 entered the same fault-specific Overseer asynchronous
status wait family seen in earlier trials, taking 130–136 seconds each. The
other five failed original JUnits completed in about 15–16 seconds. Their
existing JUnit assertion expected asynchronous status `COMPLETED` but saw
`FAILED`; the long runs saw `SUBMITTED` or `RUNNING`. The selected target
guard remained `present` in every effective trial, including the long runs.
These JUnit failures are recorded as faulted-workload outcomes, not selected
target exceptions or confirmed new bugs. A partial or missed ordered fault,
or a lost postfault target, does not count toward the effective budget.

r048, r052, and r060 exposed 40, 77, and 126 new Solr production probe IDs
respectively, despite their JUnit failures. The scheduler kept those exact
target-retaining executions as coverage feedback and mutated their observed
postfault I/O. r049 added 11 probes; r044 added one. The 255-probe total
matches the campaign checkpoint's production probe set delta.

At the r060 boundary, the whole V3 campaign had 60 attempts, 43 strict
injections, 34 effective target-retaining trials, 0 selected target
exceptions, 2,015.954 seconds of original-JUnit time, and 390 new production
probe IDs above the two healthy seeds. The node1 tmux `solr19-v3-full`
continues from the next saved plan toward the 80-effective/max8 budget;
this receipt does not mark SOLR-19 terminal.
