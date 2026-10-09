# Mallory case inventory

Run `python3 Mallory/cases/inventory.py` from the baseline repository to rebuild
`inventory.json`. The generator reads the original 102 selected sites in
`data/crashfuzz/selection102.json`, the historical result table in
`data/crashfuzz/checklist102.json`, and the versioned source trees listed in
`inventory.py`. The two later HDFS known-issue controls are stored separately
under `known_issue_controls`.

Each row records the exact target site, source hash, a resolved unit-test
selector and source hash where available, a build-command template, and the
source revision. A source-mapped test is only a **candidate workload**. The
Mallory runner must first execute a fault-free seed and verify the specific
target occurrence and cluster fixture. `build.validated_by_execution` remains
false until that command is actually exercised. Previous CrashFuzz outcomes
are historical context and do not determine Mallory eligibility or count as
Mallory results.

The selected test method for a parameterized test names the Java method. Its
Maven selector may run more than one parameter variant; bind the target to a
specific observed occurrence before injecting. Rows without a mapped test
remain in the original 102-site checklist with `no_mapped_cluster_test` so a
later mapping can be added without changing case identity.

Current source inspection maps 100 original sites to candidate test methods.
`HBASE-23` and `HDFS-13` have newly proposed cluster tests with their source
reasoning recorded in `workload.mapping_evidence`. `ZOOKEEPER-08` and
`ZOOKEEPER-09` remain unmapped to a real-quorum test; the existing
`SessionTrackerCheckTest` exercises the tracker directly and does not establish
the requested cluster workload.

Build the Java agent with `mvn -f Mallory/instrumentation/pom.xml test package`,
then run `python3 Mallory/cases/inventory.py` and
`python3 Mallory/cases/generate.py`. The latter writes one `<ID>.json` and
`<ID>.sites.json` for each source-mapped check, plus `mapping_audit.json`.
HDFS and ZooKeeper mappings use the compiled classes in their pinned isolated
worktrees; HBase and Solr use pinned distribution class bytes. A case config
records the selected class hash and exact branch and throw IDs. The healthy
trial must observe those exact IDs in its loaded-class catalog before fault
trial 1. The standard agent JAR path is reproducible from its Maven source;
the generated config and every trial pin its SHA-256.

The current standard JAR is the earlier ordinal build used by active runs.
Agent source now includes the SafeWriter fix; a fresh build has a different
hash. Existing run receipts remain pinned to their original bytes. A release
switch of reusable templates to the SafeWriter build requires adapter and
per-case healthy validation. `HDFS-48` has a separate successful healthy
retest with that build.

The pinned Solr tree uses Ant, which is unavailable on node0, node1, and
node2. The 21 Solr configs therefore use the direct JUnit runner in
`Mallory/adapters/solr/run_pilot.py` on node2's isolated, byte-identical
source worktree. The runner compiles the selected source test into each
trial's scratch directory, verifies its SHA-256, and runs the original JUnit
method with the Solr instrumentation adapter. SOLR-05 has an explicit
source-reviewed I/O door; the other Solr configs enable I/O-door discovery
inside the exact target class. Runner reachability, target reach, and door
availability remain pending for each healthy calibration. The generic
`Mallory/cases/SOLR-*.json` templates are calibration
scaffolding only. Fault work uses the Solr adapter's immutable versioned
runner and JAR configs after an exact healthy seed. Source review found
that `SOLR-15`, `SOLR-16`, and `SOLR-34` select inner guards that require an
enclosing failure branch. Their healthy nonthrowing seed is source-infeasible,
so they remain in the 102-row inventory with dispatch disabled. `SOLR-16`
maps the changed-owner guard `@539:branch:41`; its former `@536:branch:40`
mapping belonged to `SOLR-15`.

The 38 HDFS configs use the clean isolated Hadoop 3.4.3 worktree and warm
`surefire:test` after a pinned build. The five checks implemented through
`Preconditions` calls use exact invocation-exception probes; the catalog
verified their bytecode IDs, but MiniCluster runtime reach still requires
per-case calibration. `HDFS-11`, `HDFS-12`, and `HDFS-14` use a class-level
Surefire filter because the method-level filter executed zero tests for their
JUnit Parameterized class. The replacement still requires a real nonzero test
count and exact target reach. `HDFS-13` is held: its selected MiniCluster test
executes the six-argument token check, while its target is the four-argument
overload. The source and first healthy run are recorded in
`hdfs_test_mapping_recommendations.json`.
`HDFS-43` and `HDFS-49` now select independently verified smaller MiniDFS
tests in the isolated lane2 worktree. `HDFS-43` reached its exact check seven
times; `HDFS-49` reached its exact check once without the earlier large
workload's trace truncation. Both had named `nn0` targets and no selected
throw. Their first-pass evidence is retained, and neither healthy calibration
counts as a fault trial. See `calibration_alternates.json` for evidence hashes.

The 30 HBase configs use the pinned direct-Java `SelectedJUnit` runner on
node1, including pinned agent, adapter, runner, launcher, test JAR, and
site-file hashes. `HBASE-01` retains its original running lane; the other 29
use an isolated lane2 source/runtime and `-ea` for Java assertions. The
independent HBASE-02 lane2 healthy pilot verifies its named target and
closure; each other check still needs its own healthy calibration. Source-only
review of all 30 selected tests is in `hbase_test_mapping_recommendations.json`.
The HBASE-11 selected test deliberately throws at the target; an existing
normal-move MiniCluster test is proposed for separate healthy calibration.
The HBASE-16 selected crash/backoff test also throws at its target. The
HBASE-17 workload reached the HBASE-16 guard without a throw in a different
case's trace, but HBASE-16 needs its own validation before its selector changes.

The ZooKeeper configs use the patched isolated 3.8.7 source overlay and its
receipt. `ZOOKEEPER-02` and `ZOOKEEPER-03` now select the three-peer
`QuorumTest#testMultiToFollower` workload. An independent healthy calibration
observed both checks on named node `zk2`, 114 fault doors, and no target throw.
The older `testSessionMoved` selector remains recorded as an unsuitable
oracle because it deliberately exercises session-move rejection. All cases
still require the case runner's own healthy seed before a fault campaign.
`ZOOKEEPER-13` is also held: its selected `testGlobalSessionInRO` deliberately
expects global-session rejection at the target. The inventory records
`testConnectionEvents` and `testReadOnlyClient` as alternate local-session
quorum tests, pending exact target and no-throw calibration.

Every generated config sets `calibration_only: true`. A successful healthy
test must reach the intended target occurrence on a named logical node,
leave the selected exception unthrown, and expose an injectable I/O door in
its causal closure. A passing JUnit alone does not establish eligibility.
Distinct occurrences of the same check are tracked separately. The independent
`ZOOKEEPER-11` healthy pilot used the pristine class; the patched overlay
has a different class hash, so that pilot is retained as provenance and cannot
silently promote a patched campaign.

The proposed per-case budget is one healthy seed plus at most 80 fault trials,
one hour, and at most six faults per trial. These are ceilings, not reported
achievements. The trial timeout uses three times the historical healthy
duration plus 60 seconds, bounded to 180–1200 seconds when a historical
duration exists; otherwise the system default remains provisional.

`HDFS-01` retains a warning that its proposed `TestPread` workload
intentionally catches some read errors, and lists an alternate MiniDFS test.
Only healthy trace calibration can settle whether either workload satisfies
the selected target oracle. `ZOOKEEPER-08` and `ZOOKEEPER-09` have no mapped
real-quorum test and remain undispatched.
