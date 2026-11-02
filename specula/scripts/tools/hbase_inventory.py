#!/usr/bin/env python3
"""Write hbase/inventory.tsv and hbase/targets/<case>.yaml (operator tool, B2).

Sites: the fork's markers (/bulk/wt/hbase-checks) mapped to upstream apache/hbase 1790942bb2 (find_sites.py), read by
hand.  Workloads and scope: GraphChecker origin/system/hbase-cloudlab experiments/hbase/hbase-adhoc/checks.tsv.
"""
import csv, subprocess
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc/hbase")
BASE = "1790942bb2"
S = "hbase-server/src/main/java/org/apache/hadoop/hbase"
H = "org.apache.hadoop.hbase"
PRE = "(MasterProcedureEnv, Boolean)"
AMC = "AssignmentManager.preTransitCheck(RegionStateNode, RegionState.State[])"
MTR = "MergeTableRegionsProcedure.prepareMergeRegion(MasterProcedureEnv)"
ROWS = {
 "04": (f"{S}/master/procedure/AbstractStateMachineTableProcedure.java", 163, "AbstractStateMachineTableProcedure.preflightChecks" + PRE, f"{H}.TableNotEnabledException", "enabled && !ts.isEnabledOrEnabling()   (ts = master.getTableStateManager().getTableState(tn))"),
 "07": (f"{S}/master/snapshot/SnapshotManager.java", 1046, "SnapshotManager.restoreSnapshot(SnapshotDescription, TableName, SnapshotDescription, TableDescriptor, NonceKey, boolean)", "java.lang.UnsupportedOperationException", "master.getTableStateManager().isTableState(TableName.valueOf(snapshot.getTable()), TableState.State.ENABLED)"),
 "08": (f"{S}/master/ClusterSchemaServiceImpl.java", 111, "ClusterSchemaServiceImpl.getNamespace(String)", f"{H}.NamespaceNotFoundException", "nsd == null   (nsd = getTableNamespaceManager().get(name))"),
 "10": (f"{S}/master/assignment/AssignmentManager.java", 765, AMC, f"{H}.HBaseIOException", "regionNode.getProcedure() != null"),
 "11": (f"{S}/master/assignment/AssignmentManager.java", 769, AMC, f"{H}.client.DoNotRetryRegionException", "!regionNode.isInState(expectedStates)"),
 "12": (f"{S}/master/assignment/AssignmentManager.java", 772, AMC, f"{H}.DoNotRetryIOException", "isTableDisabled(regionNode.getTable())"),
 "13": (f"{S}/master/assignment/MergeTableRegionsProcedure.java", 499, MTR, f"{H}.exceptions.MergeRegionException", "regionStateStore.hasMergeRegions(ri)   (for a region ri to merge)"),
 "14": (f"{S}/master/assignment/MergeTableRegionsProcedure.java", 503, MTR, f"{H}.UnknownRegionException", "state == null   (state = regionStates.getRegionState(ri.getEncodedName()))"),
 "15": (f"{S}/master/assignment/MergeTableRegionsProcedure.java", 507, MTR, f"{H}.exceptions.MergeRegionException", "!state.isOpened()"),
 "19": (f"{S}/master/procedure/ModifyTableProcedure.java", 134, "ModifyTableProcedure.preflightChecks" + PRE, f"{H}.HBaseIOException", "!reopenRegions && !this.unmodifiedTableDescriptor.getTableName().equals(this.modifiedTableDescriptor.getTableName())"),
 "20": (f"{S}/master/procedure/ModifyTableProcedure.java", 138, "ModifyTableProcedure.preflightChecks" + PRE, f"{H}.HBaseIOException", "!reopenRegions && this.unmodifiedTableDescriptor.getColumnFamilyCount() != this.modifiedTableDescriptor.getColumnFamilyCount()"),
 "21": (f"{S}/namespace/NamespaceStateManager.java", 130, "NamespaceStateManager.checkAndUpdateNamespaceRegionCount(TableName, int)", f"{H}.quotas.QuotaExceededException", "nspdesc != null && (currentStatus.getRegionCount() - regionCountOfTable + incr) > TableNamespaceManager.getMaxRegions(nspdesc)"),
 "22": (f"{S}/namespace/NamespaceStateManager.java", 168, "NamespaceStateManager.checkAndUpdateNamespaceTableCount(TableName, int)", f"{H}.quotas.QuotaExceededException", "(currentStatus.getRegionCount() + numRegions) > TableNamespaceManager.getMaxRegions(nspdesc)"),
 "24": (f"{S}/procedure/ZKProcedureMemberRpcs.java", 210, "ZKProcedureMemberRpcs.startNewSubprocedure(String)", "java.lang.IllegalArgumentException", "!ProtobufUtil.isPBMagicPrefix(data)   (data = ZKUtil.getData(zkController.getWatcher(), path))"),
 "28": (f"{S}/HBaseServerBase.java", 353, "HBaseServerBase.putUpWebUI()", "java.io.IOException", "!Addressing.isLocalAddress(InetAddress.getByName(addr))"),
 "31": (f"{S}/regionserver/RSRpcServices.java", 1878, "RSRpcServices.throwOnWrongStartCode(long)", "org.apache.hbase.thirdparty.com.google.protobuf.ServiceException", "server.getServerName().getStartcode() != serverStartCode   (wraps a DoNotRetryIOException)"),
 "34": (f"{S}/security/token/AuthenticationTokenSecretManager.java", 160, "AuthenticationTokenSecretManager.retrievePassword(AuthenticationTokenIdentifier)", "org.apache.hadoop.security.token.SecretManager.InvalidToken", "masterKey == null   (masterKey = allKeys.get(identifier.getKeyId()))"),
 "35": (f"{S}/util/HBaseFsck.java", 2742, "HBaseFsck.loadMetaEntries() (its ClientMetaTableAccessor.Visitor.visit(Result))", "java.io.IOException", "previous != null && previous.getMetaEntry() != null   (previous = regionInfoMap.get(hri.getEncodedName()))"),
 "37": ("hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.java", 206, "MasterAddressTracker.getMasterInfoPort(ZKWatcher)", "java.io.IOException", "data == null   (data = ZKUtil.getData(zkw, zkw.getZNodePaths().masterAddressZNode))"),
}
PORTED = {"04": "org.apache.hadoop.hbase.quotas.TestAdhocWorkload04#run", "07": "org.apache.hadoop.hbase.snapshot.TestAdhocWorkload07#run",
          "22": "org.apache.hadoop.hbase.namespace.TestAdhocWorkload22#run", "34": "org.apache.hadoop.hbase.security.token.TestAdhocWorkload34#run"}


def main():
    text = subprocess.run(["git", "-C", "/bulk/GraphChecker", "show", "origin/system/hbase-cloudlab:experiments/hbase/hbase-adhoc/checks.tsv"],
                          capture_output=True, text=True, check=True).stdout
    tsv = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        tsv[f[0]] = (f"{f[1]}#{f[2]}", [s.split(":", 1)[1].replace("/", ".") for s in f[5:] if s.strip()])
    (ROOT / "targets").mkdir(parents=True, exist_ok=True)
    cols = ["case", "gc_case", "gc_branch", "site_upstream", "method", "thrown", "guard", "workload", "workload_origin", "gc_workload", "module", "scope", "tree", "status"]
    with open(ROOT / "inventory.tsv", "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for n, (file, line, method, thrown, guard) in ROWS.items():
            case = f"hbase-adhoc-{n}"
            gcw, scope = tsv[n]
            wl = PORTED.get(n, gcw)
            w.writerow([case, case, "system/hbase-cloudlab", f"{file}:{line}", method, thrown, guard, wl, "ported" if n in PORTED else "upstream", gcw, "hbase-server", " ".join(scope), f"apache/hbase {BASE}", ""])
            q = '"' + guard.replace('"', '\\"') + '"'
            y = [f"id: {case}", "system: Apache HBase", "source_tree: /set/by/run-case.sh", f"base_commit: {BASE}", "check:",
                 f"  file: {file}", f"  line: {line}", f"  method: {method}", f"  thrown: {thrown}", f"  guard: {q}", "workload:",
                 "  module: hbase-server", f"  test: {wl}", "  note: the test reaches the check's method and passes; the check does not fail in it",
                 "scope_hint:"] + [f"  - {c}" for c in scope] + [
                 "build:", "  env: /set/by/run-case.sh", '  prepare: "mvn -B install -DskipTests -Dmaven.javadoc.skip=true -Denforcer.skip=true   (already done once)"',
                 "  test_command: \"mvn -B -o surefire:test -pl hbase-server -Dtest='<Class>#<method>' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false\""]
            (ROOT / "targets" / f"{case}.yaml").write_text("\n".join(y) + "\n")


if __name__ == "__main__":
    main()
