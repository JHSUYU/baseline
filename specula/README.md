# Specula on GraphChecker's ad hoc coordination checks

[Specula](https://github.com/specula-org/Specula) is an LLM-agent pipeline:
1. code analysis;
2. TLA+ spec generation;
3. a trace-validation harness;
4. model checking and bug hunting with TLC;
5. confirmation of each finding by a reproduction in the real system.

Here it runs as a baseline on the same ad hoc coordination checks: one Specula run per check, given the check's site, the workload test that exercises it, and its starting classes. Each run answers one question: can an execution of the system, under faults in its fault model, reach the check's failing branch? It reports a verdict, every bug it reproduced, and its time, tokens and cost.

| path | what |
| --- | --- |
| [`specula/`](specula/) | Specula's source: upstream `specula-org/Specula` at `39b4a01` plus one commit (`56d8e41`, branch `adhoc-coordination`) that adds the ad hoc mode. Apache-2.0 (`specula/LICENSE`) |
| [`scripts/`](scripts/) | the run scripts used on the CloudLab cluster (paths are hard-coded to `/bulk/specula-adhoc`) |
| `data/<system>/` | per system (HDFS, ZooKeeper, HBase, Solr): `REPORT.md` (every check's verdict and cost), `VERIFIED-BUGS.md`; for HDFS also: inventory and target files, the one ported workload, baseline/reach results, per-case results, the bug classification, and each bug's TLC files |
| [`new-bugs/`](new-bugs/README.md) | the 25 verified new bugs: explanation, TLC files, reproduction, time and tokens |
| [`known-bugs/`](known-bugs/README.md) | the 14 known bugs at their buggy versions: detection result, TLC files, time and tokens |
| [`data/tlc/`](data/tlc/) | the pinned TLC jars (`SHA256SUMS`) every bug's rerun uses |
| [`OPERATIONS.md`](OPERATIONS.md) | the full operating handoff: rules, status, procedures, setup of the remaining systems, pitfalls, TODO (snapshot of `/bulk/specula-adhoc/README.md`, 2026-10-30) |

## What the ad hoc mode adds to Specula

The ad hoc mode is `specula run --adhoc-target=PATH`. The target file is YAML. It holds:
- the check: file, line, method, thrown type, guard as written;
- the workload test;
- `scope_hint` classes;
- the pinned `base_commit`.

The new skill `skills/adhoc-coordination/` scopes every phase to that check. **It gives Specula only the basic ad hoc prompt**, and none of Causym's method (no backward tracing, coordination graph, fault doors or `Phi_o`). Per phase:

- **Phase 1:** Specula's native code analysis, without bug archaeology. The brief names the target and the failing predicate `phi_T`. Its Scenarios are hypotheses, backed by code evidence only.
- **Phase 2:** the spec models the check as `TargetCheck`/`targetFired`, and the property is `TargetSafe == ~targetFired`. There is one `MC_hunt_<scenario>.cfg` per Scenario.
- **Phase 4:** a strict same-bug test. The real system must throw the target's exception at the target's file and line, starting from the workload, injecting only the counterexample's faults and never writing the guard's operands. Phases 1-3 never search history or trackers for the target; Phase 4 may, only after its verdict, to set novelty.
- **Phase 4b:** writes `adhoc-result.json`, which the pipeline validates. Its verdict is one of:
  - `REACHED_CONFIRMED`
  - `REACHED_UNCONFIRMED`
  - `MODEL_ARTIFACT`
  - `NOT_REACHED_BOUNDED`
  - `BLOCKED`

Fixes made while running it on HDFS:
- the acceptance gate's scan budget, 5 s → 60 s;
- a resume no longer invalidates Phase 4's caches (effort tuning identity);
- cache fingerprints are independent of the per-process skill token.

Unit tests: `cd specula && uv sync && .venv/bin/pytest tests/unit -q`. They need Java 21 on `PATH` for one TLC test.

## Results (final, 2026-11-09)

**Setup:** every run used the model `claude-opus-5-5[1m]` on Claude Code CLI 2.1.312, with effort `max` before 2026-11-04 and `high` after (counted together). Time is active time: quota sleeps are excluded.

### 84 ad hoc checks on current code

| system | checks | verdicts | active time | tokens | cost | new bugs (A+B) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| HDFS | 36 | 26 REACHED_CONFIRMED, 10 NOT_REACHED_BOUNDED | 191h39m | 10,776.1M | $5,959.28 | 11 |
| ZooKeeper | 16 | 15 REACHED_CONFIRMED, 1 incomplete | 65h23m | 1,611.8M | $1,323.40 | 7 |
| HBase | 19 | 18 REACHED_CONFIRMED, 1 REACHED_UNCONFIRMED | 70h57m | 1,756.6M | $1,385.45 | 7 |
| Solr | 13 | 12 REACHED_CONFIRMED, 1 not run (counted as no bug) | 26h43m | 728.8M | $448.96 | 0 |
| **total** | **84** | | **354h42m** | **14,873.3M** | **$9,117.09** | **25** |

- **New bugs:** [`new-bugs/`](new-bugs/README.md) has the 25 real, severe, new bugs that make the ad hoc check fail (7 tier A, 18 tier B). Each folder has the explanation, the TLC files with a rerun command, the reproduction, and the time and tokens.
- **Per check:** `data/<system>/REPORT.md` has every check's verdict, time, tokens and cost.
- **Root causes:** `data/<system>/VERIFIED-BUGS.md` has the root causes with file:line citations, and the dropped findings with reasons.
- **Reviews:** `data/verify/VERIFY-batch*.md` and `data/hdfs/VERIFY-*.md` are the independent reviewers' reports.
- **Caveat:** most HDFS runs were not fully independent. Until 2026-11-02, Claude Code's auto-memory let agents read notes from earlier runs on the same node. It was then turned off; the ZooKeeper, HBase and Solr runs are clean.

### 14 known bugs at their buggy versions

Specula ran on each bug's buggy version (the parent of its fix commit), one ad hoc check per bug: the check that the bug makes fail. The fix, the JIRA and the git history were hidden from it.

- **Results:** 11 detected, 1 partly detected (HDFS-5766), 2 not detected (HDFS-17383, ZOOKEEPER-2886).
- **Cost:** 27h42m active, 849.3M tokens, $541.08.
- **Details:** [`known-bugs/`](known-bugs/README.md) has each bug's mechanism, the detection criterion written before the run, Specula's finding, the TLC files and the reproduction.
- **Targets:** the case targets are `data/<system>/targets/*-adhoc-k<N>.yaml`.

## Reproducing a bug's counterexample

```
cd specula/new-bugs/<folder>/tlc        # or specula/known-bugs/<folder>/tlc
java -XX:+UseParallelGC -cp ../../../data/tlc/tla2tools.jar:../../../data/tlc/CommunityModules-deps.jar \
  tlc2.TLC -workers 4 -config <cfg> <root>.tla
```

The exact command is in each folder's `tlc/RERUN.md`; it needs JDK 21. TLC reports the target invariant violated and prints the trace. The older per-finding TLC files of every reproduced HDFS finding remain in `data/hdfs/bugs/`.

## Running it

`OPERATIONS.md` has the procedure:
- the case trees;
- the per-node queues on node0-node4 (claims on the shared `/bulk`; one Claude account per node);
- the after-run checklist (`scripts/tools/post_run.py report|keep`, `record.py`, `results.py`);
- recovery of stuck runs;
- setting up ZooKeeper, HBase and Solr.
