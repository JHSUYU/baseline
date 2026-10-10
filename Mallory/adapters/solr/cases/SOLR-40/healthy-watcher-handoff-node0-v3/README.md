# SOLR-40 v3 future healthy trial

The sealed v2 healthy run reached the exact target and observed one causal path
from the watcher `getData` door through the actual `aliases` field reference
write and read to the target check. Its JUnit log and `pilot-result.json` report
one passing test. The pinned Mallory core nevertheless marked the trial invalid
because `runner_kind` recognizes a Solr wrapper only when an argument's basename
is `run_pilot.py`; v2 used `run_pilot_v2.py`.

This package keeps the same exact-reference agent, site catalog, strict graph
gate, test workload, and pinned core. Its wrapper has the recognized basename
`run_pilot.py`, and its output path is fresh. `preflight_runtime.py` checks the
unchanged core against the sealed v2 raw JUnit files without rewriting their
result, and verifies that the v3 command would yield `passed`, 1/0/0/0.

Run the offline check with:

```sh
python3 Mallory/adapters/solr/cases/SOLR-40/healthy-watcher-handoff-node0-v3/run_healthy_v3.py --preflight-only
```

The node0 steward may launch exactly one healthy trial after dispatch issues a
matching case-local `admission-healthy-node0.json` receipt and the node0 resource
gate is clear:

```sh
python3 Mallory/adapters/solr/cases/SOLR-40/healthy-watcher-handoff-node0-v3/run_healthy_v3.py \
  --admission-receipt Mallory/adapters/solr/cases/SOLR-40/healthy-watcher-handoff-node0-v3/admission-healthy-node0.json
```

Admission to full fault testing requires a fresh v3 JUnit receipt with one
passing test, an exact named target, a physically bound watcher door, and an
observed event-time path containing the actual field-reference edge and a
balanced return edge. The case-local post-run audit records this evidence and
always leaves `full_campaign_go=false` for separate review. The v2 raw trial
remains sealed with its original invalid status.
