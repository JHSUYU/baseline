# SOLR-13 exploratory full campaign on node0

This is a separate, bounded campaign for the unchanged Solr 8.11.4
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation` JUnit. It selects
the exact `RoutedAlias.doSynchronous@348:branch:1` check and only the typed
`AliasesManager.applyModificationAndExportToZk@2259:door:1` alias write.
The fault is `KeeperException.BadVersionException` at `SolrZkClient.setData`.
Automatic I/O doors are disabled. The budget is at most 80 fault trials,
3600 seconds, three faults per trial, and 480 seconds per trial.

The SHA-sealed node0 healthy trial passed JUnit 1/0/0. It observed five
exact nonthrowing target checks and 19 typed alias-write doors on named
actors; 15 doors preceded the last target check and were replayable by
node, epoch, exact site, and door ordinal. It found zero observed event-time
paths from an alias-write door to a target check. The typed doors are in
the Overseer context while the target checks are in request contexts.
This config uses the core's documented fresh healthy runtime admission:
exact loaded target class and site catalog, named target actors and region,
clean JUnit and target outcome, and an eligible observed typed I/O door.
`require_event_time_paths=false` keeps the unverified cross-process path
as an outcome to measure, not a prerequisite to launch. `reject_coarse_roots`
keeps closure construction strict, and `explore_outside_closure=true`
permits bounded exploration of the observed typed door outside the current
target closure. No graph edge is inferred from temporal order.

At source line 2259, `setData` is enclosed by a `BadVersionException` catch
at line 2262. That catch refreshes aliases and retries, so one modeled
exception does not necessarily abort the alias update or prevent a later
target check. The Overseer command may run separately from the request's
`ensureCollection` call. A causal link and target retention after injection
remain unproven. Every candidate requires exact applied-fault identity,
the exact target throw, and independent source/replay review before any
new bug claim.

`python3 run_campaign.py --mode full --preflight-only` checks package, source,
compiled classes, sealed healthy evidence, core release, and config without
starting a JVM. Dispatch must issue a matching case-local
`admission-full-node0.json` before the full runner can start. The runner then
requires node0, a fresh output, all node0/Solr locks, disk and RAM reserves,
and no competing user JVM. It runs one controller to natural terminal;
the raw output is `data/mallory/campaigns/SOLR-13-source-exploratory-full-node0-v1`.
