# Original cluster JUnit campaign bootstrap

This inventory joins `selection102.json` to the four existing `*-TEST-MAP.json`
files and checks each target source, test source, Java class, and method
declaration against the original system source trees. It records a **source
verified original cluster JUnit workload** for 98 cases and an evidenced
`no_cluster_test` mapping gap for four. This does not establish that any
target guard was reached at runtime or that the JUnit passed in this workspace.

## Coverage of the selected 102

| System | Original cluster JUnit mapped and source verified | No mapped original cluster JUnit |
| --- | --- | --- |
| HBase | 29: 01, 02, 04, 07, 08, 10–24, 28–35, 37 | 27 |
| HDFS | 37: 01, 07–12, 14–35, 37, 39–40, 43, 48–50, 52 | 13 |
| Solr | 21: 01, 05–07, 09–10, 13–16, 18–19, 21–22, 31, 34, 36–40 | none |
| ZooKeeper | 11: 01–07, 10–13 | 08–09 |

The exact 102 IDs, full JUnit names, source locations, evidence, and starter
paths are in `catalog/CASE-ID.json`. The four excluded records retain the
existing map evidence:

- `HBASE-27`: private RegionServer startup wait plus simultaneous stop; the
  closest `TestRegionServerNoMaster` stops the master after the RS starts.
- `HDFS-13`: the HDFS map records no named test method or test source for the
  selected block token password check.
- `ZOOKEEPER-08`: the existing map has a non-cluster positive control and
  real-quorum candidates, but none is shown to reach the selected learner
  `checkSession` guard.
- `ZOOKEEPER-09`: real-quorum candidates exist, but none is shown to put a
  missing or closing local session through the selected learner `setOwner`
  guard.

`HDFS-18` has a real `TestSecureAliasMap` MiniDFSCluster JUnit source mapping,
but the current checklist calls it `no_cluster_test`: the selected
`injectStorage` target is only a setup path and has no measured runtime hit.
The catalog preserves this distinction and `next` skips it while that
checklist status remains. All other mapped rows also need runtime target-hit
verification before fault trials.

## CLI

Run from any directory:

```sh
python3 /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/bootstrap/bootstrap.py audit
python3 /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/bootstrap/bootstrap.py build
python3 /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/bootstrap/bootstrap.py validate
python3 /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/bootstrap/bootstrap.py next --system hdfs
```

`next` atomically issues one unissued, mapped case under `issued/`. By default,
it skips checklist cases with existing fault trials or an active, completed, or
excluded status; use `--case CASE-ID` to select an eligible ID, or
`--include-active` when resuming an explicitly chosen active case. A second
concurrent caller gets a different case because creation uses an exclusive
file open. `validate` rejects stale catalog entries, missing test declarations,
paths outside the original source root, or writable workspaces outside their
per-case bootstrap directory.

Each starter names the selected target identity, exact original JUnit method,
system test command, a coarse I/O scope hint, an initially unfiltered I/O
scope, a 48 trial / 4 fault budget, a 96 / 6 continuation budget, and paths
for the healthy trace and resumable state/result checkpoints. I/O markers and
selectors must come from that case's healthy runtime trace. No graph,
aggregate, or closure output is part of this bootstrap.

The issued starter is **not yet a `core-fuzzer/fuzzer.py` run config**. Its
`system-test/` workspace must first be populated with an isolated copy of the
original source, then the original JUnit must run with instrumentation that
records a healthy trace and passes fault options to the same JUnit for each
trial. The `required_before_campaign` list in each starter records those
gates. Source trees are read only inputs; build and test writes belong in
the per-case workspace. Solr's source uses Ant; `ant` was not on `PATH` during
this audit, so Solr commands have not been executed here. ZooKeeper's
`ZOOKEEPER-10` JUnit method is parameterized; the given Maven selector runs
both boolean values and the trace must identify the intended invocation.

The examples in `issued/` were selected from cases with no recorded fault
trials: HBASE-02 (`TestConnectionImplementation#testMetaLookupThreadPoolCreated`),
HDFS-01 (`TestPread#testPreadDFS`), SOLR-05
(`AddReplicaTest#testAddMultipleReplicas`), and ZOOKEEPER-03
(`SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLearner`), plus
HDFS-50 (`TestSnapshotCommands#testCreateSnapshot`). Their
original JUnit commands and isolated paths are recorded in those files.
