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
| [`data/hdfs/`](data/hdfs/) | HDFS: inventory and target files, the one ported workload, baseline/reach results, per-case results, the bug classification, and each bug's TLC files |
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

## Results so far (HDFS; 2026-10-30)

The 84 checks are HDFS 36, ZooKeeper 16, HBase 19, Solr 13. **HDFS is in progress:**
- 24 of 36 runs finished;
- the first 15 are processed in `data/hdfs/RESULTS.md` (per-phase numbers) and `data/hdfs/CLASSIFICATION.md`;
- the other systems are not set up yet (`OPERATIONS.md` §7).

Each run used the pinned model `claude-opus-5-5[1m]` and Specula's default effort (`max`), on Claude Code CLI 2.1.312.

| case | verdict | wall | runtime | tokens (cached) | cost |
| --- | --- | --- | --- | --- | ---: |
| hdfs-adhoc-05 | NOT_REACHED_BOUNDED | 6h01m | 3h18m + Phase 3 unrecorded | 174.7M (168.8M) | $96.71 |
| hdfs-adhoc-06 | NOT_REACHED_BOUNDED | 9h05m | 4h31m + Phase 3 unrecorded | 328.3M (318.1M) | $178.14 |
| hdfs-adhoc-07 | REACHED_CONFIRMED | 9h29m | 5h00m + Phase 2.5 unrecorded | 303.2M (294.2M) | $159.65 |
| hdfs-adhoc-08 | REACHED_CONFIRMED | 9h07m | 1h53m + Phases 1, 4a unrecorded | 253.0M (244.1M) | $148.60 |
| hdfs-adhoc-09 | REACHED_CONFIRMED | 11h08m | 4h38m + unrecorded | 378.8M (368.1M) | $190.40 |
| hdfs-adhoc-10 | REACHED_CONFIRMED | 4h43m | 3h52m | 199.4M (192.5M) | $115.54 |
| hdfs-adhoc-11 | REACHED_CONFIRMED | 11h21m | 5h36m + unrecorded | 470.5M (454.8M) | $259.50 |
| hdfs-adhoc-14 | REACHED_CONFIRMED | 14h35m | 3h37m + unrecorded | 314.4M (305.6M) | $152.01 |
| hdfs-adhoc-15 | NOT_REACHED_BOUNDED | 20h01m | 5h56m + unrecorded | 396.9M (385.2M) | $204.79 |
| hdfs-adhoc-16 | NOT_REACHED_BOUNDED | 11h24m | 7h49m | 355.3M (347.8M) | $152.67 |
| hdfs-adhoc-19 | NOT_REACHED_BOUNDED | 7h25m | 5h24m | 217.0M (211.2M) | $107.65 |
| hdfs-adhoc-20 | REACHED_CONFIRMED | 11h04m | 6h23m | 453.8M (437.8M) | $269.16 |
| hdfs-adhoc-21 | NOT_REACHED_BOUNDED | 6h08m | 4h03m | 164.6M (159.4M) | $90.98 |
| hdfs-adhoc-22 | NOT_REACHED_BOUNDED | 7h43m | 5h39m | 242.5M (236.2M) | $118.50 |
| hdfs-adhoc-23 | NOT_REACHED_BOUNDED | 10h20m | 5h33m | 280.4M (272.6M) | $142.13 |
| **15 runs** | 7 reached, 8 not | | | 4,533M (4,396M) | **$2,386.43** |

How to read the time and cost columns:
- **Wall time** runs from the case log's first start to its last finish. It includes the account's 5-hour usage-limit waits, 1-8 h per run.
- **Runtime and cost** are the `Total` row of the run's `summary.md` (every agent session and retry included).
- **"Unrecorded"** marks a phase whose runtime was not recorded because its session was interrupted (a pause on 2026-10-29). Its tokens and cost are still counted.

**Bugs.** The runs reproduced 17 candidate new bugs, plus known ones: HDFS-17563, HDFS-13441, HDFS-16136, HDFS-15651/13473. The 25 findings with a TLC counterexample have their TLC files, an index and a class each in [`data/hdfs/bugs/`](data/hdfs/bugs/README.md). **Their novelty is not yet independently confirmed and nothing is filed.**

## Reproducing a bug's counterexample

```
cd specula/data/hdfs/bugs/<case>/<finding>
java -cp ../../../../tlc/tla2tools.jar:../../../../tlc/CommunityModules-deps.jar tlc2.TLC -workers 4 -config <cfg> <root>.tla
```

The exact command is in each folder's `RERUN.md`. TLC reports the target invariant violated and prints the trace.

## Running it

`OPERATIONS.md` has the procedure:
- the case trees;
- the per-node queues on node0-node4 (claims on the shared `/bulk`; one Claude account per node);
- the after-run checklist (`scripts/tools/post_run.py report|keep`, `record.py`, `results.py`);
- recovery of stuck runs;
- setting up ZooKeeper, HBase and Solr.
