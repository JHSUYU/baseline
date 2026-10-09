# Mallory-style campaign records

This directory stores only runs made with the new Mallory-style baseline. The 102 selected check identities and original source locations are in [`../crashfuzz/selection102.json`](../crashfuzz/selection102.json) and [`../crashfuzz/checklist102.json`](../crashfuzz/checklist102.json).

For each case, record the exact source check, cluster-based unit test, healthy target reach, applied fault sequences, target reach after injection, coverage and causal feedback, elapsed time, target exception, replay status, and evidence paths. A case has no Mallory result until the new campaign executes it. Do not copy CrashFuzz results into this directory as Mallory outcomes.
