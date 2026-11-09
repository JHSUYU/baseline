# hbase-adhoc-35: setRegionStateInMeta for the hbase:meta region writes a bogus meta row into hbase:meta itself instead of rejecting the request or routing it to the master local region, permanently breaking hbck1 ('Two entries in hbase:meta are same').

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/util/HBaseFsck.java:2742`, `HBaseFsck.loadMetaEntries() (its ClientMetaTableAccessor.Visitor.visit(Result))`, throws `java.io.IOException` when `previous != null && previous.getMetaEntry() != null   (previous = regionInfoMap.get(hri.getEncodedName()))`
- Starting test: `org.apache.hadoop.hbase.util.TestHBaseFsckReplication#test`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** On a mini cluster, an operator calls the HBCK2 admin API Hbck#setRegionStateInMeta({1588230740 -> CLOSED}) for the hbase:meta region, and then runs hbck1 (HBaseFsck).

**Why (root cause in the source):** MasterRpcServices.setRegionStateInMeta accepts the meta region: it resolves it from the AssignmentManager and calls MetaTableAccessor.updateRegionState (MasterRpcServices.java:2696-2710). That method always Puts into the hbase:meta table and has no isMetaRegion guard (MetaTableAccessor.java:781-786). Yet the meta region's state belongs in the master local region, and RegionStateStore routes it there (RegionStateStore.java:238,279). The master reports success but leaves a persistent self-referencing 'hbase:meta,,1' row inside hbase:meta, and the requested state change never reaches the real meta state store. hbck1 then finds two records for 1588230740, one from the locator and one from the bogus row, and aborts with 'Two entries in hbase:meta are same' (HBaseFsck.java:2742). The check is correctly detecting corruption that the master wrote in response to an ordinary, accepted admin request. This is not a rejection of an invalid request, since the master never rejects it. The demonstrated consequence is that every later hbck1 run fails until the row is removed by hand. Possible effects on other meta scanners were not demonstrated.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The coordination behind the check is that each region has at most one record: user regions get one row in hbase:meta, and the hbase:meta region gets its single record in the master local region, mirrored to ZK and taken from the locator. The master breaks this when it handles a legitimate HBCK2/Hbck admin RPC for the meta region. It accepts the request (it neither rejects nor routes it) and persists the meta region's state into hbase:meta through MetaTableAccessor.updateRegionState, which has no isMetaRegion guard. Other paths do have that guard (RegionStateStore.updateRegionLocation, HRegionServer.skipReportingTransition). The request is not rejected as invalid. The master reports success, and the result is a persistent, corrupt self-referencing row in hbase:meta. Consequences in a real deployment: every later hbck1 run aborts with 'Two entries in hbase:meta are same', so the cluster can no longer be checked or repaired with it. The bogus row also sits among user-region rows that the master, CatalogJanitor and getAllRegions-style scans read (am.populateRegionStatesFromMeta re-reads it right away), and the requested state change for meta never reaches the real meta state store.

**Execution (agent):** 1) Start a mini cluster (1 master, 1 RS) and create a user table 't'. HBaseFsck (hbck1) runs clean. 2) An operator calls the HBCK2 admin API Hbck#setRegionStateInMeta({1588230740 (hbase:meta region) -> CLOSED}), the RPC that HBCK2 'setRegionState' sends, for example to unstick meta after an RS crash. MasterRpcServices.setRegionStateInMeta resolves the meta RegionInfo from the AM, finds that current state OPEN != CLOSED, and calls MetaTableAccessor.updateRegionState(conn, metaRegionInfo, CLOSED). That method always Puts to the hbase:meta table, so it writes a row 'hbase:meta,,1' with info:regioninfo = hbase:meta,,1 into hbase:meta itself. The meta region's state is supposed to live only in the master local region (RegionStateStore routes meta to masterRegion, and HRegionServer.skipReportingTransition explicitly refuses to write meta's location into hbase:meta). The test's own scan shows the bogus row. 3) HBaseFsck runs again: recordMetaRegion() puts hbase:meta,,1 (encoded 1588230740) into regionInfoMap with a MetaEntry from the locator. Then loadMetaEntries() scans hbase:meta. The visitor keeps meta regions (isTableIncluded || hri.isMetaRegion()) and reaches the bogus row for 1588230740. previous.getMetaEntry() != null, so it throws java.io.IOException 'Two entries in hbase:meta are same { meta => hbase:meta,,1.1588230740 ... }' at HBaseFsck.java:2742, and onlineHbck aborts.

**Stack frame (agent):** at org.apache.hadoop.hbase.util.HBaseFsck$3.visit(HBaseFsck.java:2742)

## Reproduction

- Test: `org.apache.hadoop.hbase.util.TestHBaseFsckMetaRowInMeta#test`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.util.TestHBaseFsckMetaRowInMeta#test' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/util/TestHBaseFsckMetaRowInMeta.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.io.IOException: Two entries in hbase:meta are same { meta => hbase:meta,,1.1588230740, hdfs => null, deployed => agent-host,45713,1794080666440;hbase:meta,,1.1588230740, replicaId => 0 }`, frame `at org.apache.hadoop.hbase.util.HBaseFsck$3.visit(HBaseFsck.java:2742)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h09m | 1 | 3,241,928 | 92 | 39,393 | 115,367 | 3,087,076 | $2.33 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
