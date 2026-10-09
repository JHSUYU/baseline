# Mallory-style campaign records

This directory stores only runs made with the standalone Mallory baseline.
The fixed 102-check inventory, original source locations, exact runtime
mapping, and selected cluster tests are in `Mallory/cases/inventory.json`.
Historical CrashFuzz data remains under `data/crashfuzz` and does not count as
Mallory execution.

`calibration/<ID>` holds first healthy-only attempts. Corrected attempts use
`calibration_v2/<ID>` and retain the earlier evidence. `cases/<ID>` holds a
full fault campaign only after a valid healthy seed and exact target identity
are established. `checklist102.{json,md}` records each check's source and
test, calibration time and outcome, campaign time, effective injection count,
post-fault target reach, target exception observations, coverage, closure
feedback, and source-reviewed bug status. A terminal budget is separate from
the `quality_status` gate for effective target exercise. The gate requires a
named pre-target I/O point with an observed causal path to the target, or an
explicitly labeled same-occurrence local timeline under the optional rule.
It also requires an effective injected fault and post-fault target reach.

Terminal evidence archives and off-host raw copies are SHA-verified before
large MiniCluster scratch files are removed from expanded trial directories.
The relevant archive or off-host copy retains those files for rehydration;
trial traces and result receipts remain available for offline audit and table
generation.
