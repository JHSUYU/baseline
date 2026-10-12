# SOLR-37 original-102 full campaign stage

Selected JUnit: `ShardSplitTest#test`. Selected guard: `DistributedZkUpdateProcessor.doDefensiveChecks@994`. ShardSplitTest.java:100-114,675-715 exercises parent-to-subshard updates; DistributedZkUpdateProcessor.java:983-996 checks whether the subshard range remains within the parent range.

Prior passing calibration `data/mallory/calibration_v29a_lane3/SOLR-37/result.json` reached the exact guard on shard-2: 88 exact nonthrowing target instances and 914 named pretarget I/O doors. The selected target did not throw. This establishes a suitable existing cluster JUnit and named pretarget I/O. Earlier path-gap reviews describe fault outcome, not admission.

The full campaign starts its own fresh healthy seed and then runs up to 80 fault trials, 3600 cumulative trial seconds, and three exception faults per trial. Healthy JUnit success, exact nonthrowing target, named actor, and named injectable pretarget I/O are admission conditions. Target retention after injection and graph path quality are reported outcomes; no event-time path is required to launch.

The case-local configs pin Solr source and compiled target hashes, the immutable numeric-thread agent, v38 Solr adapter, direct JUnit runner, real I/O site catalog, and frozen graph-order core. The node2 shell holds case and Solr source locks and checks disk and RAM floors. `admission-request.json` has `go=false`; dispatch GO receipts are absent. No JVM was launched while staging. Run `run_campaign.py --mode full --preflight-only` on node2, then dispatch may run `run_node2.sh full` in order.
