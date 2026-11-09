# Coding-agent baseline

The paper's "LLM Coding Agent" baseline: a coding agent gets a system's source code and **one prompt per ad hoc
check**, and must write a test that makes the check fail in the real system. There is no pipeline, no spec and no
model checker. Two experiments:

- **New bugs:** all 84 ad hoc checks of Table 1 (HDFS 36, ZooKeeper 16, HBase 19, Solr 13), on each system's current
  code (the same base commits and starting tests as `../specula/`).
- **Known bugs:** the 14 old bugs of the table, each run at its **buggy version** (the parent of the JIRA's fix, as
  one commit with no history), with only the ad hoc check the bug makes fail as input.

## Setup (`SETUP.md`, `scripts/`)

- **Agent:** Claude Code CLI 2.1.319, `claude -p`, model `claude-opus-5-5[1m]` (Opus 5.5), `--effort high`, auto-memory
  off, one session per check. Budget: 8 h of agent time per check.
- **Prompt** (`scripts/make_prompt.py`; every case's prompt is its `prompt.md`): the paper's four parts.
  1. What ad hoc coordination is, and where the check is (file, line, method, exception, condition).
  2. The integration test to start from, with its build command.
  3. The task: find an execution (node crashes, failed requests, concurrent operations) in which the check fails and that is a bug, not a correct rejection.
  4. The deliverable: a test that reproduces it without changing system code, and a `result.json`.
- **No answers within reach:**
  - Each tree has a fresh one-commit git history (no older or newer commits, no remotes, no fix).
  - The agent runs in a container that sees only its own tree and dependency cache.
  - The network allows only the model API (`scripts/docker/proxy.py`); WebSearch and WebFetch are disabled.
  - Builds run offline.
- **Validation** (`scripts/validate.py`): the agent's test-side files only are copied into an unmodified tree. Its
  command must throw the check's exception from the check's line.
- **Review:** an independent reviewer agent judges each validated reproduction against the source:
  - for new bugs, real bug, by design, or unrealistic (`data/REVIEW-RUBRIC.md`);
  - for known bugs, whether the root cause is the JIRA's defect (`data/CRITERIA.md`, written before the runs). The test is also re-run on the buggy tree plus the fix.
- **Time and tokens:**
  - Time is the agent's active time; usage-limit waits are excluded.
  - Tokens are input plus output plus cache writes plus cache reads, including subagents.
  - Cost is the CLI's list-price estimate.

## Results

### New bugs: 84 ad hoc checks ([`new-bugs/`](new-bugs/README.md), [`data/REPORT.md`](data/REPORT.md))

| system | checks | claimed | validated | bug (reviewed) | by design | unrealistic | agent time | tokens | cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HDFS | 36 | 26 | 26 | 14 | 9 | 3 | 6h07m | 48.99M | $104 |
| Solr | 13 | 13 | 13 | 5 | 8 | 0 | 2h19m | 24.69M | $22 |
| HBase | 19 | 18 | 18 | 9 | 9 | 0 | 1h52m | 21.96M | $23 |
| ZooKeeper | 16 | 15 | 15 | 11 | 4 | 0 | 2h19m | 30.60M | $36 |
| **total** | 84 | 72 | 72 | 39 | 30 | 3 | 12h37m | 126.23M | $185 |

`new-bugs/` has one folder for each of the 39 bugs. Each holds:
- the reviewer's verified defect and the agent's own explanation;
- the reproduction test;
- validation, time and tokens.

The time and tokens of every check, including the 12 not claimed, are in `data/results.tsv`.

### Known bugs: 14 at their buggy versions ([`known-bugs/`](known-bugs/README.md))

**8 of 14 detected:** HDFS-11741, HDFS-14075, HDFS-14311, SOLR-6101, SOLR-6197, HBASE-15039, HBASE-20642 and ZOOKEEPER-710.
Totals: 1h28m of agent time, 21.1M tokens, $18.77.

All 14 claims reproduce a failure of the check. For the 6 not detected (HDFS-17383, HDFS-12931, HDFS-5766,
HDFS-10609, SOLR-9440, ZOOKEEPER-2886), the root cause is another defect and the failure persists once the fix is
applied. Each case's folder has the per-bug time and tokens, the explanation, and the result on the buggy and fixed versions.

## Layout

| path | what |
| --- | --- |
| `new-bugs/<case>/` | `BUG.md`, `prompt.md`, `repro/` (the agent's test files, paths relative to the system's tree) |
| `known-bugs/<JIRA>-<case>/` | the same, plus `fix/` (the JIRA's fix: `prod.diff` production only, `full.diff`) |
| `data/` | `REPORT.md` and `results.tsv` (84 checks), `known-REPORT.md` and `known-results.tsv`, review rubric and criteria, every review (`reviews/`), the known bugs' targets, fixes and tree setup (`known-SETUP.md`) |
| `scripts/` | the operator scripts (`bin/` in `SETUP.md`): prepare, driver, queue, validate, reports; `docker/` the container and proxy |
