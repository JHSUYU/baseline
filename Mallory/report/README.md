# Mallory result table

Run `python3 -m Mallory.report.build` from the baseline repository root to
generate `data/mallory/checklist102.json` and `checklist102.md`. The generator
joins the fixed 102-check inventory in `Mallory/cases/inventory.json` with
only the Mallory `data/mallory/cases/<ID>/result.json` files that exist. The
two known-issue controls are shown separately.

The table also shows a separate calibration status and elapsed time from
`data/mallory/calibration/<ID>/result.json`. Calibration never counts as a
completed campaign or a fault trial. `calibration_counts` tracks these
preliminary outcomes while full campaigns are pending.
If a corrected calibration is stored under `calibration_v2` (or a later
numbered cohort), the table shows the newest status and keeps all attempts
in `calibration_history`. Earlier receipts and evidence remain untouched.

The generated checklist schema is version 2. `completed_checks` counts only
terminal campaigns; `not_completed_checks` is the rest of the fixed 102.
`skipped_no_suitable_cluster_test` counts rows with a verified source review
showing no suitable existing cluster JUnit. Each row has the same Boolean
classification. `handled_checks` is completed campaigns plus these source
proven skips; `remaining_unhandled_checks` excludes both. A staged but unrun
fault-discovery bootstrap stays pending, and source reviews never increase
`completed_checks`.
Fault-to-target evidence and source reviews are outcome fields, never a
second completion count.

The table shows the inventory test, latest calibration test, and actual
campaign test separately, since a source-backed alternate calibration may
use a different JUnit selector before the inventory is versioned.

An absent result stays `pending_seed`, `target_mapping_gap`, `runner_pending`,
or `no_mapped_cluster_test`, according to the inventory gates. A failed
healthy seed is `seed_invalid`. `completed_campaign` requires a terminal
campaign result (`budget_exhausted` or `queue_exhausted`); it does not mean a
bug was found or that every planned fault matched. Duration and trial counts
are copied from the campaign result. The `new_bug` mark requires a separate
source review confirmation and is never inferred from an exception count.
After a terminal campaign, `data/mallory/triage/<ID>/review.json` can record
`source_review_status` and `new_bug` without editing the immutable result.
The receipt must contain schema version 1, case ID, SHA-256 hashes of the
campaign `result.json` and `triage.json`, the triage classification, a review
status (`expected_guard`, `inconclusive`, or `confirmed_new_bug`), and a Boolean
`new_bug`. The report verifies these bindings and every file hash listed in
the triage manifest before displaying the review. A mismatched receipt is
shown as `invalid_review` and cannot mark a new bug.

For a check with no completed campaign, a source-reviewed workload gap can be
recorded in `data/mallory/source_gaps/<ID>/receipt.json`. The report displays
`no_suitable_cluster_test` only when the receipt matches the source review,
the newest healthy calibration result, and its offline audit, and that audit
shows zero observed I/O paths to the target. A newer calibration or completed
campaign supersedes the gap; a stale receipt never counts as a tested check.
HBASE-32 has a pinned target-absent bootstrap under an unchanged cluster JUnit,
so its older no-suitable-healthy-test review is superseded by a pending
bootstrap. HBASE-34 has a source-pinned LocalHBaseCluster JUnit whose previous
calibration stopped in MiniKdc setup; it remains pending environment repair.

Campaign completion has one definition: a terminal result. The report keeps
`quality_status` as a fault-to-target evidence annotation; it does not affect
`completed_checks` or a row's `completed_campaign` status. `target_exercised`
requires a valid
healthy seed, valid runtime attestation, at least one fully effective fault
trial, a target check reached after that fault, and a verified offline causal
audit. Run `python3 -m Mallory.core.audit --campaign data/mallory/cases/<ID> --out data/mallory/cases/<ID>/offline-causal-audit.json` after collecting a terminal
campaign. The audit recomputes the graph and oracle from SHA-verified raw
traces, checks named exact fault identities and feedback consistency, and is
bound to the unchanged campaign result hash. The healthy run must also contain
an entirely observed causal path from at least one named, pre-target I/O fault
point to the target. A target-only graph or a path through candidate state
edges does not satisfy this gate.
For a local-timeline-only campaign, the report separately shows
`same_actor_target_trials`. At least one such trial must have an effective
fault at an admitted healthy local door site and a later exact target check
in the same named node, epoch, and occurrence. `strict_target_trials` remains
the generic post-fault reach count and can include a different actor. This
stronger audit applies to future re-audits; frozen 5820 results and releases
are unchanged, though a new audit may change a local-only case's evidence mark.
A missing or failed audit is
shown as `causal_audit_unproven` or `causal_audit_invalid`. A terminal campaign with
no effective fault or with only target-losing faults retains its completed
status and receives the corresponding evidence annotation. `evidence_counts`
totals these annotations for the original 102 checks; calibration results
never enter this table.

A later causal precision review can supersede an earlier verified audit
without changing its result or runtime. Reviews live in
`data/mallory/quality_reviews/causal_precision_v2/`. The report reads only
the cases listed in `index.json`, verifies the individual sidecar hash and
its bindings to the exact campaign result and offline audit hashes, and
checks the terminal status, duration, and strict target count. A valid
`causal_precision_unverified` review changes only the evidence annotation;
the completed campaign, time, fault counts, and source review stay intact.
A damaged or stale listed review is shown as
`causal_precision_review_invalid` and cannot restore an unsupported path
claim. These reviews distinguish exact post-fault target reach from an
observed root-free occurrence path from the admitted healthy door to the
target. That historical criterion admitted 23 rows. Their archived traces
lack numeric JVM `thread_id`, so the newer `fa5f3bde` event-time gate cannot
retroactively prove exact event order on the path. SHA-bound
`data/mallory/quality_reviews/event_time_v1/` sidecars document the timing
gap; `data/mallory/quality_reviews/faulted_path_v1/` then checks whether each
applied fault has an observed continuation to the later target. Cases without
that evidence are labeled `faulted_path_unverified`, retaining their completed
status, original trial counts, and time. A new terminal case has a
`causal_precision_pending` evidence annotation until a SHA-bound precision
review is available; it is already counted as completed.

An older completed campaign can be marked `target_exercised_posthoc` only
when a separate `posthoc-attestation.json` binds to the unchanged result
hash, exact target sites, all trial catalogs, compiled target class hash,
and fully effective fault count. The raw campaign attestation stays
unchanged; the table shows the independent audit separately.

The table retains each check's system, exact source file and line, function,
site ID, target exception, and cluster test. Original CrashFuzz measurements
live under `data/crashfuzz` and do not populate Mallory results.
