# Graph-free coverage-guided fault injection

This is the current baseline for the ad hoc coordination study. It runs each selected original cluster JUnit workload, observes runtime I/O points and the selected target check, injects ordered I/O exceptions using exact runtime identities, and uses production code coverage and new I/O families to prioritize later fault sequences. An exact target exception after an applied fault is a review candidate; its meaning is decided from replay and source code. No causal graph, backward closure, region skeleton, or GraphChecker runtime is used by the campaign.

## Layout

- `core-fuzzer/`: common fault-sequence queue, runtime trace parsing, exact match checks, target oracle, checkpointing, and coordinator.
- `cases/<ID>/`: case-specific workload adapters, instrumentation sources, campaign logic, review notes, and `reproduce.sh` for every selected check.
- `entrypoints.json`: one explicit original JUnit test, target source location, current campaign runner, and instrumentation source index per check. Shared runners are identified by `shared_campaign_checks`.
- `hdfs-*`, `qjm-rpc-actor-v2/`, `hbase-namespace-actor-v2/`, `zk-actor-v2/`: shared system adapters used by the selected cases.
- `vendor/`: one copy of each case-local JAR dependency; case paths are relative symlinks to these files.
- `checklist.py` and `audit_checklist.py`: render and audit the final table in `../data/`.

Final results, measured time, selection metadata, and recorded run artifacts live in [`../data/`](../data/README.md). Symlinks in case directories preserve paths expected by the original campaign code. The source for each current case instrumentation agent is indexed in `entrypoints.json`.

## One check

```sh
./cases/HDFS-54/reproduce.sh           # show the selected test, check and runner
./cases/HDFS-54/reproduce.sh --check   # validate its local entrypoint
./cases/HDFS-54/reproduce.sh --run     # invoke its original JUnit fault campaign
```

`--run` invokes the recorded case-specific campaign, including its existing checkpoint behavior. A completed checkpoint may stop immediately. Campaigns that do not expose a separate output argument write in their case directory; use an isolated checkout when restarting or extending one. For the 17 checks marked `no_cluster_test`, `no_usable_cluster_test`, or `source_excluded`, the script explains the recorded screening result and exits with status 3 instead of pretending to run a test. There are 102 originally selected checks and two separately marked HDFS known-issue controls.

To check the complete layout and reproduce the table from case records:

```sh
python3 reproduce.py --check-all
python3 checklist.py render
python3 audit_checklist.py --require-terminal
cd core-fuzzer && python3 -m unittest -q
```

The per-case runners retain the original source-version and dependency requirements recorded in their READMEs. A path named `.graphchecker-sources` in a runner refers to an external checkout of the system source; it is not a GraphChecker runtime dependency.
