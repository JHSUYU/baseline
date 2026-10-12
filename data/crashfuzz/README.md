# Campaign records

[`static102-rerun.tsv`](static102-rerun.tsv) is the live checklist for the
current Soot-selected CrashFuzz rerun. It has one row for each original check,
with the exact source site, chosen cluster JUnit, elapsed time, fault counts,
strict runtime matches, post-fault target reaches, and candidate status.
The `fault_trials` and `active_trial` fields also show progress from a live
checkpoint. Final time, injection, and candidate counts are written when the
case finishes. A pending or running row is not a tested result.
For completed cases whose raw trials were moved to preserve node0 disk space,
`archive_host` and `archive_path` locate the checksum-verified copy. The local
`campaign_result` remains available with the case summary.

The files below preserve the earlier case-specific campaign; their completion
counts do not describe the current Soot-selected rerun.

[`checklist102.md`](checklist102.md) is the final human-readable table. [`checklist102.json`](checklist102.json) contains the same 104 rows: the original 102 selected checks and two known-issue HDFS controls. Each row preserves the system, exact source check location and function, original cluster test, measured time where recorded, fault and coverage counts, status, and bug mark.

`selection102.json` and `check_locations.json` preserve the selected site identities. `cases/<ID>/result.json` contains each terminal case record. `evidence/` and `artifacts/` hold recorded run output that was moved out of the implementation tree; relative links from `../../crashfuzz/` retain the campaign's original local paths. `bug-confirmations.txt` holds the source-reviewed candidate descriptions. Source reviews are in `reviews/`.

The table records 87 `quality_complete` checks, six `no_cluster_test`, five `no_usable_cluster_test`, and six `source_excluded`. A quality-complete mark reports the recorded fault-injection budget and target reach; it does not assert that every target exception is a new bug. Measured time is present for 98 checks, and six are explicitly unrecorded.
