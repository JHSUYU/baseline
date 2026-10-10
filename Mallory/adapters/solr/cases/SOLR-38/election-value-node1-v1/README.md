# SOLR-38: exact accessor-value diagnostic on node1

The prior node1 healthy run passed the unchanged three-node
`CloudHttp2SolrClientTest#testAliasHandling` JUnit and reached 12 exact
`doDefensiveChecks@1021` checks. It observed four typed election I/O doors and
same-descriptor `isLeader` field writes and reads, but the 660 sampled state
edges are only candidate evidence. The strict target closure contains no path
from an election door. The earlier four HTTP faults did not retain the target.

This bounded follow-up instruments only `CloudDescriptor.setLeader(Z)V` and
`isLeader()Z` in the existing Solr handoff adapter. The getter hook duplicates
its actual return-stack boolean; the setter hook captures the argument after
the pinned volatile field assignment. Both emit structured diagnostic events
with the Probe's JVM object identity. `audit_healthy.py` checks that the true
write and true read belong to the same object, actor, and relevant regions,
with no intervening instrumented setter. These events still have
`version_confidence=sampled`: the hooks run after field access and do **not**
establish an atomic read-from relation. This package cannot authorize a full
campaign or a bug claim.

`python3 -B -m unittest -v test_offline.py` and
`python3 -B run_healthy.py --preflight-only` are JVM-free. The node1 steward
may create `admission-healthy-node1.json` matching the preflight fields, with
`go: true` and `scope: one_healthy_junit_no_fault`, after its own lane GO.
Only then may it run
`python3 -B run_healthy.py --admission-receipt admission-healthy-node1.json`.
The runner takes node1 and Solr-source locks, builds the isolated adapter on
node1, and runs one fresh fault-free JUnit. It leaves the prior output and
shared core/checklist untouched. Audit the result with
`python3 -B audit_healthy.py <healthy-output> --out <audit-file>`.

The pinned source has `CloudDescriptor.isLeader` as a volatile boolean at
line 43, getter at line 97, setter at line 101. Election
`runLeaderProcess` calls `setLeader(true)` at line 264 after ZooKeeper
participant reads at lines 396/450. The target reads the local flag at
lines 982/1013 and compares it to cluster-state leadership at line 1021.
All paths and class hashes are checked by the reused node1/base preflight.
