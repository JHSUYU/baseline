# MC-1 investigation record (evidence only)

Tree: pinned `1790942bb2`. All `file:line` below are against the pristine tree. The worktree arrived with
Phase 2.5 instrumentation applied (`git diff` 14 files plus two untracked). It was saved to
`instrumentation-backup/` and reversed before any build, so the reproduction runs without Specula code.

Finding citation note: the finding gives HM:2617 for the call; the pristine line and the stack frame are HM:2615. HM:2630 (abort) is as cited.

Abbreviations: HM = HMaster, CSSI = ClusterSchemaServiceImpl, NSM = NamespaceStateManager,
TNM = TableNamespaceManager, MQM = MasterQuotaManager, DNP = DeleteNamespaceProcedure.

## Step 1: code audit

### The check
`CSSI.getNamespace` (CSSI:109-113): `nsd = getTableNamespaceManager().get(name); if (nsd == null) throw new
NamespaceNotFoundException(name)`. The read is `TNM.cache.get` (TNM:~191), a ConcurrentHashMap with no lock.

### Call chain from master startup to the check
```
HM.startActiveMasterManager                 HM:2615 finishActiveMasterInitialization()
  HM.finishActiveMasterInitialization       HM:1335 initQuotaManager()     (after HM:1300 setInitialized(true))
    HM.initQuotaManager                     HM:1623 quotaManager.start()
      MQM.start                             MQM:115 namespaceQuotaManager.start()
        NamespaceAuditor.start              NamespaceAuditor:49
          NSM.start -> NSM.initialize       NSM:224 getNamespaces()  (snapshot)
                                            NSM:227 listTableNamesByNamespace(ns)
            HM.listTableNames               HM:3851 cpHost.preGetTableNames; HM:3853 getTableDescriptors
              HM.getTableDescriptors        HM:3876 clusterSchemaService.getNamespace(ns)
                CSSI.getNamespace           CSSI:111 throw
```
No try/catch on this path between NSM:224 and HM:2615. The `catch (Throwable t)` at HM:2617 logs at HM:2619 and calls
`abort("Unhandled exception. Starting shutdown.", t)` (HM:2630). Quota must be enabled (MQM.start returns early
otherwise), which the workload does (`QuotaUtil.QUOTA_CONF_KEY = true`).

### The writer racing the check
`DNP` (procedure), `AbstractStateMachineNamespaceProcedure.waitInitialized` -> `env.waitInitialized(this)`: a
recovered DNP is held until `setInitialized(true)` at HM:1300 and then runs concurrently with the init thread.
- PREPARE: `prepareDelete`, DNP:~183 (checks `doesNamespaceExist`, counts tables).
- DELETE_FROM_NS_TABLE: `TNM.deleteNamespace` removes the meta row, then `cache.remove` (TNM:218).
- NSM takes no namespace lock, and `TNM.get` takes none, so nothing orders the DNP against NSM:224-227.

### Reachability
Public API `Admin.deleteNamespace` persists the DNP on submit. A master crash then recovers it on the backup
master. Every step in the counterexample corresponds to code above:
State 43 ClientDeleteNamespace(m1), 44 MasterCrash(m1), 45-51 m2 start and cache load (nsp still in meta),
52 GateInitialized, 53 QuotaSnapshot (NSM:224), 54-56 DnpPrepare / DnpMetaDelete / DnpCacheRemove, 57 TargetCheck_NsmInit (NSM:227).

### Ordering of namespaces in the snapshot
`getNamespaces` sorts by `NAMESPACE_DESCRIPTOR_COMPARATOR`, plain `String.compareTo` (NamespaceDescriptor:72-79,
CSSI:118). `TestNamespaceAuditor_np2` sorts before `default` and `hbase`, so with only the workload's namespace
the lookup is the first thing after the snapshot and the window is very short. Any namespace sorting earlier adds
its work to the window: one `listTableNames`, and one `MetaTableAccessor.getTableRegions` scan per table (NSM:233).

### Safeguards recorded, to be tested in Phase 2
- HM:1262 cache load precedes the gate, so the namespace IS in the cache at snapshot time (needed for the race, not a guard).
- `checkInitialized` at HM:3759 passes (gate already open).
- HA: a further master can take over after the abort (does recovery hold? tested in Phase 2).
- Neighbouring hazard: DNP's REMOVE_NAMESPACE_QUOTA step calls `getMasterQuotaManager().removeNamespaceQuota`; the
  field is only published after `quotaManager.start()` returns (HM:1623-1624), so it can be null in this same window.

### Comments near the code
TNM:~130 comment reasons about master-init ordering, but about the DisableTableProcedure and the namespace table:
"DisableTableProcedure can only be executed after master is initialized". It says nothing about DNP versus quota init.

## Step 2 and 3: developer knowledge and known status
Per adhoc Shared Rule 2 the history and tracker search runs only after the reproduction verdict is settled. See the
section at the end of this file. This finding is MC-sourced with an actual counterexample, so the code-review drop does not apply.

## Step 2 and 3 (run after the reproduction verdict was settled; Novelty only)

### Queries
Local history (pinned tree, no checkout):
- `git log --oneline -8 -- .../namespace/NamespaceStateManager.java`
- `git log --all --grep='NamespaceStateManager\|quota.*failover\|deleteNamespace.*master\|DeleteNamespaceProcedure' -i`
- `git log -S'status.setStatus("Starting quota manager");' -- .../HMaster.java`; `git log -S'Set master as' -- .../HMaster.java`

ASF JIRA REST (`project=HBASE AND ...`), result count in brackets:
- `text ~ "NamespaceStateManager" AND text ~ "NamespaceNotFoundException"` [0]
- `text ~ "NamespaceStateManager.initialize"` [0]
- `text ~ "NamespaceAuditor" AND text ~ "abort"` [1: HBASE-14614, unrelated]
- `summary ~ "namespace" AND summary ~ "quota" AND (summary ~ "master" OR "failover" OR "startup")` [1: HBASE-16488]
- `text ~ "DeleteNamespaceProcedure" AND (text ~ "failover" OR "NullPointerException" OR "removeNamespaceQuota")` [1: HBASE-30008]
- `updated >= "2026-05-01" AND text ~ "namespace" AND (text ~ "quota" OR "failover" OR "abort")` [79; first 20 by default order read, none on this mechanism]
- `text ~ "Failed to become active master" AND text ~ "namespace"` [23; first 20 read, none on this mechanism]
- `text ~ "getNamespace" AND text ~ "NamespaceNotFoundException" AND text ~ "master"` [0]

GitHub search API, `repo:apache/hbase is:pr <q>`, sorted by updated (open, closed and merged all included; `gh` is not installed, so curl):
- `NamespaceStateManager` [3: #8792, #8787 HBASE-30483 truncate count; #6501 HBASE-29005 split quota table]
- `NamespaceNotFoundException quota` [0]
- `DeleteNamespaceProcedure` [1: #7957]
- `deleteNamespace failover` [0]
- `initQuotaManager` [6: HBASE-30473, HBASE-30348 and its reverts, unrelated]
- `HBASE-30008` [1: #7957]
- `namespace quota master initialization` [7: HBASE-30348 family, HBASE-30064, unrelated]

Web search: "HBase master abort NamespaceNotFoundException NamespaceStateManager.initialize DeleteNamespaceProcedure failover quota enabled": API docs only, no report.

Limit: the JIRA searches with 79 and 23 hits were read only to the first 20, so a report ranked below that is not excluded by those two queries. The targeted class-name queries returned 0.

### What was found
- HBASE-30008 / PR #7957 (open, not merged): "It is possible that HMaster marks itself initialized before it creates and stores quotaManager, which can cause NPE." Same gate ordering, DIFFERENT site and symptom: DNP/CNP's `getMasterQuotaManager()`. The PR diff changes only `setNamespaceQuota` and `removeNamespaceQuota` to `ProcedureSyncWait.getMasterQuotaManager(env)`. That step runs after `cache.remove`, so it leaves NSM:224-227 open. Not a match for MC-1; it IS a match for the neighbouring NPE seen in these runs.
- HBASE-13194 (closed, fixed 2.0.0), Duo Zhang, 2015-03-12: "The only doubt is that whether it is safe to just throw the exception out if stateManager.initialize is fail. Of course I think it is rarely happen since now we only call it after namespaceManager is initialized." Developer awareness that an init throw is fatal, about namespace-manager readiness rather than this race. Awareness does not make it known (Phase 1 Step 3).
- HBASE-16488 (Won't Fix): start namespace and quota services asynchronously, because namespace-region assignment was failing startup. Different failure.
- HBASE-20644 (open, 2018): `ClusterSchemaServiceImpl` failing to start at `initClusterSchemaService`. Different site and cause.
- HBASE-30483 / #8792: truncate-table region count. Different.
- History of the site: `initQuotaManager` dates to HBASE-11598. Commit messages found state no intent about DNP racing NSM.
- Existing tests: `TestNamespaceAuditor#killActiveMaster` restarts a master with no in-flight DNP; no test sets up this scenario or asserts the abort as intended.

### Known status
No report of THIS mechanism at THIS site, open or closed, in the tracker or in recent PRs. Novelty: NEW.
