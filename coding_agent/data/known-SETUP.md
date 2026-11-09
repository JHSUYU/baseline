# Coding-agent baseline on 14 known bugs, at their buggy versions

The same coding-agent baseline as the 84 checks (`../README.md`: agent, model, effort, container, network,
disallowed tools, validation), run on the 14 known bugs of the paper's table, each at its **buggy version**.
The agent gets only the ad hoc check the bug makes fail (file, line, method, exception, condition) and a
starting integration test: the same four-part prompt (`../bin/make_prompt.py`). It is never told there is a
bug, which bug, or its JIRA.

## Trees: the buggy version, no way to the answer

- **Source** (`bin/prepare_known.py golden`): the Specula known-bug case tree of the same bug, which is the
  fix's parent as one commit (`git archive`). Its tree hash equals the upstream parent's for 12 bugs; zk-adhoc-k2
  lacks two generated `zkperl/build` files; solr-adhoc-k1 lacks 7 comment lines naming SOLR-9440
  (`../known-fixes.json` has each fix and parent).
- Every change Specula's run made to the tree is reverted and its untracked files are deleted (kept: the ported
  starting test of hdfs-adhoc-k2, hdfs-adhoc-k7, zk-adhoc-k1; `known/<case>/golden.json`). The `.git` is
  replaced by a fresh one-commit history `base`. Solr's test-timing cache lines naming Specula's tests are removed.
- **Built clean** offline in the container (`bin/build_known.sh <case> golden`): Maven trees with every
  `target/` removed and `mvn -o install -pl <module> -am` (which also replaces the system's own SNAPSHOT jars in
  the dependency cache), Ant trees with `ant clean` and a test compile. JDK 8 (JDK 7 and Ant 1.9.16 for
  solr-adhoc-k2), protoc 2.5.0 for HDFS, as these old versions need.
- Each agent gets a copy of the built golden tree and its dependency cache (`prepare_known.py copy`), checked
  with `bin/build_known.sh <case> sanity` (the prompt's starting-test command passes in such a copy).
- Leak check of every golden tree and cache: no `Specula`, `GraphChecker`, `Causym`, JIRA key or fix hash
  (only genuine text such as "Speculation" in a Lucene test corpus).

## Judging detection

`CRITERIA.md` (written before the runs): what a finding must show to count as each bug. A claimed
reproduction is first validated like the 84 (`../bin/validate.py`); then its test is re-run on the fixed version
(`known/<case>/fixed/`: the golden tree plus the fix's production changes, `known/fixes/<case>.prod.diff`), and an
independent reviewer compares the finding's root cause with the JIRA's fix (`cases/<case>/review-known.json`).

## Files

| path | what |
| --- | --- |
| `targets/<case>.yaml` | the check and starting test given to the prompt |
| `<case>/golden/` | the built buggy tree, dependency cache and env.sh every copy comes from |
| `<case>/fixed/` | the same plus the fix (operator only, never mounted into an agent container) |
| `fixes/` | each fix commit, full and production-only |
| `queue.json`, `../logs/queue-known.log` | the run queue (`KNOWN=1 bin/queue.py`) |
| `REPORT.md`, `results.tsv` | results (`bin/report_known.py`) |
| `../cases/<case>/` | the agent's run, as for the 84 |
