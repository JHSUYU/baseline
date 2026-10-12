# Mallory-style campaign records

This directory stores only runs made with the standalone Mallory baseline.
Generated campaign output is ignored by default because it includes large
MiniCluster scratch trees and repeated build artifacts. Reviewed summaries,
configuration, and selected compressed traces are tracked explicitly; use
`git add -f` when promoting a new evidence file. Historical tracked artifacts
remain available for the original campaigns.
The fixed 102-check inventory, original source locations, exact runtime
mapping, and selected cluster tests are in `Mallory/cases/inventory.json`.
Historical CrashFuzz data remains under `data/crashfuzz` and does not count as
Mallory execution.

`calibration/<ID>` holds first healthy-only attempts. Corrected attempts use
`calibration_v2/<ID>` and retain the earlier evidence. `cases/<ID>` holds the
full fault campaign for a runnable cluster test. `checklist102.{json,md}`
records each check's source and test, calibration time and outcome, campaign
time, effective injection count, post-fault target reach, target exception
observations, coverage, closure feedback, and source-reviewed bug status.
A check is complete when its configured full campaign reaches the time or
trial budget, or exhausts its fault queue. `quality_status` describes the
observed fault-to-target evidence; it is not another completion gate. A
target exception, an effective injection, and an observed causal path are
reported as outcomes and can be absent from a completed campaign.

Terminal evidence archives and off-host raw copies are SHA-verified before
large MiniCluster scratch files are removed from expanded trial directories.
The relevant archive or off-host copy retains those files for rehydration;
trial traces and result receipts remain available for offline audit and table
generation.
