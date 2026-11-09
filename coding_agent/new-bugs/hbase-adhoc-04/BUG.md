# hbase-adhoc-04: QuotaObserverChore records the 'in observance' state before re-enabling the table; if that one enable fails, it is never retried and the table stays disabled until an admin enables it.

Severity (reviewer): **outage**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/master/procedure/AbstractStateMachineTableProcedure.java:163`, `AbstractStateMachineTableProcedure.preflightChecks(MasterProcedureEnv, Boolean)`, throws `org.apache.hadoop.hbase.TableNotEnabledException` when `enabled && !ts.isEnabledOrEnabling()   (ts = master.getTableStateManager().getTableState(tn))`
- Starting test: `org.apache.hadoop.hbase.quotas.TestAdhocWorkload04#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** The table is in DISABLE space-quota violation and its quota goes back into observance. The one enableTable request the QuotaObserverChore issues fails at the master (a master coprocessor throws IOException in preEnableTable, i.e. a failed RPC). The client uses retries=0, a valid setting inherited from the starting workload.

**Why (root cause in the source):** QuotaObserverChore.updateTableQuota (QuotaObserverChore.java:322-333) writes the observance state to hbase:quota (transitionTable) and to the in-memory store (tableSnapshotStore.setCurrentState, line 325) before it calls QuotaUtil.enableTableIfNotEnabled (line 333). When the enable fails, chore() logs 'Will retry' (line 137). The retry never happens: the next run reads current == target from the store (line 247) and does nothing. A restarted master reloads the same observance state from hbase:quota. The table therefore stays DISABLED for good although its quota is in observance, and every later operation that needs an enabled table, here flush, is rejected at AbstractStateMachineTableProcedure.java:163. The test calls updateTableQuota directly on a chore it builds itself. It passes the same (current, target) pair the real processTablesWithQuotas would pass (line 247-254), and it injects the fault at an RPC boundary, so the path is reachable in production. The check itself is right to reject; the bug is the state the chore leaves behind.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** With the DISABLE space-violation policy, the quota observer coordinates the table's enabled state with its quota status: when the table goes back into observance, the observer is the one that must re-enable it. QuotaObserverChore.updateTableQuota writes the new 'in observance' state to hbase:quota and to its in-memory snapshot store before the side effect (enableTable) has succeeded. If that one enable request fails (transient master error, RPC timeout, master busy), later chore runs see current == target and never retry. The table is left disabled indefinitely although the quota system reports it in observance and no admin disabled it. Every table operation that requires an enabled table (flush, split, merge, reads and writes) is rejected, here by the TableNotEnabledException check, until an operator notices and enables the table by hand. The user's request is valid; the observer's coordination produced the inconsistent state.

**Execution (agent):** 1) One-RS mini cluster with space quotas on; a master coprocessor (test fault injection) makes the next EnableTable RPC fail with a transient IOException, standing in for a failed/lost master request. 2) Table adhoc_workload_04 is created and then disabled. The QuotaObserverChore (client retries=0) begins with the table's snapshot in DISABLE violation. 3) Observer run 0: updateTableQuota(current=DISABLE-violation, target=observance) calls snapshotNotifier.transitionTable (hbase:quota gets the observance state) and then tableSnapshotStore.setCurrentState(table, observance) BEFORE it calls QuotaUtil.enableTableIfNotEnabled. The enableTable RPC fails and the IOException propagates. 4) Observer run 1: getTableQuotaSnapshot now returns the observance snapshot, so current.equals(target) holds and the method does nothing. Enable is never retried (only 1 enable attempt was seen). 5) The table stays DISABLED even though its quota is in observance. admin.flush(table) submits a FlushTableProcedure, and preflightChecks(env, true) finds state DISABLED and throws TableNotEnabledException at AbstractStateMachineTableProcedure.java:163.

**Stack frame (agent):** at org.apache.hadoop.hbase.master.procedure.AbstractStateMachineTableProcedure.preflightChecks(AbstractStateMachineTableProcedure.java:163)

## Reproduction

- Test: `org.apache.hadoop.hbase.quotas.TestAdhocWorkload04LostEnable#run`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.quotas.TestAdhocWorkload04LostEnable#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/quotas/TestAdhocWorkload04LostEnable.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hbase.TableNotEnabledException: adhoc_workload_04`, frame `at org.apache.hadoop.hbase.master.procedure.AbstractStateMachineTableProcedure.preflightChecks(AbstractStateMachineTableProcedure.java:163)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h02m | 1 | 239,861 | 16 | 7,547 | 28,699 | 203,599 | $0.42 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
