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

## Results so far (2026-11-02)

The 84 checks are HDFS 36, ZooKeeper 16, HBase 19, Solr 13.

**Status:**
- HDFS: 28 of 36 runs finished.
- ZooKeeper (15) and HBase (15) are running.
- Solr is prepared but not started (`OPERATIONS.md` §2, §7).

**Setup:** every run used the model `claude-opus-5-5[1m]` and effort `max`, on Claude Code CLI 2.1.312.

**HDFS results:**
- Per case, with time, tokens, cost and per-phase numbers: [`data/hdfs/RESULTS.md`](data/hdfs/RESULTS.md).
- 28 runs: $4,864, 9,098M tokens.
- 19 REACHED_CONFIRMED, 9 NOT_REACHED_BOUNDED.

**Source-verified HDFS bugs that make the ad hoc check fail** ([`data/hdfs/VERIFIED-BUGS.md`](data/hdfs/VERIFIED-BUGS.md)). Each was reviewed by an independent verifier against the code, and the decisive code was read again by the operator. None is reported upstream or fixed on trunk.

| tier | case/finding | bug | impact |
| --- | --- | --- | --- |
| A | 07/MC-1 | JournalNode purge marks a restarted JN's live segment `.stale` | an acknowledged edit is lost after failover |
| A | 11/MC-4 | `FileChecksumHelper` retry does not restore `remaining` | `getFileChecksum` silently returns a wrong checksum |
| A | 38/MC-1 | LAZY_PERSIST inherited by existing files | append refused; the scrubber deletes DISK files |
| A | 24/MC-2 | a disk formatted during an unfinalized upgrade gets the new cTime and no `previous/` | the documented rollback cannot complete |
| A | 08/MC-1 | epoch selection reads only a quorum's promises | a JN fences the new writer for its whole term |
| B | 08/MC-2, 24/CR-6, 24/MC-3, 11/MC-1, 14/MC-1, 26/MC-1 | rollback, volume-failure, rolling-upgrade, safe-mode, derived-QOP and DN-upgrade defects | narrower triggers or lower severity |

**Caveat:** most HDFS runs were not fully independent. Claude Code's auto-memory let agents read notes from earlier runs on the same node until 2026-11-02, when it was turned off. The ZooKeeper, HBase and Solr runs are clean.

**Preparation of the other systems:** each `data/<system>/` holds the inventory, the targets, the ported workloads (with porting records) and `baseline/REACH.tsv` (every workload passes on upstream and reaches its check method; Solr's case 22 is blocked).

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
