# Specula on ad hoc coordination checks (HDFS, ZooKeeper, HBase, Solr)

Specula is one of the Causym paper's baselines. Each Specula run checks **one** ad hoc coordination check: the same check site, workload test and starting classes that the paper's own tool used. The run answers one question: can an execution of the system, under faults in its fault model, reach the check's failing branch? It reports a verdict, every bug it reproduced, and its time, tokens and cost.

This file is the handoff to the next agent. It is current as of **2026-10-30 19:20 UTC**.
- §0: what to do first.
- §1: the owner's decisions and the standing rules.
- §2: status.
- §3-§6: code, machines, layout and procedures.
- §7: how to set up the remaining systems.
- §8: pitfalls already hit.
- §9: the TODO list.
- §10: the 84 checks.

## 0. Start here

1. Read §1 (rules), §2 (status) and §8 (pitfalls).
2. Check the live state:
   ```
   head -qn1 /bulk/specula-adhoc/hdfs/queue-status.*.txt      # one line per node's queue
   python3 /bulk/specula-adhoc/summarize.py hdfs --tsv         # every case: verdict, state, time, tokens, cost
   ```
3. Process every finished HDFS case that is not yet in `hdfs/RESULTS.md` (§6.2). At the time of writing that is 12, 24, 25, 28, 29, 31, 35, 37 and 38.
4. Keep processing cases as they finish, then write `hdfs/REPORT.md` (§6.4) and move to ZooKeeper (§7).

## 1. Decisions and standing rules

**Owner decisions:**

1. **One Specula version.** There is only the current Specula; an older Causym-hinted version and all its runs were deleted on 2026-10-29. Never compare with it, and never call anything "v1"/"v2".
2. **Basic ad hoc prompt only.** Specula gets the target, the oracle `TargetSafe == ~targetFired`, the fairness rules, per-phase scoping, the strict same-bug test and the result file. It gets **none of Causym's method**: no backward tracing, coordination graph, fault doors, `Phi_o`, "causally relevant" rule, or TLA+ patterns encoding them (§3).
3. **84 checks, one run per check**: HDFS 36, ZooKeeper 16, HBase 19, Solr 13 (§10).
4. **Do not measure Specula against GraphChecker.** Report each case on its own terms:
   - its verdict;
   - the bugs it reproduced and their class;
   - wall time, runtime, usage-limit waits, tokens and cost.

   No "agree with GraphChecker" columns, no GraphChecker verdicts in reports or in `inventory.tsv`. GraphChecker is used only as the source of each target's check site, workload and starting classes.
5. **Parallel, without conflicts.** Several checks run per node, 5 by default, on node0-node4 (§4, §6.1). Earlier "one at a time" and "one system at a time" orders are superseded. The systems still go in order: finish HDFS (with its report) before starting ZooKeeper, then HBase, then Solr.
6. **For every case, record** wall time, Specula runtime, usage-limit waits, tokens (total and cached), cost (USD), the per-phase split, the model and the CLI version (§6.2). Report them to the owner as each case finishes.
7. **Keep the files of every bug found** (TLC spec, counterexample and reproduction) in `<system>/bugs/<case>/<finding>/` with a `RERUN.md`. Never delete them.

**Standing rules:**

- **L1 inputs only.** For each case Specula gets the check (file, line, method, thrown type, guard), the workload test, the scope classes and the pinned source revision. Nothing GraphChecker computed goes into a target, tree or prompt.
- **Agents must never see GraphChecker.**
  - Trees are clean upstream clones.
  - Nothing an agent reads may contain `GraphChecker`, `graphchecker`, `Causynth`, `Causym`, `causym`, `/bulk/GraphChecker` or `/bulk/wt`.
  - After every run, `tools/post_run.py report` greps the agent logs for these. So far: 0 hits in every run.
  - Agents run with full file access, so this grep is the guard. Operator files (`inventory.tsv`, `workloads/*.md`) do mention GraphChecker; that is acceptable only because of the grep.
- **Neutral case ids.** The id reaches the agent, so it must not name a bug or mechanism. Study checks keep their ids (`zk-adhoc-07`). Bug points get neutral ids (`zk-adhoc-b1`…`b6`, `solr-adhoc-22`). The real names live only in `inventory.tsv`.
- **Pinned model** `claude-opus-5-5[1m]` (1M context) and Specula's default effort (`max`), on Claude Code CLI **2.1.312** with auto-update off. `run-case.sh` sets all three.
- **Ask the owner before:**
  - any `git commit` or `git push` (the Specula branch is uncommitted on purpose);
  - filing JIRAs or opening PRs upstream;
  - deleting run outputs or kept bug files;
  - changing concurrency rules.

## 2. Status (2026-10-30 19:20 UTC)

| system | checks | done | running | not started |
| --- | ---: | ---: | ---: | ---: |
| HDFS | 36 | 24 (15 processed, 9 not yet: 12 24 25 28 29 31 35 37 38) | 10: node0 39 40 45 48 49; node2 26 27 30 33 34 | 2: 50, 52 |
| ZooKeeper | 16 | 0 | 0 | 16 (not set up) |
| HBase | 19 | 0 | 0 | 19 (not set up) |
| Solr | 13 | 0 | 0 | 13 (not set up) |

**The 15 processed HDFS cases** (full table with per-phase numbers: `hdfs/RESULTS.md`; classification: `hdfs/CLASSIFICATION.md`):
- 7 REACHED_CONFIRMED: 07, 08, 09, 10, 11, 14, 20.
- 8 NOT_REACHED_BOUNDED: 05, 06, 15, 16, 19, 21, 22, 23.
- Totals: **$2,386.43, 4,533M tokens** (4,396M cached).
- A typical case costs $90-270 and takes 4-8 h of Specula runtime. Wall time is 6-20 h, because usage-limit waits add 1-8 h.

**Candidate new bugs: 17 distinct.**
- Each was reproduced on the unmodified base commit, and Specula's post-verdict search of JIRA, GitHub PRs, the web and git history found no report.
- The cited code is unchanged on `origin/trunk` as fetched 2026-10-26.
- **Novelty is not independently confirmed**: no own JIRA search, no own rerun of the Java reproductions (TODO 4, §9). Nothing is filed.

| # | case/finding | defect | note |
| ---: | --- | --- | --- |
| 1 | 10/MC-3 | `Journal.startLogSegment` rejects a header-only (0-txn) in-progress file that other paths treat as removable | |
| 2 | 08/MC-1 | epoch selection reads only a quorum; an orphan higher promise on a minority JN fences the newest writer for its whole term | could be judged by design |
| 3 | 08/MC-2 | `Journal.doRollback` keeps the cached `lastPromisedEpoch` | |
| 4 | 06/CR-3 | `EditsDoubleBuffer.writeRaw` via `QuorumOutputStream` never sets firstTxId/numTxns (a BackupNode with a `qjournal://` edits dir fails every segment) | niche configuration |
| 5 | 07/MC-1 | `FileJournalManager.purgeLogsOlderThan` marks a restarted JN's live in-progress segment `.stale`; an acknowledged edit is lost after failover | **critical**; 09/CR-5 is the same defect |
| 6 | 07/MC-4 | a queued `acceptRecovery` binds the next segment's committedTxId (fault-free failover with a slow JN) | |
| 7 | 09/MC-1 | `JournalSet.selectInputStreams` swallows a read failure of the required QJM; the new active NN starts below the committed txid and terminates | **critical** |
| 8 | 09/MC-3 | `Journal.discardSegments` (rolling-upgrade rollback) is not epoch-fenced | |
| 9 | 09/CR-3 | `doRollback` does not fence writers of the rolled-back history | |
| 10 | 11/MC-1 | in safe mode the NN stops pushing block keys but keeps rolling them (11/MC-5 is the standby/observer case) | |
| 11 | 11/MC-3 | DN registration exports keys before joining the heartbeat set; a concurrent roll misses it | |
| 12 | 11/MC-4 | after NN+DN restarts, snapshot-path / explicit-length `getFileChecksum` silently returns a wrong checksum | **wrong result** |
| 13 | 11/MC-6 | a restarted NN issues DEKs from new keys before DNs re-register | could be judged by design |
| 14 | 11/CR-4 | encrypted SASL before a block pool's keys are installed fails with NPE/IAE instead of ERROR_UNKNOWN_KEY | |
| 15 | 14/MC-1 (+MC-2..4) | with `dfs.encrypt.data.overwrite.downstream.derived.qop=true`, a DN re-signs a forwarded block token with its own key but keeps the keyId | non-default config |
| 16 | 20/MC-1 (+MC-2, CR-2) | NN heartbeats advertise the assigned (not yet durable) txid; after a crash DNs treat the real active as split brain and drop its commands | |
| 17 | 20/MC-3 | DN handshake installs a reported-ACTIVE NN without a txid check | mostly assertion-only symptom |

**Already-known bugs also reproduced:**
- HDFS-17563 (10/MC-1 target, 10/MC-2; 10/MC-5 is a variant);
- HDFS-13441 (11/MC-2);
- HDFS-16136 (11/MC-7);
- HDFS-15651/HDFS-13473 (11/CR-3).

**Bug files kept** in `hdfs/bugs/` (2.6 GB) for 06, 07, 08, 09, 10, 11, 14 and 20. Every TLC-backed bug's `RERUN.md` ends with a "Checked …: Invariant … is violated" line from a rerun on the pinned TLC.

## 3. Specula code

- **Repository:** `/users/ZhenyuLi/Specula`, branch `adhoc-coordination`, **uncommitted** (ask before committing). Base commit `39b4a01`.
- **The `--adhoc-target=PATH` mode** (env `SPECULA_ADHOC_TARGET`):
  - `phaselib._adhoc_prompt_section` appends a short "Ad Hoc Coordination Target" section to every phase prompt. It points at one section of `skills/adhoc-coordination/guide.md`.
  - Phase 1 uses Specula's native Code Analysis prompt.
  - Phase 4b must write `adhoc-result.json` (format: `skills/adhoc-coordination/references/adhoc-result-format.md`); a missing or malformed one fails the phase.
- **The skill** `skills/adhoc-coordination/`:
  - **What it holds:** `guide.md` with Shared Rules 1-5 and Phases 1-4b. Its references are `tla-patterns.md` (target, sanity, hunt configs only), `target-file-format.md`, `adhoc-result-format.md` and `java-harness.md` (Maven, an Ant/Ivy section for Solr, node roles for HDFS/HBase/ZooKeeper/Solr).
  - **Banned words:** a grep of the skill and the six rendered prompts for `backward`, `coordination graph`, `region`, `edge`, `door`, `Phi_o`, `causal`, and for any HDFS target's identifiers, finds nothing.
  - **The Ant/Ivy section was written without a Solr checkout.** Verify its commands at Solr setup.
- **Fixes made during the HDFS runs** (both with unit tests; the whole suite passes):
  1. `stop_gate.SCAN_TIMEOUT_S` 5 s → 60 s. Phase 4's acceptance gate walks the run dir. With 8 HDFS confirmation worktrees (about 36k directories) the walk took 5.4 s, and every Phase 4 then failed with "background-job PID scan was incomplete".
  2. `confirmlib._tuning_identity` treats an explicit effort `max` (claude-code) as the default. A fresh run passes no `--effort` while a resume forwards the stored `max`, so before this fix every resume after an interrupted Phase 4 broke the cache:
     - it invalidated the candidate and verdict caches;
     - it re-consolidated the findings differently;
     - it then stopped at "resume checkpoint no longer matches current findings".
  3. Earlier: `skill_refs.stable_skill_refs`, so cached confirmation verdicts survive a resume in a new process.
- **Tests:** `cd /users/ZhenyuLi/Specula && PATH=/bulk/specula-adhoc/jdk/jdk-21.0.13+9/bin:$PATH .venv/bin/pytest tests/unit -q` (1616 pass). The system `java` is 1.8 and one TLC test needs 21.
- **Skills are symlinks.** `Specula/.claude/skills/*` link into the repo's `skills/`, so **editing the skill changes runs in flight**. Change it only between runs, and record the change.
- **Code is copied per node.** Each node has its own copy of the repo at the same path. **After any code change, sync it to every node:**
  ```
  cd /users/ZhenyuLi && for n in node0 node1 node3 node4; do rsync -a --exclude=/runs --exclude=__pycache__ Specula/src Specula/tests Specula/skills $n:/users/ZhenyuLi/Specula/; done
  ```
  Never rsync `runs`: it is a symlink to `/bulk/specula-adhoc/specula-runs` on every node.

## 4. Machines and accounts

- **node0-node4:** 64 cores and 376 GB each.
- **Shared disk:** `/bulk` is node0's disk, NFS-mounted on all nodes, about 850 GB free. Everything shared lives there: trees, runs, logs, scripts.
- **Local per node:** `/users/ZhenyuLi` (about 50 GB free per node). It holds the Specula copy, the Claude CLI (`~/.local/bin/claude` → 2.1.312) and the Claude login (`~/.claude/.credentials.json`).
- **Accounts:**
  - node2 and node0 are logged in to **different** Claude accounts.
  - node1, node3 and node4 have the CLI but **are not logged in**. Only the owner can log in (`ssh nodeN`, `~/.local/bin/claude`, `/login`).
  - `tools/start_logged_in_nodes.sh hdfs 5` starts a queue on every node that has a working login and no queue yet.
- **Quotas:**
  - Each account's 5-hour quota is the real limit. With 5 runs per account it fills in about 3 h.
  - Specula then sleeps until the reset by itself, logging `Quota: 5h=…% … sleeping Ns`; `summarize.py` counts and sums these waits.
  - More logged-in nodes (accounts) means more throughput; more runs per account does not.
- **The agent shell is zsh:**
  - Unquoted variables are not word-split, so use `bash -c '…'` for loops over lists.
  - `pkill -f <pattern>` matches your own shell when the command line contains the pattern. Kill by PID, or use the scripts.

## 5. Layout (`/bulk/specula-adhoc`)

| path | what |
| --- | --- |
| `env.sh`, `jdk/` (17.0.21 runs Hadoop; 21.0.13 runs TLC and Specula), `apache-maven-3.9.15/`, `m2/`, `pybin/` | shared toolchain (HDFS) |
| `src/hadoop` | apache/hadoop at `734dd8a67cd`, built once. `origin/trunk` fetched 2026-10-26 (`f8422975702`). Never run `git fetch` here: case copies would then expose newer history to agents. Use `git -c gc.auto=0` for history reads |
| `specula-runs/` | all Specula runs; `/users/ZhenyuLi/Specula/runs` links here on every node |
| `tlc/` | pinned `tla2tools.jar`, `CommunityModules-deps.jar`, `SHA256SUMS`; used by every `RERUN.md` |
| `run-case.sh <case> [specula args]` | one run. The system comes from the id prefix (only `hdfs-*` is configured). It makes `<system>/cases/<case>/` with a private tree copy, a dependency cache (`deps/`), `env.sh` and `target.yaml`, and overlays a ported workload from `<system>/workloads/<case>/tree/`. It pins the model and CLI. A new case's TLC cap is in `cases/<case>/tlc-memory-limit` (24G). On a resume (`--run-id=`) it passes no `--artifact`/`--adhoc-target`, so the stored paths are used |
| `queue.py`, `start-queue.sh <system> [K]` | one queue per node (§6.1) |
| `summarize.py <system> [--tsv\|--markdown]` | per case: verdict, state, wall, runtime, waits (count and time), tokens, cost, model, CLI. Sources: the case log and the run's `summary.md` `Total` row |
| `wait_event.sh <system> [s]` | blocks until a case finishes or needs the operator (prints what changed) |
| `watch.sh <system>` | live phase/verdict stream |
| `tools/post_run.py report\|keep` | after-run checks and bug-file keeping (§6.2) |
| `tools/record.py`, `tools/results.py` | write a case's fields into `inventory.tsv`; regenerate `RESULTS.md` |
| `tools/stop_run.sh <case>` | stop one run (pipeline and all descendants) so it can resume |
| `tools/start_logged_in_nodes.sh <system> [K]` | start queues on logged-in nodes |
| `tools/find_sites.py`, `tools/hdfs_inventory.py` | inventory/targets (§7 B2; the HDFS script is the worked example) |
| `tools/insert_probes.py`, `tools/run_workloads.sh`, `tools/run_workloads_probe.sh` | workload baseline and reach probes (§7 B3; the run scripts hard-code the hadoop-hdfs module, so adapt them per system) |
| `v2 -> /bulk/specula-adhoc` | compatibility link: runs started before 2026-10-29 stored paths under `v2/`. All those runs are now done. Keep it while any of them might be resumed (e.g. re-classification); otherwise it may be removed |
| `hdfs/inventory.tsv` | one row per check: the site upstream (and in the fork), method, thrown type, guard, workload and its origin, scope, tree; after a run, the fields of §6.2 |
| `hdfs/targets/<case>.yaml` | target files |
| `hdfs/cases/<case>/` | private tree, deps, env.sh, target.yaml; `resume-args` (operator file, §6.3) |
| `hdfs/logs/<case>.log` | pipeline log (resumes append). Its last `Run:` line names the run |
| `hdfs/claims/<case>/owner` | which node owns a case |
| `hdfs/queue-status.<node>.txt`, `hdfs/queue.log` | queue state and events. `queue.log` is appended by several nodes over NFS and can have garbled lines |
| `hdfs/baseline/` | workload baseline (`summary.tsv`), reach probe (`REACH.tsv`, `probe/`) |
| `hdfs/workloads/hdfs-adhoc-12.md`, `…/hdfs-adhoc-12/tree/` | the one ported HDFS workload (`TestAdhocWorkload12#run`) and its porting record |
| `hdfs/RESULTS.md`, `hdfs/CLASSIFICATION.md`, `hdfs/NOTES.md`, `hdfs/bugs/` | results, bug classification, run incidents, kept bug files |

## 6. Procedures

### 6.1 Running a system

- **Start or restart this node's queue:** `/bulk/specula-adhoc/start-queue.sh <system> 5`. On another node: `ssh nodeN /bulk/specula-adhoc/start-queue.sh <system> 5`.
- **Each node runs one queue over the whole case list:**
  - **Claims.** A node claims a new case with an atomic `mkdir <system>/claims/<case>`, so no case starts twice.
  - **Own cases only.** It checks and resumes only the cases it owns, because a run's agent conversations live in that node's `~/.claude`.
  - **Capacity.** It keeps K of its cases running.
  - **Resumes.** A non-zero exit is resumed with `--run-id` up to 3 times; after that the case shows `needs operator`.
- **Restarting a queue never touches running runs**; they are in their own sessions.
- **To stop everything:**
  1. Kill each node's queue: `pgrep -f "^python3 queue.py <system> "`, then kill by PID.
  2. Stop each run with `tools/stop_run.sh <case>`.
  3. Avoid stopping a run in Phase 4 (§8).

### 6.2 After each run (do this for every finished case)

1. **Report:** `python3 tools/post_run.py report <system> <case>` prints:
   - `adhoc-result.json` (verdict, mechanism, finding, stack frame, every config's bounds);
   - the **leakage grep** (expect 0 hits);
   - every confirmation verdict;
   - the novelty lines.
2. **Classify every REPRODUCED finding** into one of:
   - real new bug;
   - already known (cite the issue);
   - variant of a known one;
   - same defect as another finding (count it once);
   - by design.

   How to decide:
   - Read `confirmation/<id>/issue.json` (cause, trigger, consequence, premises), the entry in `bug-severity.md` and the cited code.
   - Check that the code is unchanged on trunk: `git -c gc.auto=0 log 734dd8a67cd..origin/trunk -- <files>` in `src/hadoop`.
   - Do not trust Specula's "NEW" alone (TODO 4).
   - Findings that are FALSE POSITIVE, MASKED or ENV_LIMITED are not bugs.
   - Append the table to `<system>/CLASSIFICATION.md`.
3. **Keep the bug files:** `python3 tools/post_run.py keep <system> <case> <id> --verify` for every bug (target or not, known included).
   - It copies `spec/`, `traces/`, `adhoc-result.json`, `summary.md`, `confirmation/<id>/` (without the worktree), the reproduction files and `repro/`.
   - It writes `RERUN.md`, taking the config **and root module from the counterexample log's own header**. A counterexample may come from a variant config run from a subdirectory, for example `spec/output/hunt/gated/purge_guided_b.cfg` with `MCGuided1.tla`, not the `config` that `findings.json` names.
   - `--verify` reruns TLC with 4 workers and appends "Checked …: Invariant … is violated". Large configs can take 15+ min, so run them in the background.
   - Code-review (CR) findings have no TLC counterexample: run without `--verify`, and `RERUN.md` then points at the reproduction.
4. **Record:** `python3 tools/record.py <system> <case> "<bugs summary>"` (fills `inventory.tsv`), then `python3 tools/results.py <system>` (regenerates `RESULTS.md`).
   - `summary.md` may say `Total (incomplete)` or show a phase's runtime as `-`. That happens when a phase's session was interrupted (stopped, or killed by the pause of 2026-10-29); its tokens and cost are still counted.
   - Note such cases, and any pause included in the wall time, in `<system>/NOTES.md`.
5. **Tell the owner** the case's verdict, its bugs, wall, runtime, waits, tokens and cost, plus the running totals.

### 6.3 Stuck or failed runs

- **`needs operator`:** read the log's last invocation. A run is resumed only on its owning node.
- **Grant one more resume with arguments** by writing them, whitespace-separated, into `<system>/cases/<case>/resume-args`. The owning queue uses it once on its next pass, then renames it to `resume-args.used-<time>`.
- **A stuck Phase 4** (for example "resume checkpoint no longer matches current findings", or a missing `confirmed-bugs.md`) needs the confirmations rerun from scratch, without redoing Phases 1-3:
  ```
  echo "--fresh-context --skip-analysis --skip-specgen --skip-harness --skip-validate" > <system>/cases/<case>/resume-args
  ```
  `--fresh-context` **alone restarts every phase**: Phase 1 would overwrite the brief.

### 6.4 System report

When every case of the system has a final `adhoc-result.json` (or is marked not run, with the reason), write `<system>/REPORT.md`:
- one row per case: verdict, mechanism, wall, runtime, waits, tokens, cost (from `RESULTS.md`);
- the bug table: case, finding, one-line mechanism, target or not, class, and the run's fields;
- every NEW finding and its class;
- the cases not run, and why;
- totals for all runs and for the bug runs.

Show it to the owner. Do not delete worktrees or run outputs without the owner's OK: a run directory is about 3 GB, mostly confirmation worktrees, and `/bulk` has room.

## 7. Setting up ZooKeeper, HBase and Solr

Do these per system, in order. HDFS is the worked example: its scripts and files show every step.

### B1. Tree, toolchain, run-case block

| system | upstream (GitHub) | base commit | build | JDK |
| --- | --- | --- | --- | --- |
| ZooKeeper | apache/zookeeper | `eab16599` (master, 2026-03-23) | Maven | 11 or 17: verify (`maven.compiler.release` 8) |
| HBase | apache/hbase | `1790942bb2` (master, 2026-09-18) | Maven | 17 |
| Solr | apache/lucene-solr | `faca81bff1` (`branch_8_11`, 8.11.4) | Ant + Ivy (`ant ivy-bootstrap`) | 8 or 11: verify |

Steps:
1. Clone into `src/<system>` at the base commit. Do not leave newer refs fetched in that clone.
2. Install the JDK and build tool under this root, and write `<system>-env.sh` (dependency cache: a private Maven repo, or the Ivy cache for Solr).
3. Fill the system's block in `run-case.sh`. Its fields are `src`, `tree` (the copy's directory name the agent sees), `deps`, `envsh` and `repo`. For Solr, add the Ivy cache to the per-case `env.sh` rewrite.
4. Build once.
5. Prepare the bug points' trees:
   - The bug points are ZooKeeper's six and Solr point 22. Confirm each bug is present at the base commit (ZOOKEEPER-5094 and -5088 must be unfixed at `eab16599`).
   - If a fix is upstream, the case tree needs that revert. Find it in GraphChecker's `trees.tsv` and fork log.
   - **Ask the owner** how to apply it without the agent seeing "Revert ZOOKEEPER-NNNN". Recommended: one neutral commit, used as the target's `base_commit`, with the provenance only in `inventory.tsv`.
6. Copy nothing to the nodes. `/bulk` is shared; the Specula and CLI copies are already on every node.

### B2. Inventory and targets

- **Write `<system>/inventory.tsv` and `<system>/targets/<case>.yaml`.** The format is in `skills/adhoc-coordination/references/target-file-format.md`; `hdfs/targets/*.yaml` are examples.
- **Find each check's site** from the fork tree's marker `@CausynthExceptionTarget("<case id>")`, then the same statement **upstream**:
  - `tools/find_sites.py <fork tree> <upstream tree> <id>[=<marker>]` maps the fork line to upstream with a line diff.
  - A marker string can list several ids, e.g. `"hdfs-17960,hdfs-adhoc-52"`.
  - The forks turn `assert`/`Preconditions` into explicit throws, so the upstream "throw" may be an `assert` or a `Preconditions` call. Quote the guard as written upstream, and say on which side it fails.
- **Take scope and workloads from GraphChecker** (`git -C /bulk/GraphChecker show <branch>:<path>`; never check out):

  | system | branch | check table | workloads and scope |
  | --- | --- | --- | --- |
  | ZooKeeper | `origin/system/zookeeper` | `docs/checks/ZOOKEEPER.md` §E | `experiments/zookeeper/zk-adhoc/checks.tsv`; `experiments/zookeeper/zk-bugs/case.sh` |
  | HBase | `origin/system/hbase-cloudlab` | `docs/checks/HBASE.md` | `experiments/hbase/hbase-adhoc/checks.tsv`; `experiments/hbase/hbase-bugs/case.sh` |
  | Solr | `origin/system/solr-cloudlab` | `docs/checks/SOLR.md` | `experiments/solr/solr-adhoc/checks.tsv`; `experiments/solr/{solr-18406,solr-18413,solr-bugs}/case.sh` |

- **Fork trees** (read-only, never given to Specula): `/bulk/wt/zookeeper-checks`, `/bulk/wt/hbase-checks`, `/bulk/wt/lucene-solr-checks`.
- **Scope:** strip `server:`, `server=:`, `common:` and similar prefixes, and turn `/` into `.`.
- **Drop** GraphChecker's window, target occurrence, verdicts and every result column.

### B3. Workloads

- **Baseline and reach probe.** Run every case's workload on the unmodified upstream tree, in a scratch copy with its own dependency cache.
  - It must pass, and must reach the check's method: probe it by printing one line at method entry (`tools/insert_probes.py`).
  - Record the times. A workload that does not reach the check goes to the owner, and that case is not run.
  - HDFS: all 36 passed in 9-37 s and all reached their method.
- **Port the GraphChecker-written workloads** into the case tree as `<system>/workloads/<case>/tree/…`. `run-case.sh` overlays them as untracked files, and Specula copies untracked files into its confirmation worktrees.
- **Porting rules:**
  - Same operations, order, topology, configuration and waits.
  - Remove GraphChecker's recording and propagation calls.
  - Replace the adapter clusters with upstream test utilities (`MiniDFSCluster`, `ClientBase`/`QuorumBase`, `HBaseTestingUtil`, `MiniSolrCloudCluster`).
  - Drop replay-determinism helpers, especially any that write the guard's operands.
  - Neutral names, and comments that state no mechanism.
  - Write `<system>/workloads/<case>.md` with the original, the port, and what was removed and why.
  - `hdfs/workloads/hdfs-adhoc-12.md` is the example.

  | system | cases | GraphChecker workloads to port |
  | --- | --- | --- |
  | ZooKeeper | b1 quota-init, b3 container-reuse, b4 retry-seq-quota, b5 trunc-sync, b6 observer-master | `CausynthQuotaRetryTest`, `CausynthContainerReuseTest` (uses `CausynthZkCluster`), `CausynthZooKeeperRetryQuotaTest`, `CausynthTruncSyncTest`, `CausynthObserverMasterSyncTest` (with `CausynthQuorumHarness`) |
  | HBase | hbase-adhoc-04, 07, 22, 34 | `TestCausynthQuotaEnableAfterAdvance`, `TestCausynthRestoreSnapshot`, `TestCausynthTruncatedTableQuota`, `TestCausynthTokenKeys` |
  | Solr | solr-adhoc-22 | `TestCausynthPullReplicaReservation` (point 22 = GraphChecker's solr-18406) |

  Everything else is an upstream test; verify it exists at the base commit. `zk-adhoc-b2` (election-offer) uses `LeaderElectionSupportTest#testNodes3`. The HBase and Solr ports may rely on the forks' test-base changes, so check.
- **If no faithful port exists:** mark the case `PORT_BLOCKED` and ask the owner.

### B4. Run

- Run two cases first, and read their prompts, `modeling-brief.md` and `analysis-report.md`. Check for Causym vocabulary, history searches and problems with the target or workload.
  - Note: `"WebSearch"` appears in every session's tool list. Count real calls with `grep -c '"name":"WebSearch"'`.
- Then start the queues (§6.1) and process each finished case (§6.2).

## 8. Pitfalls already hit

- **Do not stop a run in Phase 4.**
  - Its resume may re-consolidate the findings, and the interrupted conversations then no longer match. Even with the effort fix, an interrupted conversation's checkpoint can still mismatch.
  - If it happens, use the `--fresh-context` plus skip-flags resume (§6.3). It reruns all confirmations, about $50-100.
- **`--fresh-context` without skip flags reruns Phase 1.**
- **Usage limits stop runs mid-phase.** Specula waits and continues by itself. When a batch gives up, the invocation exits 1 and the queue resumes it.
- **Skill edits reach running runs** (symlinks). Code edits reach new processes only, and only on nodes you rsync to.
- **zsh does not word-split, and `pkill -f` kills your own shell** (§4).
- **Heavy I/O on `/bulk`** (e.g. deleting tens of GB) slows every run's file scans.
- **`findings.json`'s `config` may not be the config that produced the counterexample**; `post_run.py keep` reads the log header instead.
- **Java `assert` targets** (e.g. 05, 06, 19, 20, 27, 33) fire only with `-ea`. Surefire enables it; production does not. Judge a finding's production effect from its `-da` behavior.

## 9. TODO (in order)

1. **Process the 9 finished, unprocessed HDFS cases** (12 24 25 28 29 31 35 37 38) with §6.2.
2. **Keep processing HDFS cases** as they finish: 26 27 30 33 34 39 40 45 48 49 are running, and 50 and 52 are unstarted.
3. **Write `hdfs/REPORT.md`** (§6.4) and show it to the owner.
4. **Independently verify the candidate new bugs** before anything is filed (the owner asked "do you confirm they are all new bugs?"; the answer was "not yet"). For each:
   - re-run its reproduction test on a clean tree;
   - search Apache JIRA and GitHub yourself;
   - check the latest trunk through the GitHub API, keeping `src/hadoop` untouched;
   - judge design intent and reachability under the default configuration.

   Start with the critical ones: 07/MC-1, 09/MC-1, 11/MC-4. The owner had not yet said whether to start this.
5. **ZooKeeper:** B1-B4 (§7), then §6, then its report.
6. **HBase:** the same.
7. **Solr:** the same, verifying the skill's Ant/Ivy notes first.
8. **Logins:** if the owner logs in node1, node3 or node4, start their queues (`tools/start_logged_in_nodes.sh <system> 5`).
9. **Later:** `adhoc_result_issue` lives in `phaselib.py` but is used by the pipeline; move it if it reads better.

## 10. The 84 checks

Source: GraphChecker `docs/checks/SELECTION.md` "The ad hoc check selection: the final table" (owner 2026-10-21), the "with an integration test we run" column.

- **HDFS (36):** `hdfs-adhoc-` 05 06 07 08 09 10 11 12 14 15 16 19 20 21 22 23 24 25 26 27 28 29 30 31 33 34 35 37 38 39 40 45 48 49 50 52.
- **ZooKeeper (16):**
  - Study checks: `zk-adhoc-` 01 02 03 04 06 07 10 11 12 13.
  - Six bug points: zk-bugs-quota-init, -election-offer, -container-reuse, -retry-seq-quota, -trunc-sync, -observer-master, with Specula ids `zk-adhoc-b1`…`b6` in that order.
  - The three NoNode bugs share one throw, and the two quorum bugs share `ZKDatabase:341`. Each is still its own check.
- **HBase (19):** `hbase-adhoc-` 04 07 08 10 11 12 13 14 15 19 20 21 22 24 28 31 34 35 37.
- **Solr (13):** `solr-adhoc-` 05 07 09 10 13 14 19 21 31 38 39 40, plus point 22 as `solr-adhoc-22` (GraphChecker's solr-18406; its workload comes from `experiments/solr/solr-18406/case.sh`).
- **Not run:** GraphChecker's other 20 bug executions. Each shares a point with a study case or sits outside the selection:
  - HDFS: hdfs-17897, hdfs-17899-bug1/2/3, hdfs-17967-pathA/B/C, hdfs-11741, hdfs-17960, hdfs-bugs-slowdisk-zero;
  - HBase: hbase-bugs-master-active-time, -backup-lock-reply-lost, -ns-rsgroup-removal;
  - Solr: solr-18413 and the six `solr-bugs-*`.
