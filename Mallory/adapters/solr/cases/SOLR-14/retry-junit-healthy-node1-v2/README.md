# SOLR-14 unchanged retry JUnit: isolated healthy stage

`ShardSplitTest#testSplitAfterFailedSplit` is an existing Solr 8.11.4 cluster
JUnit. It starts the distributed ZooKeeper/Solr fixture, deliberately fails a
split, checks that incomplete subshards were cleaned up, and submits another
split of the same shard (`ShardSplitTest.java:284-332`). The first failure is
caught at lines 298-305; the second split starts at lines 320-325.

The SOLR-14 check is `SplitShardCmd.split@165:branch:5`, immediately after
`SolrZkClient.exists` at line 164. The prior unchanged `SplitShardTest#doTest`
healthy trace reached this exact check three times on named `node1`, with
same-occurrence line-164 doors. Its two selected direct ZooKeeper exceptions
are uncaught inside `split`. Therefore an exception at line 164 prevents **that
invocation** from reaching the check. This alternate JUnit may retain a target
check **after** such a fault through its own split retry. It cannot prove a
same-invocation fault-to-check path, and the retry must be observed in a fresh
healthy trace before admission of a fault campaign.

The wrapper changes only the selected, unchanged JUnit in a case-local copy of
the pinned inventory. It uses the existing Solr v38 runner, compiled Solr
8.11.4 target, immutable agent and frozen Mallory core. The site catalog
contains only the exact line-130 and line-164 typed ZooKeeper calls; automatic
I/O doors are disabled. The healthy stage performs no faults.

Offline check: `python3 static_preflight.py`. Dispatch must supply a
case-local `admission-healthy-node1.json` GO receipt before `run_node1.sh`
starts the JVM. No GO receipt or JUnit result is included in this stage.

After a healthy run, verify one passing JUnit, loaded-class SHA, named target
actor, first and retry split occurrences for the same collection/shard, and a
typed line-164 door preceding each check. A later fault run must count only
checks that occur after the applied fault. A check reached earlier in the test
does not establish target retention. The original SOLR-14 checklist row stays
pending until a fault campaign finishes.

The node1 port pins the same source revision, compiled Solr JAR and class,
agent, adapter, frozen core, selected unchanged JUnit, and typed door catalog.
A fresh healthy trace must pass `audit_healthy.py` before any fault run.
