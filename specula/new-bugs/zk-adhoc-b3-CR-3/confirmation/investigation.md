# CR-3 investigation (evidence only)

Tree: worktree at base_commit eab16599 + trace instrumentation (`SpeculaTrace`, gated by `SpeculaTrace.ENABLED`;
8 lines changed in place, line numbers unchanged, target method untouched). Paths relative to
`zookeeper-server/src/main/java/org/apache/zookeeper/server/`.

## Step 1: code audit

Binding of the manager
- `ContainerManager.java:45` `private final ZKDatabase zkDb;`, assigned once at `:90`. `getCandidates` reads only that field (`:187-223`).
- `ZooKeeperServerMain.java:170` `new ContainerManager(zkServer.getZKDatabase(), zkServer.firstProcessor)`; started `:171`, stopped only at shutdown (`:210-211`).
- `quorum/LeaderZooKeeperServer.java:80` has the same binding (`getZKDatabase()` at leader start). Not exercised here.

Restore
- `admin/Commands.java:645` RestoreCommand (POST `/commands/restore`), needs ALL on `/`; `:654` enabled by default ("true").
- `ZooKeeperServer.java:601-650` `restoreFromSnapshot`: builds a new ZKDatabase, `setZKDatabase(newZKDatabase)` (`:627`, plain field write at `:513-515`), re-creates the session tracker. It does not touch the container manager. No code path notifies it (grep: the only references are the two owners above).
- Old database object: not cleared, stays reachable through the manager's final field, so its tree is frozen.

Post path
- `ContainerManager.java:142-158` posts `deleteContainer(path)` straight to `requestProcessor` (= `firstProcessor`), i.e. past `submitRequest`/`restoreLatch` (`ZooKeeperServer.java:1208-1217`).
- `PrepRequestProcessor.java:167` resolves against `zks.getZKDatabase()`, the NEW tree. `:326-336` checks only: exists, childCount == 0, not NORMAL-ephemeral. No check of node type, cversion, or that the node is the one scanned. A PERSISTENT node passes (`EphemeralType.get(0)` is VOID, not NORMAL).
- Target: `FinalRequestProcessor.java:672-675` `n = zks.getZKDatabase().getNode(path); if (n == null) throw NoNodeException`; caught at `:604-605` and turned into an err code, so only the client-side exception and the frame (via JDI) are observable.

Candidate kinds in the frozen tree: used empty container (cversion>0) `:197`; never-used container once elapsed > maxNeverUsedIntervalMs (default 5 min) `:205`, elapsed keeps growing against wall time though the tree is frozen; expired TTL node `:213-221`. The frozen tree never receives the deletion, so each candidate is re-posted every check forever.

Trigger scenario: see the repro. Backup via snapshot, path P persistent in backup; P later becomes an empty/unused container; operator restores backup on the live server; next check deletes the restored P; client getData(P) fails NoNode at FRP:674. Re-created P is deleted again at the following check.

Safeguards recorded
- Admin auth: ALL on `/` (Commands.java:645). Operator-only trigger, not a client or a fault.
- Rate limit: one restore per 5 min (does not affect the mechanism).
- `zookeeper.admin.restore.enabled=false` disables the trigger.
- Non-empty restored node: NotEmptyException, `PrepRequestProcessor.java:331-333`. Ephemeral restored node: BadVersionException, `:334-336`.
- Restore right after a server restart with an empty old tree (the `RestoreQuorumTest` flow): the frozen tree has no candidates, so no stale post.
- Scope: the modeling brief kept restore out of the workload's fault model; never model-checked. Restore is a supported, default-enabled, documented command, not an invalid configuration.

## Step 2: developer evidence (in-tree only so far)
- `zookeeper-docs/.../zookeeperSnapshotAndRestore.md:52-63`: restore is for "recovering a cluster for quorum lost or building a brand-new cluster with seed data"; steps are block traffic, snapshot, move dataDir files, restore via admin command, unblock traffic. No restart after restore, and nothing about container nodes.
- `ContainerManager.java:35-41` class comment: "The result of the delete is unimportant. If the proposal fails or the container node is not empty there's no harm." Assumes a candidate really is a container. `:191-195` comment: cversion>0 "keep newly created containers from being deleted".
- Tests: `ZookeeperServerRestoreTest`, `SnapshotAndRestoreCommandTest` restore on a live server and check data right after, with no ContainerManager (neither uses ZooKeeperServerMain). No test covers manager + restore.
- Tracker/history search deferred until the reproduction verdict is settled (adhoc Shared Rule 2); queries recorded below.

## Step 2/3 continued: history and tracker (run only after the reproduction verdict settled; sets Novelty only)
Local history
- `git log -- ContainerManager.java`: latest f9fa0ccc ZOOKEEPER-4915 (default maxNeverUsedIntervalMs = 5 min, 2025-12-17). No commit about restore.
- `git log -i --grep=restore -- ZooKeeperServer.java admin/Commands.java`: d35bdfb9 ZOOKEEPER-4571 (2023-01-26) added the command. Field `zkDb` dates from 78b84f3ae (2015), i.e. it predates restore.
Jira (REST search, project=ZOOKEEPER)
- `text ~ "ContainerManager" AND text ~ "restore"`: 1 hit, ZOOKEEPER-2247, unrelated.
- `text ~ "restoreFromSnapshot"`: 4 hits (4858, 4639, 4571, 5097), none about the manager.
- `text ~ "ContainerManager" ORDER BY updated DESC`: 39 hits, first 25 titles read, none on this mechanism.
- `summary ~ "restore"`: 7 hits, none relevant.
- `text ~ "restore" AND text ~ "container"`: 82 hits, only the 20 most recently updated titles read, none relevant.
- `text ~ "stale" AND text ~ "ContainerManager"`: 1 hit, unrelated (ZOOKEEPER-2546).
- `text ~ "restore admin" AND updated >= 2025-06-01`: 2 hits, unrelated.
- ZOOKEEPER-4571 description: "takes a snapshot data as input stream and restore db without manual restarting"; "performing full restore and replace existing ZKDatabase". No mention of containers.
GitHub (`gh` not installed; REST search API, apache/zookeeper, is:pr)
- `ContainerManager restore` (1: #938 unrelated); `restoreFromSnapshot` (#1966, #1961); `ContainerManager in:title` (#1419, #64); `restore in:title` (10, none relevant); `container in:title updated:>2026-01-01` (#2430, log level only).
- Last 40 closed PRs by update date filtered on contain|restore|snapshot|zkdb|database|admin: #2463, #2476, unrelated.
- Upstream master raw files: `ContainerManager.java:45` still `private final ZKDatabase zkDb;`, `ZooKeeperServerMain.java:172` still passes `zkServer.getZKDatabase()`. Not fixed upstream.
Result: NEW. No report of this mechanism found. Pre-existing files in this finding's area (`error.txt`, `repro/CR-3.log`, `repro/CR-3.server-output.txt`) are from an earlier attempt and were not used as evidence.
Persistent-findings `lookup` not run: the task forbids reading other findings.
