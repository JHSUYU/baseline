# HBASE-20642 (Adding column family fails): detected

Case `hbase-adhoc-k2`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/master/HMaster.java:2255`, `HMaster.addColumn(TableName, ColumnFamilyDescriptor, long, long)`, throws `org.apache.hadoop.hbase.InvalidFamilyOperationException` when `old.hasColumnFamily(column.getName())   (old = getTableDescriptors().get(tableName))`
- Starting test: `org.apache.hadoop.hbase.master.procedure.TestTableDescriptorModificationFromClient#testAddColumn`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** A single Admin.addColumnFamily whose master response is delayed past the client RPC timeout (after ModifyTableProcedure already added the family) is retried by RpcRetryingCaller; the retry hits the 'already exists' check in HMaster.addColumn and the client gets InvalidFamilyOperationException although the family was added by that same call.

**Same root cause as HBASE-20642?** Yes. The buggy HBaseAdmin.addColumnFamilyAsync builds the request inside rpcCall() with ng.newNonce() (hbase-client/.../HBaseAdmin.java:1027), so every retry attempt carries a fresh nonce, and HMaster.addColumn (HMaster.java:2253-2256) evaluates old.hasColumnFamily() before and outside NonceProcedureRunnable's nonce dedup. The retry therefore cannot be recognised as a duplicate and is rejected. The fix hunks change exactly this: HBaseAdmin hoists 'Long nonceGroup = ng.getNonceGroup(); Long nonce = ng.newNonce();' out of rpcCall() so retries reuse the nonce, and HMaster.addColumn moves the hasColumnFamily check into a TableDescriptorGetter evaluated inside the NonceProcedureRunnable.run() of the new private modifyTable(), so a retried request with the same nonce is deduplicated before the check runs.

**Realistic?** Yes. Mini cluster, default client retry policy with a valid hbase.rpc.timeout (3s); the only injection is a master coprocessor whose postModifyTable sleeps ~6s after the procedure completed, i.e. a delay in the master RPC handler that makes the response arrive after the client timeout, which a GC pause, overloaded master or slow network can produce. The client's retry is its own normal RpcRetryingCaller behaviour; no reflection, fabricated arguments or direct calls to the check.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **NOT_REPRODUCED**. On the buggy tree plus the fix's production changes the test fails at its fail("expected the retried addColumn to be rejected") line in both runs: addColumnFamily now returns successfully, no InvalidFamilyOperationException is thrown. The retry reuses the nonce and is deduplicated, so the consequence is gone.

**Reason:** The agent's failing execution is exactly HBASE-20642: a client-retried addColumn DDL with a new nonce is not recognised by the master as a retry of an already-applied operation and is rejected with InvalidFamilyOperationException. The trigger (RPC timeout from a delayed master response) is realistic and the consequence (a successful add reported as failed) matches the JIRA. The fixed version makes the call succeed, which supports this.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The client and master coordinate the add-column operation via an RPC that is retried on timeout; the retry is supposed to be idempotent (that is what the nonce group/nonce in AddColumnRequest is for). But the 'family already exists' check is evaluated against the current descriptor before, and independently of, nonce deduplication, and HBaseAdmin re-generates the nonce on each attempt, so the master cannot recognize the retry as a duplicate of its own already-applied operation. The check thus rejects state produced by the same logical request, not an invalid user request. Consequence: in a real deployment any slow/lost master response (GC pause, overloaded master, network hiccup, master failover after the procedure completed) makes a successful addColumnFamily report failure (InvalidFamilyOperationException 'already exists'); applications/tools (schema migration scripts, shell) treat it as an error, may abort or roll back, and the reported result contradicts the actual table schema. The same pattern affects deleteColumn/modifyColumn retries.

**Execution (agent):** Mini cluster: 1 master, 1 RS; table T with family cf0, disabled. A client (hbase.rpc.timeout=3s, default retry policy) calls Admin.addColumnFamily(T, cf1) once. (1) The master RPC handler runs HMaster.addColumn: check passes (cf1 absent), modifyTable() submits ModifyTableProcedure and waits only for its prepare latch. (2) The procedure runs to completion and writes the new descriptor {cf0, cf1} (postCompletedModifyTableAction fires). (3) The RPC handler is then slow to return the response (modelled by a master coprocessor whose postModifyTable stalls 6s, i.e. longer than the client RPC timeout - in production: GC pause, slow coprocessor, network delay/lost response). (4) The client gets CallTimeoutException, which is retriable, and RpcRetryingCaller re-sends AddColumnRequest (HBaseAdmin even generates a fresh nonce per attempt; in any case the check runs before the nonce dedup in NonceProcedureRunnable). (5) The retried request reaches HMaster.addColumn, getTableDescriptors().get(T) already contains cf1 added by the first attempt, so InvalidFamilyOperationException is thrown at HMaster.java:2255. Since it is a DoNotRetryIOException the client's single addColumnFamily call fails with it, while the table actually has cf1. Only one 'modify testAddColumnRetry' is logged by the master.

**Stack frame (agent):** at org.apache.hadoop.hbase.master.HMaster.addColumn(HMaster.java:2255)

## Reproduction

- Test: `org.apache.hadoop.hbase.master.procedure.TestAddColumnFamilyRetryAfterTimeout#testAddColumnRetriedAfterRpcTimeout`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.master.procedure.TestAddColumnFamilyRetryAfterTimeout#testAddColumnRetriedAfterRpcTimeout' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/master/procedure/TestAddColumnFamilyRetryAfterTimeout.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hbase.InvalidFamilyOperationException: Column family 'cf1' in table 'testAddColumnRetry' already exists so cannot be added`, frame `at org.apache.hadoop.hbase.master.HMaster.addColumn(HMaster.java:2255)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h02m | 1 | 212,124 | 16 | 9,425 | 24,114 | 178,569 | $0.42 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
