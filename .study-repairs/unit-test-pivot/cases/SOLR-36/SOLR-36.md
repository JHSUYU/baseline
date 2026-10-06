# SOLR-36: active child shard rejects parent forwarding

## Original source and test

Solr 8.11.4 revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9`,
`DistributedZkUpdateProcessor.doDefensiveChecks`, line 986 checks whether a
child shard receiving an update marked as from its parent leader is already
`ACTIVE`; line 987 throws a `SERVICE_UNAVAILABLE` `SolrException` if so. The
original `ShardSplitTest#test` is a Nightly embedded SolrCloud JUnit. It runs
the original range, unique-key, route-field, and route-key split scenarios.
The JUnit source is unchanged; `-Dtests.nightly=true` enables its declared test.

## Independent healthy calibration

The uninstrumented original JUnit passed in 102.743 seconds. Two independent
case-local ASM/JaCoCo recordings of the same JUnit passed in 105.004 and
104.037 seconds. The exact source-line guard executed 92 and 100 times,
respectively, on logical child replicas `collection1/shard1_0/core_node11`
and `collection1/shard1_1/core_node12`. Observed states were `construction`
or `recovery` while the phase was `FROMLEADER`; the exact throw occurred zero
times. The physical Jetty address is recorded separately from the logical
replica identity. The two healthy records share 650 precise, target-preceding
ZooKeeper I/O selectors; the initial queue samples 200 selectors across 120
I/O families. See [seed-audit.json](independent/seed-audit.json).

## Campaign

`SOLR-36` and `SOLR-37` share an ordered-fault sequence and original JUnit
execution, but retain distinct postfault target and exact exception oracles.
The node2 campaign runs in `tmux` session `solr36_37_fuzz`, with an 80 trial,
eight ordered fault ceiling and atomic resume checkpoint. Node0 session
`solr36_37_mirror` updates both 102 checklist rows. Every applied fault must
match marker, caller site, logical source, resource and hit ordinal. Production
JaCoCo probes from original Solr/Lucene classes and newly observed I/O guide
mutations. Runtime-woven methods are excluded from production coverage.

An exact target exception is a candidate observation requiring source review,
comparison with the original JUnit's expected behavior, and replay. A
protective rejection of an invalid forwarded update is not by itself a new bug.
