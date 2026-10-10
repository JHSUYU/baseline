# Mallory baseline for ad hoc coordination checks

This is a new baseline implementation for the original 102 selected checks.
It runs each check's existing cluster-based unit test in a fresh trial JVM,
records a target-anchored occurrence graph and code coverage, and selects
subsequent fault injections from runtime feedback. It does not import or
execute the upstream `mallory/` or `GraphChecker/` repositories.

## Components

- `cases/`: the 102-check inventory, test provenance, generated case configs,
  and explicit gaps where a usable cluster test or target bytecode mapping is
  not available.
- `static/`: independent static analysis that proposes a target influence
  frontier. Its Jimple site IDs are advisory until mapped to bytecode probes.
- `instrumentation/`: shaded Java agent for target, branch, coverage, fault,
  state and region events; system adapters must provide logical node and
  cross-thread/process handoff identity.
- `adapters/`: source hooks for HDFS, HBase, Solr and ZooKeeper MiniClusters.
- `core/`: resumable per-check fault sequence campaign and evidence-qualified
  causal feedback.
- `dispatch/`: three-host case scheduling with isolated scratch and receipts.
- `report/`: generate the final 102-row table from actual Mallory results.

## Fault sequence selection

The upstream Mallory mediator includes a Q-learning scheduler. This baseline
uses a deterministic priority queue instead: it favors validated recovery
sites, fault doors in the observed target closure, then static candidates,
and scores coverage and causal-edge novelty, untried sites, sequence depth,
and waiting time. It expands a fault sequence only when the injected faults
matched their runtime identities and the target check remained reachable.
Each check has a bounded campaign, so its changing I/O identities provide few
repeat observations of the same state and action. The current results therefore
describe a target-guided heuristic adaptation, not an evaluation of Mallory's
Q-learning policy. The selector is implemented in `core/scheduler.py`.

The original CrashFuzz records are under `data/crashfuzz/`. Mallory results
belong under `data/mallory/cases/<ID>/` and the generated table under
`data/mallory/checklist102.{json,md}`. An absent result stays pending; an
exception after an effective injection is a candidate for replay and source
review, not automatically a new bug.

## Evidence boundary

The original Mallory paper builds node-local timelines and links them through
matched network packets; it does not specify application shared-field
read-from edges ([paper, Section 3.1](https://arxiv.org/pdf/2305.02601.pdf)).
Our adaptation uses explicit region ancestry, matched RPC messages, and
correlated task handoffs for fuzz guidance in the unit-test clusters. RPC and
task edges require an explicit, unique correlation. Optional sampled state
events are an extension, disabled by default; if enabled, they produce only
candidate edges rather than a proven shared-field read-from relation.
Unknown node identity, unpaired messages, and missing target reach are recorded
as gaps. A campaign is completed when it reaches its configured terminal
budget or exhausts its fault queue; these gaps describe its result, not a
second completion threshold. A positive causal-path annotation requires a
named I/O fault point with an observed path to the target, or a separately
labeled local temporal relation when the optional rule is enabled. Candidate
state edges cannot prove either relation.

When a fault-free trace has no event at the exact configured target site, the
core records its oracle result, global coverage and observed doors without
building an irrelevant occurrence graph. The feedback graph is explicitly
marked `analysis_skipped: healthy_target_absent`; zero edge counters in that
record are not a claim that the trace contains no communication. The raw trace
is retained, and offline audit applies the same rule to this invalid seed.

The earliest 23 campaigns received a path annotation under an earlier rule
requiring a root-free healthy path and a target check after an effective fault.
Their archived agent
traces lack numeric JVM `thread_id`, so the later `fa5f3bde` event-time gate
cannot retroactively prove a same-thread path. SHA-bound reviews in
`data/mallory/quality_reviews/event_time_v1/` and
`data/mallory/quality_reviews/faulted_path_v1/` separate a healthy path from
an observed fault-to-target continuation. The checklist labels cases without
the latter `faulted_path_unverified`; this is an evidence gap, not proof that
the fault had no effect or that no bug exists. New terminal cases are counted
as completed immediately; SHA-bound reviews can later refine their evidence
annotations.

For checks whose I/O door and target lie in one region occurrence, an optional
local-timeline rule accepts a named door observed before the exact check in
that same occurrence. The audit labels this evidence separately from a path
across graph regions; temporal order alone does not prove data flow.

The checklist uses `source_review_no_suitable_test` when a hash-checked
source survey finds no existing cluster test for an exact check but no valid
healthy trace is available. This is a workload selection decision, separate
from `no_suitable_cluster_test`, which has additional runtime evidence; neither
counts as a completed fuzz campaign.

Run `python3 -m unittest discover -s Mallory -p 'test_*.py'` and see each
component README for its other checks. Run `python3 -m Mallory.report.build`
after any case reaches a terminal result to refresh the table.
