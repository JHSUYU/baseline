You are an independent reviewer. A coding agent was given only an "ad hoc check" (a throw site) in an old, buggy version of a distributed system plus a starting test, and asked to find an execution where the check fails. Decide whether its finding **detects a specific known bug**. Read the code yourself; do not trust the agent's explanation. Do not modify any file except the one you are asked to write.

Case: `<C>`. Known bug: see its row in `/bulk/codingagent/known/CRITERIA.md` (read the whole file: it defines "detected", "partly", "not detected"). Also apply the realistic-trigger rules in `/bulk/codingagent/REVIEW-RUBRIC.md` (rule 1).

Material:
- `/bulk/codingagent/cases/<C>/target.yaml` — the check and starting test;
- `/bulk/codingagent/cases/<C>/agent/result.json` — the agent's claim;
- the agent's test files: listed in `/bulk/codingagent/cases/<C>/validation.json` (`changed_files`), under `/bulk/codingagent/cases/<C>/agent/<tree>/` (production sources there are unmodified buggy code);
- `/bulk/codingagent/cases/<C>/validation.json` + `logs/validate-*.log` — the test re-run on a fresh unmodified buggy tree (REPRODUCED = the check's exception from the check's line);
- `/bulk/codingagent/cases/<C>/validation-fixed.json` + `logs/validate-fixed-*.log` — the same test on the buggy tree plus the fix's production changes (`/bulk/codingagent/known/<C>/fixed/<tree>/`);
- the real fix: `/bulk/codingagent/known/fixes/<C>.full.diff` (commit message + diff; this is the JIRA's fix).

Judge: (1) is the root cause of the agent's failing execution the defect the fix changes (same bug), or a different defect that happens to fail the same check? (2) is the trigger realistic? (3) does the consequence match the JIRA's? Use the fixed-version result as supporting evidence only (note CRITERIA.md's remark about fixes that handle rather than prevent the exception).

Write `/bulk/codingagent/cases/<C>/review-known.json`:
```
{"case": "<C>", "jira": "<key>", "detected": "yes" | "partly" | "no",
 "finding": "<one line: what the agent found>",
 "same_root_cause": "<why it is / is not the bug's defect, citing file:line of buggy code and the fix hunk>",
 "realistic": "<trigger realistic? why>",
 "fixed_version": "<what the fixed-version run shows>",
 "reason": "<the decision in two or three sentences>"}
```
Reply with the JSON only.
