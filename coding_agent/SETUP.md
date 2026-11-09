# Coding-agent baseline on the 84 ad hoc checks

The paper's "LLM Coding Agent" baseline (§6.6): a coding agent gets the source code of the system and
**one prompt per ad hoc check**, and must produce a test that makes the check fail in the real system.

- **Agent:** Claude Code CLI 2.1.319 (`cli/claude-2.1.319`), `claude -p`, model `claude-opus-5-5[1m]`
  (Opus 5.5), `--effort high`, `--dangerously-skip-permissions`, auto-memory off. One session per check,
  resumed only after a usage-limit/login/API error, or nudged (at most twice) if it stops without writing
  its result file.
- **Budget:** 8 hours of agent time per check (the fuzzers' budget in the paper); usage-limit waits do not count.
- **Checks:** the 84 of Table 1 (HDFS 36, ZooKeeper 16, HBase 19, Solr 13): the same sites, workload tests,
  base commits and built trees as the Specula baseline (`/bulk/specula-adhoc`, its `targets/` and `src/`).
  Only the target's site and workload go into the prompt; Specula's scope hints, pipeline and results are not used.
  - `solr-adhoc-22`: the ported workload cannot pass on upstream, so it starts from the upstream test
    `TestPullReplica#testAddDocs` instead, which reaches the check's method 78 times and passes
    (`overrides/solr-adhoc-22.yaml`).

## The prompt (`bin/make_prompt.py`)

The four parts the paper gives: (1) the definition of ad hoc coordination and the location of the check
(file, line, method, exception, condition); (2) the integration test to start from, with its build
environment and command; (3) the task of finding an execution with node crashes, failed requests or
concurrent operations in which the check fails (and that is a bug, not a correct rejection); (4) a test that
reproduces the failure without modifying the system code, plus the result file `agent/result.json`.
Example: `cases/<case>/prompt.md`.

## No answers within reach

- **Git:** each case tree has its `.git` removed and re-initialised with one commit `base` (the branch name is kept,
  as Lucene's build cleans its build dirs when `.git/HEAD` changes). No older or newer commits, no remotes,
  no fix commits.
- **Container** (`docker/`, image `codingagent-runtime:1`): the agent sees only its case's `agent/` directory
  (tree, its own dependency cache, `env.sh`, its home, `/tmp`), the JDKs/Maven/Ant read-only under `/opt/tools`
  and the CLI. No `/bulk/specula-adhoc`, `/bulk/GraphChecker`, other cases, or the operator's `~/.claude`.
- **Network:** the container is on an internal Docker network; its only way out is `ca-proxy`
  (`docker/proxy.py`), which allows HTTPS CONNECT to `*.anthropic.com`, `*.claude.com`, `*.claude.ai` only
  (tested: GitHub and issues.apache.org are refused). Every connection is logged (`docker logs ca-proxy`).
- **Tools:** `WebSearch`, `WebFetch` (server-side web access), `RemoteTrigger`, `Cron*`, `ScheduleWakeup`
  and `Workflow` are disallowed.
- **Builds run offline** from each case's own copy of the dependency cache (Solr's Ivy cache was completed once
  online: `deps/ivy-solr`).

## Validation (`bin/validate.py`)

A claimed reproduction counts only if it holds on an unmodified system: a fresh copy of the case gets only the
agent's new or changed **test-side** files (changes to production sources or build files are recorded in
`validation.json` and dropped), the agent's command runs there in the same offline container (up to 3 tries),
and the output must show the target exception with a stack frame at the target `file:line`.

## Layout

| path | what |
| --- | --- |
| `bin/prepare.sh <case> [dir]` | case tree, deps, env.sh, prompt |
| `bin/driver.py <case>` | one agent run; `cases/<case>/run.json` (sessions, time, tokens, cost), `logs/session-NN.jsonl` |
| `bin/queue.py` | all 84, 2 per node on node0-node4; `queue.json`, `logs/queue.log` |
| `bin/validate.py <case>` | `cases/<case>/validation.json`, `logs/validate-N.log` |
| `bin/status.py [--tsv]` | per case: state, active time, waits, tokens, cost, claim, validation |
| `bin/cred_sync.py` | keeps one Claude login across node0's `~/.claude` and every case home |
| `cases/<case>/agent/` | what the agent saw and changed (its tree's `git status` shows its test files) |
