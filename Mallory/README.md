# Mallory baseline for ad hoc coordination checks

The primary implementation uses a source-built port of GraphChecker to guide
fault injection in the existing cluster-based JUnit tests for HDFS 3.4.3,
HBase 2.6.6, Solr 8.11.4, and ZooKeeper 3.8.7. Each check is identified by
its exact branch and exception site in the 102-check inventory. The JUnit
method is the workload; its source is not edited to manufacture an oracle.
Docker clusters and the earlier Mallory occurrence-graph loop are not part of
this path.

## Native execution path

```text
inventory check + original JUnit
          |
          v
GraphChecker static seed analysis (Soot, regions, demanded sites, ports)
          | original scope map, candidate graph, region skeletons
          v
GraphChecker REGION_STATE weave + fault-free JUnit recording
          | observed target occurrence, I/O doors, branch outcomes
          v
original Recorder / optional Scheduler / Finalizer
          | target region plan and exact occurrence IDs
          v
fresh JUnit JVM per fault sequence ---> original trace + fault receipts
          |                                  |
          +---------- GraphChecker closure and graph delta <------------+
                              |
                              v
                   update the resumable fault queue
```

`static_scope_port/original_engine` contains the pinned GraphChecker source
closure and adapters to its original static analyzer, recorder, scheduler, and
runtime planner. Its provenance is recorded in
`static_scope_port/original_engine/UPSTREAM_SOURCES.json`. The original
GraphChecker source is built inside this repository; the active path does not
load a live `GraphChecker/target` JAR. The original static analysis proposes
regions and I/O sites. A system adapter supplies protocol-wide transport
mapping where GraphChecker cannot infer the carrier, and the runtime records
which selected sites and exchanges actually occurred.

The healthy run establishes the target and initial queue. Each fault trial
starts a fresh JVM using the same woven classes and original JUnit method.
`native_graphchecker_feedback` reads the trial's original GraphChecker
session or REGION_STATE plan and computes changes in observed target-closure
region families, paired communication or state edges, and branch outcomes.
`native_graphchecker_campaign` uses those deltas, exact fault identities,
and queue age to choose later single- or multi-fault sequences. A missing
target, unmatched injection, or unpaired transport is recorded as such;
static may-edges are not counted as observed communication. A target
exception requires an exact `TARGET_THROW` receipt after a matched
injection. A JUnit assertion or process exit alone does not establish that
observation.

## Four-system preparation

| System | Native preparation and protocol source |
| --- | --- |
| HDFS | `native_graphchecker_dispatch/hdfs_native_adapter.py`; `adapters/hdfs/graphchecker_port/native_original/` builds the original-runtime IPC and SASL bridge from generic HDFS source anchors. |
| HBase | `adapters/hbase/native_graphchecker_port/` applies checked MiniCluster, RPC, procedure, and meta-state source hooks and supplies its original-runtime JUnit runner. |
| Solr | `adapters/solr/native_graphchecker_port/prepare_case.py` derives scope, weave, and campaign inputs from inventory; `adapters/solr/graphchecker_port/native_original/` contains the pinned transport patch and runner. |
| ZooKeeper | `native_graphchecker_dispatch/zookeeper_native_adapter.py` prepares a system-wide recipe; `adapters/zookeeper/native_graphchecker_port/` supplies the original-runtime quorum and client protocol post-pass. |

The adapters select a transport family or source-backed hook, not a fault site
for an individual check. The native preparation gate requires source identity,
static scope, a passing unchanged healthy JUnit, and an observed target.
Concolic mode also selects a recording-derived task plan before admission.
REGION_STATE can skip the ahead-of-campaign Scheduler: its first fault-free
trial builds the original Recorder/Finalizer target plan before any fault is
queued. The availability and quality of these proofs vary by check. See
`native_graphchecker_dispatch/README.md` and each adapter README for inputs
and commands; preparation by itself is not a completed fuzz run.

`native_graphchecker_campaign/README.md` defines the pinned campaign
manifest, fault selector, budgets, oracle, and restart behavior. The three-host
`native_graphchecker_queue/README.md` describes isolated workers and audited
completion receipts. A terminal case is not rerun on resume. The authoritative
102-row result table is generated from those receipts at
`data/mallory/native_graphchecker_queue/native-102-results.{json,tsv}`; it
records source location, original JUnit, trial counts, elapsed time, target
reach, exact throw count, and evidence limitations. Historical CrashFuzz and
earlier custom-graph Mallory results are separate datasets.

## Build and tests

From the repository root, build the source port and its dependency classpath,
then run the native Python contract tests:

```sh
mvn -q -f Mallory/static_scope_port/original_engine/pom.xml \
  test package dependency:build-classpath \
  -Dmdep.outputFile=target/native-original-dependencies.txt
python3 -m Mallory.run_tests
```

`run_tests.py` defaults to native feedback, campaign, dispatcher, queue,
fault adapter, and system adapter tests. Use
`python3 -m Mallory.run_tests --legacy` only for the archived custom-graph
`core` and `report` tests. Maven tests and Python contract tests are
separate from a real four-system campaign: only case-specific closed traces,
exact fault receipts, and the audited result table support a result claim.

## Current boundaries

GraphChecker needs matched transport identities and sufficient protocol hooks
to reconstruct a cross-process edge. Missing carrier data remains a gap.
REGION_STATE feedback uses the original Recorder/Finalizer plan and exact IDs;
the post-run native-session mode uses the original `SessionReader`,
`Corpus`, `Branches`, and `ClosurePlanner`. These modes have different
trace formats; an occurrence ID or local event sequence is not assumed stable
across fresh JVMs. A budget-complete case can still have a graph-attribution
limitation, which the result table must preserve.
