# SOLR-39 bounded graph-guided revisit

This diagnostic uses the unchanged Solr 8.11.4 four-server
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`. It selects the
exact `lookupShardLeadersOfCollections@246` check and the watcher
`getData("/aliases.json")` exception door from the existing case-local site
file. The first run must pass without faults and reach the target. The queue
then uses the dynamic target closure, code coverage, and observed doors.
Bounded actor-miss and normal-target-branch replays address nondeterministic
request routing, as in the SOLR-40 diagnostic. Only one fault is injected per
trial; the cap is 30 fault trials or 1200 seconds.

This is a new output directory and does not import any v5 trials. `run.py`
generates an immutable config from the pinned v3 healthy package, validates
runtime artifacts, holds the node0 Solr and source locks, and resumes from the
case checkpoint if interrupted. It pins the active controller's SHA-256; it
does not claim to use the older core release recorded in v3.

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/graph-auto-v1/run.py --preflight-only
python3 Mallory/adapters/solr/cases/SOLR-39/graph-auto-v1/run.py
```

Output: `data/mallory/solr39_graph_auto_v1_node0/SOLR-39/`. An exact target
throw after an effective fault is a candidate and requires source review.

## Completed result

The checkpoint ended with `budget_exhausted` after 1269.127 seconds; the last
trial was allowed to finish after the 1200-second selection ceiling. The
original cluster JUnit passed the fault-free run and reached the selected
target. All 25 fault trials applied their planned exception; 20 still reached
the target after injection. None produced the selected target exception.
There were 13 normal observed trials, five target-lost trials, and eight runs
whose workload failed elsewhere (including the healthy row in the status
count). `result.json`, the trial receipts, and the resumable checkpoint remain
under the output directory. This bounded rerun found no SOLR-39 bug witness.
