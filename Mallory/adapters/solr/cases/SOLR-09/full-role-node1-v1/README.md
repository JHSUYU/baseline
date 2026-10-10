# SOLR-09 node1 role-scoped full campaign

This package uses the unchanged Solr 8.11.4 cluster JUnit
`DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`. The selected
check is `DeleteReplicaCmd.deleteCore@277:branch:7`; the error is thrown at
line 278 when both waits fail. A `TimeoutException` injected at
`OverseerCollectionMessageHandler.waitForCoreNodeGone@434:door:1` is caught
locally and causes one wait to return false. The first failure may expose a
second wait, so a sequence of two exact role-scoped faults can reach the
selected check. The original source and compiled classes are pinned by the
healthy role package.

The node1 healthy run is preserved under
`data/mallory/calibration_solr09_healthy_role_v1_node1/SOLR-09`. It passed one
JUnit and observed the exact typed door before the exact check in the same
registered physical node, epoch, thread, context, and `deleteCore` occurrence.
The door had a unique `delete-replica-deletecore` role and an observed
`OverseerCollectionMessageHandler.processMessage` parent. The direct graph
event path was empty; the door remains in the target occurrence's dynamic
closure and has a local timeline witness. No line-278 throw was observed.

`run_campaign.py` uses a fresh output at
`data/mallory/full_solr09_runtime_role_v1_node1/SOLR-09`. It verifies the
previous evidence and all runtime pins before a JVM starts, then requires an
independent dispatch `go=true` receipt matching the config, runner, manifest,
prior healthy audit, lane locks, and output. It holds both the node1 Solr
lane lock and the source checkout lock for the whole campaign. The first
trial is a new healthy JUnit. That trial must independently pass the exact
physical role audit before any faults are selected. Any gap ends the campaign
as `healthy_role_gap`.

Only the exact @434 `TimeoutException` door may be mutated. Each fault plan
contains a `site`, `role`, and positive `role_ordinal`; the agent resolves the
current physical node at runtime. A fault counts as effective only after one
matched/applied pair proves the same named actor, epoch, occurrence, thread,
and role. An exact line-278 throw is a candidate only when it follows an
effective fault in that same command occurrence; source review and replay
remain necessary before calling it a new bug. The bounds are 80 fault trials,
3600 seconds, at most three faults per trial, and 480 seconds per trial.

The package is staged with `admission-request.json` set to `go=false`.
`PYTHONDONTWRITEBYTECODE=1 python3 run_campaign.py --preflight-only` checks
the package without starting Java. The dispatcher owns any full launch and
must provide a separate receipt with `mode=full`. The output can be resumed
from its checkpoint with the same immutable config after an interruption.
