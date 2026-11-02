# Specula on ad hoc coordination checks (HDFS, ZooKeeper, HBase, Solr)

Specula is one of the Causym paper's baselines. Each Specula run checks **one** ad hoc coordination check: the same check site, workload test and starting classes that the paper's own tool used. The run answers one question: can an execution of the system, under faults in its fault model, reach the check's failing branch? It reports a verdict, every bug it reproduced, and its time, tokens and cost.

This file is the handoff to the next agent. It is current as of **2026-11-02 21:05 UTC**.
- §0: what to do first.
- §1: the owner's decisions and the standing rules.
- §2: status and results.
- §3-§6: code, machines, layout and procedures.
- §7: per-system notes, including the open decisions for Solr.
- §8: pitfalls already hit.
- §9: the TODO list.
- §10: the 84 checks.

## 0. Start here

1. Read §1, §2, §8 and §9.
2. Check the live state:
   ```
   for s in hdfs zookeeper hbase; do head -qn1 /bulk/specula-adhoc/$s/queue-status.*.txt; done   # one queue per node per system
   python3 /bulk/specula-adhoc/summarize.py <system> --tsv     # per case: verdict, state, wall, runtime, waits, tokens, cost
   /bulk/specula-adhoc/wait_all.sh 540                        # blocks until a case of any system finishes or needs the operator
   ```
3. **What is running (left running on purpose; the owner asked me to stop my own work, not the runs):**
   - the queues: `queue.py` for hdfs on node0 and node2; for zookeeper and hbase on all five nodes;
   - their Specula runs;
   - `tools/sync_credentials.sh` on node2, which keeps every node's Claude login fresh. It must keep running while runs run.

   To stop everything:
   - kill each `^python3 queue.py` process on each node;
   - then run `tools/stop_run.sh <case>` per running case;
   - avoid stopping a case in Phase 4 (§8).
4. As each case finishes, do §6.2. When a system is done, do §6.4. Then prepare and run Solr (§7.4).

## 1. Decisions and standing rules

**Owner decisions:**

1. **One Specula version.** There is only the current Specula. An older Causym-hinted version and all its runs were deleted on 2026-10-29; never compare with it, and never call anything v1/v2.
2. **Basic ad hoc prompt only.** Specula gets the target, the oracle `TargetSafe == ~targetFired`, the fairness rules, per-phase scoping, the strict same-bug test and the result file. It gets **none of Causym's method** (§3).
3. **84 checks, one run per check:** HDFS 36, ZooKeeper 16, HBase 19, Solr 13 (§10).
4. **Do not measure Specula against GraphChecker.** Report each case on its own terms: verdict, bugs, time, tokens, cost. GraphChecker is only the source of each target's site, workload and starting classes.
5. **Parallel runs.** Several checks run per node, K=5 for HDFS and K=3 per system for the others, on all five nodes, without conflicts (claims, private case trees). Systems may run at the same time.
6. **One Claude account.** Every node uses the owner's current account (2026-11-02); node0's own login is backed up as `~/.claude/.credentials.json.node0-own-account.bak`.
7. **Bug bar for the final list:** only **high-quality, severe bugs that really make the ad hoc check fail**. Each one must:
   - throw the target exception at the target line in the real system;
   - be real: a realistic trigger, not designed behaviour, not already reported;
   - be severe: data loss, a wrong result, a crashed or wedged component, or lasting loss of availability or redundancy.

   **Read the source yourself for every bug you keep** (the owner asked for this explicitly). The source-verified HDFS list is `hdfs/VERIFIED-BUGS.md`.
8. **For every case, record** wall time, runtime, usage-limit waits, tokens, cost, the per-phase split, the model and the CLI. Keep every bug's TLC files.
9. **Code and results are published** in GitHub `JHSUYU/baseline`, folder `specula/`. Specula commit `56d8e41`; the results snapshot is updated as of this handoff. Ask before every push.

**Standing rules:**
- **L1 inputs only.** Nothing GraphChecker computed goes into a target, tree or prompt.
- **Agents never see GraphChecker.** Strings banned from anything an agent reads: `GraphChecker`, `graphchecker`, `Causynth`, `Causym`, `causym`, `/bulk/GraphChecker`, `/bulk/wt`. After every run `tools/post_run.py report` greps the agent logs; 0 hits so far.
- **Neutral case ids.** Bug points: `zk-adhoc-b1`…`b6`, `solr-adhoc-22`.
- **Every run has auto-memory off** (`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, set by `run-case.sh`), so no notes carry over between runs (§8).
- **Pinned setup:** model `claude-opus-5-5[1m]`, Specula's default effort `max`, Claude Code CLI 2.1.312 with `DISABLE_AUTOUPDATER=1`.
- **Ask the owner before:** any git commit or push, filing JIRAs or PRs, deleting run outputs or kept bug files, and changing these rules.

## 2. Status and results (2026-11-02 21:05 UTC)

| system | checks | finished | running | waiting | notes |
| --- | ---: | ---: | ---: | ---: | --- |
| HDFS | 36 | 28 (all processed and source-verified except 33: TLC kept, verification pending) | 8: 34 39 40 45 48 49 50 52 | 0 | |
| ZooKeeper | 16 | 0 | 15 | 1 (b6) | prepared, §7.2 |
| HBase | 19 | 0 | 15 | 4 (21 22 24 28) | prepared, §7.3 |
| Solr | 13 | 0 | 0 | 13 | **prepared but not started**: open decisions in §7.4 |

**HDFS results:** `hdfs/RESULTS.md` (per case and per phase), `hdfs/CLASSIFICATION.md` and `hdfs/CLASSIFICATION-batch2.md` (every reproduced finding classified), `hdfs/VERIFY-*.md` (independent source reviews), `hdfs/VERIFIED-BUGS.md` (the final list).
- The 28 finished runs cost **$4,864**, for 9,098M tokens (8,816M cached).
- Verdicts:
  - **19 REACHED_CONFIRMED:** 07 08 09 10 11 12 14 20 24 25 26 28 29 30 31 33 35 37 38.
  - **9 NOT_REACHED_BOUNDED:** 05 06 15 16 19 21 22 23 27.
- "Reached" is Specula's verdict. Whether the reproducing bug is real, severe and new is the separate verification below; many reached checks yield only by-design or known behaviour.

**Source-verified HDFS bugs that make the ad hoc check fail** (`hdfs/VERIFIED-BUGS.md`):

| tier | case/finding | bug | impact |
| --- | --- | --- | --- |
| A | 07/MC-1 | the JournalNode purge marks a restarted JN's live segment `.stale` (`currentInProgress` is null after restart) | **an acknowledged edit is lost** after failover |
| A | 11/MC-4 | `FileChecksumHelper` retry does not restore `remaining` | `getFileChecksum` **silently returns a wrong checksum** |
| A | 38/MC-1 | LAZY_PERSIST inherited by existing files (append refused; the scrubber uses the inherited policy) | **the scrubber deletes DISK files**: data loss |
| A | 24/MC-2 | a disk formatted during an unfinalized upgrade gets the new cTime and no `previous/` | **the documented rollback cannot complete** |
| A | 08/MC-1 | epoch selection reads only a quorum's promises | a JN fences the new writer for its whole term: **no JN redundancy** |
| B | 08/MC-2 | `doRollback` keeps the cached promise | JN left running fences the next writer |
| B | 24/CR-6 | a failed volume load is only logged; finalize deletes its `previous/` | needs `failed.volumes.tolerated` ≥ 1 |
| B | 24/MC-3 | a stale rolling-upgrade marker deletes a regular upgrade's `previous/` | narrow window |
| B | 11/MC-1 | safe mode stops block-key pushes while keys roll | after about 10 h in safe mode |
| B | 14/MC-1 | derived-QOP re-sign keeps the wrong keyId | non-default flag |
| B | 26/MC-1 | a DN's block-pool upgrade deletes an unfinalized `previous/` | needs two rolled-back upgrades |

Dropped:
- 09/MC-1 = HDFS-5058, Won't Fix;
- the 10 cases = HDFS-3726/HDFS-17563 or by design;
- 20 = assertion-only;
- the 28/29/30/31 block-recovery and pool-teardown findings = HDFS-4701/4843/15651 handling;
- and others (see `VERIFIED-BUGS.md` "Dropped").

**Caveat (2026-11-02):** most HDFS runs were **not independent**. Auto-memory let agents read notes from earlier runs on the same node (§8). The bugs are real, verified in code, but per-run numbers and "found from the check alone" carry this caveat. ZooKeeper, HBase and Solr runs are clean.

## 3. Specula code

- **Repository:** `/users/ZhenyuLi/Specula`, branch `adhoc-coordination`, commit **`56d8e41`** on upstream `39b4a01`. It was committed locally on 2026-11-01 and copied to GitHub `JHSUYU/baseline` `specula/specula/`; Specula's own upstream was not pushed.
- **The ad hoc mode:**
  - `specula run --adhoc-target=PATH` turns it on.
  - The skill `skills/adhoc-coordination/` (guide plus references) scopes each phase. Phase 1 is Specula's native Code Analysis plus the ad hoc section.
  - Phase 4's same-bug test requires the target's exception at the target line, with the stack frame shown.
  - Phase 4b writes `adhoc-result.json`, which the pipeline validates.
- **Fixes made during the runs:**
  - `stop_gate.SCAN_TIMEOUT_S` 5 s → 60 s;
  - `confirmlib._tuning_identity` treats an explicit `max` as the default, so a resume no longer invalidates Phase 4's caches;
  - `skill_refs.stable_skill_refs`.
- **Tests:** `PATH=/bulk/specula-adhoc/jdk/jdk-21.0.13+9/bin:$PATH .venv/bin/pytest tests/unit -q` (1616 pass).
- **Skills are symlinks** (`Specula/.claude/skills` points into `skills/`), so an edit reaches **runs in flight**. Change them only between runs.
- **The skill's Ant notes (`references/java-harness.md`) are wrong for Solr**:
  - Ivy is loaded with `ant -lib $IVY_USER_DIR/lib`, not `-Divy_install_path`;
  - tests need `-Dtests.useSecurityManager=false`;
  - mention `-Dtests.nightly=true` and `-Dtests.awaitsfix=true`;
  - `-Dargs` must keep `-XX:TieredStopAtLevel=1`.

  Fix this **before Solr runs start** and rsync it to the nodes. Solr's targets already carry the right `test_command`.
- **Code is copied per node.** After any code or skill change:
  ```
  cd /users/ZhenyuLi && for n in node0 node1 node3 node4; do rsync -a --exclude=/runs --exclude=__pycache__ Specula/src Specula/tests Specula/skills $n:/users/ZhenyuLi/Specula/; done
  ```

## 4. Machines, account, environment

- **node0-node4:** 64 cores and 376 GB each.
- **`/bulk`** is node0's disk over NFS. It holds trees, runs, logs and scripts, and has about 800 GB free.
- **Local per node:** `/users/ZhenyuLi` holds the Specula copy, CLI 2.1.312 and `~/.claude`.
- **Account:** every node uses the owner's account. `tools/sync_credentials.sh` runs on node2 (log: `/bulk/specula-adhoc/sync-credentials.log`). Every 5 min it copies the freshest `~/.claude/.credentials.json` (by `expiresAt`) to every node, so all nodes follow one refresh-token chain. If a node shows "Not logged in", rerun it once with `--once`.
- **Quota:** each account has a 5-hour and a 7-day quota. When either passes Specula's limit, the run logs `Quota: … sleeping Ns` and waits by itself.
  - A run asleep on a quota that no longer applies can be restarted with the `--fresh-context` resume (§6.3).
  - If the 7-day quota runs out again, all runs sleep until it resets.
- **The agent shell is zsh:** unquoted variables are not word-split, and `$B:e…` is a modifier, so use `${B}`. Use `bash -c` for loops. `pkill -f <pattern>` kills your own shell when the command line contains the pattern.

## 5. Layout (`/bulk/specula-adhoc`)

| path | what |
| --- | --- |
| `src/hadoop` (734dd8a67cd; has `origin/trunk` 2026-10-26: never fetch), `src/zookeeper` (eab16599), `src/hbase` (1790942bb2), `src/lucene-solr` (faca81bff1) | upstream trees. ZooKeeper, HBase and Solr were cloned with **only the base commit's history** (no remote, branches or tags) |
| `env.sh` (HDFS), `zookeeper-env.sh`, `hbase-env.sh`, `solr-env.sh`; `m2/`, `m2-zookeeper/`, `m2-hbase/`, `ivy-solr/` | per-system environment and dependency caches |
| `jdk/` (17.0.21, 21.0.13 for TLC and Specula, 11 for Solr), `apache-maven-3.9.15/`, `apache-ant-1.10.14/`, `tlc/` (pinned TLC jars, `SHA256SUMS`) | tools |
| `specula-runs/` | all runs; `/users/ZhenyuLi/Specula/runs` links here on every node |
| `run-case.sh <case> [args]` | one run. The system comes from the id prefix; blocks exist for hdfs, zk, hbase and solr. It makes `<system>/cases/<case>/` (tree copy, `deps/`, `env.sh`, `target.yaml`, `tlc-memory-limit`) and overlays a ported workload from `<system>/workloads/<case>/tree/`. It sets the model, the CLI pin and memory off. A resume (`--run-id`) reuses the stored paths |
| `queue.py`, `start-queue.sh <system> [K]` | one queue per node per system; claims in `<system>/claims/<case>/owner` (atomic `mkdir`); `<system>/cases/<case>/resume-args` grants one more resume with extra args |
| `summarize.py`, `wait_event.sh`, `wait_all.sh`, `watch.sh` | status and waiting |
| `tools/post_run.py report\|keep [--verify]`, `tools/record.py`, `tools/results.py` | after-run checks, bug-file keeping (the config and root module come from the counterexample log; CR findings have no TLC), inventory fields, RESULTS.md |
| `tools/stop_run.sh`, `tools/sync_credentials.sh`, `tools/start_logged_in_nodes.sh` | operations |
| `tools/find_sites.py`, `tools/{hdfs,zk,hbase,solr}_inventory.py`, `tools/insert_probes.py`, `tools/run_workloads*.sh` | preparation (B2/B3) |
| `<system>/inventory.tsv`, `targets/`, `workloads/`, `baseline/REACH.tsv`, `cases/`, `logs/`, `bugs/`, `NOTES.md`, `RESULTS.md`, `CLASSIFICATION*.md`, `VERIFY-*.md`, `VERIFIED-BUGS.md` | per system |
| `agent-memory-archive/{node0,node2}/` | the agents' cross-run notes, moved out of reach on 2026-11-02 (kept as evidence) |
| `v2 -> .` | old compatibility link; no run needs it anymore |
| `publish/baseline` | the clone of GitHub `JHSUYU/baseline` used to publish `specula/` |

## 6. Procedures

### 6.1 Running a system

- **Start or restart:** `ssh nodeN /bulk/specula-adhoc/start-queue.sh <system> <K>` on each node. Restarting a queue never touches running runs.
- **What a queue does:**
  - it claims new cases;
  - it resumes its own failed or crashed cases with `--run-id`, at most 3 times;
  - then it marks the case `needs operator`.
- **Holding a case:** create `<system>/claims/<case>/owner` with `hold`.
- **Releasing a case:** move its log aside, then `rm <system>/claims/<case>/owner; rmdir <system>/claims/<case>`.

### 6.2 After each finished case

1. `python3 tools/post_run.py report <system> <case>`: verdict, the leakage grep (expect 0), confirmation verdicts, novelty.
2. `python3 tools/post_run.py keep <system> <case> <id> [--verify]` for every REPRODUCED finding. Use `--verify` for MC findings, which reruns TLC; run them in the background, as big ones take 15+ min.
3. `python3 tools/record.py <system> <case> "<bugs>"`, then `python3 tools/results.py <system>`.
4. **Classify and verify against the source**, with the bar of §1.7. A finding counts only if it makes the **target** check fail (CR findings elsewhere don't).
   - Check trunk for changes, and search JIRA.
   - Group duplicates.
   - First pass: a verifier subagent per batch. The prompts used are visible in the VERIFY files' structure: read the code, the reproduction's realism, design intent, production severity, known/fixed.
   - Then read the decisive code yourself for every bug you keep.
   - Append to `<system>/VERIFIED-BUGS.md`.
5. Tell the owner the case's verdict, verified bugs, time, tokens and cost.

### 6.3 Stuck or failed runs

| symptom | fix |
| --- | --- |
| `needs operator` | read the log's last invocation |
| `Not logged in` | credentials (§4) |
| "resume checkpoint no longer matches current findings", or a missing `confirmed-bugs.md` | write `--fresh-context --skip-analysis --skip-specgen --skip-harness --skip-validate` into `cases/<case>/resume-args` (reruns Phase 4 only) |
| "this run has no unfinished agent conversation" (stopped between sessions, e.g. in a quota sleep) | `--fresh-context` plus the skip flags of the phases it finished (find its last `] PHASE N` line) |
| `--fresh-context` without skip flags | reruns every phase |

### 6.4 System report

When every case of a system has a final `adhoc-result.json`, or is marked not run with the reason, write `<system>/REPORT.md`:
- one row per case (from `RESULTS.md`);
- the verified bug table;
- the cases not run;
- totals.

Then show it to the owner.

## 7. Per-system notes

### 7.1 HDFS

- **Remaining TODO:**
  - finish 34, 39, 40, 45, 48, 49, 50, 52, then verify;
  - verify 33 (hot-swap add vs pool shutdown; the target is a Java `assert`, judge the `-da` effect);
  - write `hdfs/REPORT.md`.
- **The one ported workload** is `hdfs-adhoc-12` (`TestAdhocWorkload12#run`).
- **Run history** (pauses, the memory contamination, resumes): `hdfs/NOTES.md`.
- **Already published** in `JHSUYU/baseline` `specula/data/hdfs/`.

### 7.2 ZooKeeper (`zk-adhoc-*`)

- **Readiness:** all 16 workloads pass on upstream and reach their method (`zookeeper/baseline/REACH.tsv`).
- **Ports:** b1, b3, b4, b5 and b6 (`zookeeper/workloads/*.md`). b3 keeps the original's 3 s delay before the deletion is posted. b4 ships an untracked `.mvn/maven.config` for its test classpath.
- **zk-adhoc-b2:** its case tree carries one neutral commit `1312ae0187` (a test-scope `junit-platform-runner` in `zookeeper-recipes/pom.xml`; without it no recipes test runs). Its target's `base_commit` is that commit.
- **Build:** `test_command` is `mvn -o test` (not `surefire:test`). `m2-zookeeper` now has surefire's JUnit-platform provider.
- **Runs:** six runs that started while memory was on were restarted clean; their old logs are in `zookeeper/logs/superseded/`. See `zookeeper/NOTES.md`.

### 7.3 HBase (`hbase-adhoc-*`)

- **Readiness:** all 19 workloads pass on upstream and reach their method (`hbase/baseline/REACH.tsv`).
- **Ports:** 04, 07, 22, 34, and **13**, whose workload method existed only in the fork; its inventory and target were updated.
- **Case 34:** keeps `removeKey(keyId)`, which is the server's own reaction to a deleted key node. The port uses an upstream `hbase.rpc.server.impl` subclass to start the token manager without Kerberos.
- **Build:** `m2-hbase` now has the surefire JUnit 5 provider jars. Baseline runs used `-PrunAllTests`.
- **Runs:** 12 launches failed at start on 2026-11-02 (I edited `run-case.sh` in place, §8). They were released and relaunched; the old logs are in `hbase/logs/superseded/`.

### 7.4 Solr (`solr-adhoc-*`): prepared, NOT started

Prepared:
- the inventory, the targets (with the right Ant `test_command`), and the baseline (`solr/baseline/REACH.tsv`): 12 of 13 pass and reach their method;
- `run-case.sh` has the solr block (a per-case Ivy cache in `env.sh`);
- the solr-18406 defect (`solr-adhoc-22`) is present at faca81bff1.

**Owner decisions needed before starting:**
1. **`solr-adhoc-22` is PORT_BLOCKED.** The fork's workload needs a hold hook that upstream `IndexFetcher` lacks (the fork took it from the fix PR). Options:
   - a neutral base commit adding the one-line hook (a production change Specula would see);
   - hold the fetch on the leader through a test-only `ReplicationHandler` subclass in the configset (no production change);
   - drop the case.

   See `solr/workloads/solr-adhoc-22.md`.
2. **Every Solr test runs with `-Dtests.useSecurityManager=false`**, because the test policy only allows `~/.ivy2`. The alternative is a custom policy.
3. **Scope:** only `checks.tsv`'s classes, without GraphChecker's seven extra solrj classes. GraphChecker used a fixed seed; these runs use random seeds.
4. **The case tree's `solr/*/lib` symlinks point into the shared `ivy-solr`** until a build re-resolves them, so trees are not fully isolated from the shared cache.

Then:
- fix the skill's Ant notes (§3) between runs and rsync them;
- start `start-queue.sh solr 3` on each node.

## 8. Pitfalls already hit

- **Auto-memory leaked knowledge between runs.** Claude Code wrote notes to `~/.claude/projects/-users-ZhenyuLi-Specula/memory` (node2 from 10-28, node0 from 10-29), and later runs read them. It is now off via `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, and the notes are archived. Check new nodes or new CLIs for it.
- **Never edit a script the queues exec** (`run-case.sh`, `queue.py`) in place while queues run: bash reads it incrementally, and launches crash. Write a temp file and `mv` it over.
- **Do not stop a run in Phase 4.** Its resume can mismatch the interrupted checkpoint; fix with §6.3, which costs a Phase-4 rerun.
- **`--fresh-context` alone reruns Phase 1.**
- **A plain resume of a run stopped between sessions fails** ("no unfinished agent conversation").
- **Quota sleeps:** a run asleep on an account's quota keeps sleeping even after the account changes; restart it (§4, §6.3).
- **`findings.json`'s `config` may not be the config that produced the counterexample.** `post_run.py keep` reads the log header and tries `MC_hunt_<stem>.cfg`. One rerun (31/MC-2, a dropped finding) still picked a diag config and showed no violation.
- **Java `assert` targets** (e.g. HDFS 05 06 19 20 27 33, Solr 21) fire only with `-ea`. Judge production severity with `-da`.
- **The safety check blocks `rm -rf` with variables.** Use explicit paths, file `rm` plus `rmdir`.

## 9. TODO (in order)

1. **Keep processing finished cases** (§6.2) for HDFS, ZooKeeper and HBase, with source verification (§1.7), and report each to the owner.
2. **HDFS:** verify 33; finish the 8 running cases; write `hdfs/REPORT.md`.
3. **Solr:** get the owner's decisions (§7.4); fix the skill's Ant notes between runs; start the Solr queues.
4. **ZooKeeper and HBase:** when done, write their `REPORT.md` and `VERIFIED-BUGS.md`.
5. **Publish:** with the owner's OK, update `publish/baseline/specula/` (results, VERIFIED-BUGS, the TLC files of new bugs; see how `specula/data/hdfs/bugs` is built: `.tla` + cfg + counterexample log + `RERUN.md`, verified by rerunning from the copy), then commit and push.
6. **Later:** remove the `v2` link; Part-C cleanups.

## 10. The 84 checks

Source: GraphChecker `docs/checks/SELECTION.md` (owner 2026-10-21), the "with an integration test we run" column. Sites, guards and workloads are in each `<system>/inventory.tsv`.

- **HDFS (36):** `hdfs-adhoc-` 05 06 07 08 09 10 11 12 14 15 16 19 20 21 22 23 24 25 26 27 28 29 30 31 33 34 35 37 38 39 40 45 48 49 50 52.
- **ZooKeeper (16):** `zk-adhoc-` 01 02 03 04 06 07 10 11 12 13, and b1-b6, which are GraphChecker's quota-init, election-offer, container-reuse, retry-seq-quota, trunc-sync (ZOOKEEPER-5094) and observer-master (ZOOKEEPER-5088).
- **HBase (19):** `hbase-adhoc-` 04 07 08 10 11 12 13 14 15 19 20 21 22 24 28 31 34 35 37.
- **Solr (13):** `solr-adhoc-` 05 07 09 10 13 14 19 21 31 38 39 40, and 22 (= solr-18406).
