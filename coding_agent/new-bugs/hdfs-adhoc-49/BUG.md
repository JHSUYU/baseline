# hdfs-adhoc-49: A delayed original of an idempotent disallowSnapshot runs after the client's successful retry and a later allowSnapshot, silently making '/' non-snapshottable (quota 0), so createSnapshot('/') keeps failing.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/snapshot/DirectorySnapshottableFeature.java:189`, `DirectorySnapshottableFeature.addSnapshot(INodeDirectory, SnapshotManager, String, LeaseManager, long)`, throws `org.apache.hadoop.hdfs.protocol.SnapshotException` when `n + 1 > snapshotQuota   (n = getNumSnapshots())`
- Starting test: `org.apache.hadoop.hdfs.server.namenode.snapshot.TestNestedSnapshots#testNestedSnapshots`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** A client with a valid ipc.client.rpc-timeout.ms (3 s) calls disallowSnapshot('/'). The first handler stalls in a pre-lock authorization step (an external AccessControlEnforcer that is slow on a latch but delegates unchanged). The client times out, fails over, and its retry succeeds. The admin then runs allowSnapshot('/'). Only after that does the stale first handler run.

**Why (root cause in the source):** disallowSnapshot is @Idempotent (ClientProtocol.java:1360) and has no retry-cache or ordering protection. The superuser check runs before the write lock (FSNamesystem.java:7241-7242), so an original call delayed past the client timeout can run after the client's acknowledged retry and after a later allowSnapshot. On the root it then runs SnapshotManager.resetSnapshottable, which sets the root's snapshot quota to 0 and removes '/' from snapshottables (SnapshotManager.java:301-306). This silently undoes the admin's last acknowledged operation, and the change is written to the edit log, so it survives restart and reaches the standby. Every later createSnapshot('/') is then rejected by the quota check (DirectorySnapshottableFeature.java:189) until someone notices and re-allows. The slow pre-lock step is a delay the real scheduler can produce (slow external authorizer or GC), not a fabricated state. The quota check itself is right given the state; the bug is the lost update from the unfenced stale duplicate.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** allowSnapshot/disallowSnapshot are marked @Idempotent and get no retry-cache or ordering protection, but the pair is not idempotent when combined: a delayed original disallowSnapshot can run after the client's successful retry and after a later allowSnapshot from the same admin. The NameNode then holds state the coordination should never produce. The admin's last acknowledged operation made '/' snapshottable, yet the namespace (and the edit log, so the standby and restarted NNs too) records '/' as not snapshottable with quota 0. For the root directory this shows up as the quota check at line 189 rejecting every createSnapshot('/') with a misleading 'snapshot quota is 0' error. In a real deployment, scheduled backup or DR snapshots of '/' (for example distcp snapshot-diff based replication) fail until someone notices and runs allowSnapshot again. Snapshots that should have been taken are silently missing. The trigger is realistic: a client RPC timeout plus a slow pre-lock step in the handler (an external authorization plugin, group lookup, GC pause) together with the HDFS client's built-in automatic retry and failover of idempotent calls.

**Execution (agent):** Setup: HA MiniDFSCluster with NN0 active and NN1 standby, plus 1 DN. NN config: an external INodeAttributeProvider/AccessControlEnforcer (like a Ranger-style plugin) that only delegates to the default enforcer, but its superuser check for the first disallowSnapshot call is slow (held on a latch, standing in for a slow remote policy/audit call). That check runs in the RPC handler BEFORE the FSNamesystem write lock is taken. Client: failover proxy with ipc.client.rpc-timeout.ms=3000. 1) The admin runs allowSnapshot('/'), then createSnapshot('/','s0') and deleteSnapshot('/','s0'); '/' is a normal snapshottable root. 2) The admin runs disallowSnapshot('/') (Call#20). On NN0 the handler for attempt A blocks in the authorization check. After 3 s the client gets a SocketTimeoutException. disallowSnapshot is @Idempotent, so RetryInvocationHandler fails over to NN1 (StandbyException), fails back to NN0 and retries (attempt B). B runs resetSnapshottable('/') (root quota set to 0) and returns success to the admin. 3) The admin runs allowSnapshot('/'). setSnapshottable sets the root's snapshot quota back to 65536 and adds '/' to snapshottables. getSnapshottableDirListing shows '/'. 4) The stale attempt A now gets past the authorization check, takes the write lock, and runs resetSnapshottable('/') again. The root has 0 snapshots, so the root's quota becomes 0 and '/' is removed from snapshottables. This is logged as OP_DISALLOW_SNAPSHOT after OP_ALLOW_SNAPSHOT, so the standby and any restart replay it too. A's response is dropped ('output error'). 5) The admin runs createSnapshot('/','s1'). DirectorySnapshottableFeature.addSnapshot sees n=0 and snapshotQuota=0, so the check n+1 > snapshotQuota fails at line 189 with SnapshotException 'Failed to add snapshot: there are already 0 snapshot(s) and the snapshot quota is 0'. Other paths I tried that do not fail: NN restart with edits only and with saveNamespace (the root quota round-trips correctly through PB fsimage and edit replay); edit replay ordering (all snapshot ops log under the FS write lock); HA failover and crash before or after logSync; reserved paths. A second route exists in RBF (RouterSnapshot.allowSnapshot uses invokeSequential and stops at the first successful destination, so a mount whose destinations are subcluster roots can leave one root un-allowed). It cannot be built offline here because of missing mapreduce and derby artifacts.

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.namenode.snapshot.DirectorySnapshottableFeature.addSnapshot(DirectorySnapshottableFeature.java:189)

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.namenode.snapshot.TestRootSnapshotStaleDisallowRetry#testStaleDisallowSnapshotRetryResetsRootQuota`
- Command: `source /bulk/codingagent/cases/hdfs-adhoc-49/agent/env.sh && mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.namenode.snapshot.TestRootSnapshotStaleDisallowRetry#testStaleDisallowSnapshotRetryResetsRootQuota' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot/TestRootSnapshotStaleDisallowRetry.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hdfs.protocol.SnapshotException:`, frame `at org.apache.hadoop.hdfs.server.namenode.snapshot.DirectorySnapshottableFeature.addSnapshot(DirectorySnapshottableFeature.java:189)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h12m | 7 | 2,807,444 | 82 | 44,814 | 108,869 | 2,653,679 | $2.30 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
