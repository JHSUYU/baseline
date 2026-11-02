#!/usr/bin/env python3
"""Write zookeeper/inventory.tsv and zookeeper/targets/<case>.yaml (operator tool, B2).

Sites read by hand at upstream apache/zookeeper eab16599 (GraphChecker ZOOKEEPER.md §E gives the lines on that
master).  Workloads and scope: GraphChecker origin/system/zookeeper experiments/zookeeper/zk-adhoc/checks.tsv
and zk-bugs/case.sh.  Bug points get neutral ids zk-adhoc-b1..b6; their real names are only in this inventory.
"""
import csv, subprocess
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc/zookeeper")
BASE = "eab16599"
S = "zookeeper-server/src/main/java/org/apache/zookeeper/server"
SRV = "zookeeper-server"
KE = "org.apache.zookeeper.KeeperException"
CRE = "org.apache.zookeeper.server.ServerCnxn.CloseRequestException"
IOE = "java.io.IOException"

# case: (gc case, file, line, method, thrown, guard, workload Class#method, workload origin, module, scope (class names))
ROWS = {
 "zk-adhoc-01": ("zk-adhoc-01", "SessionTrackerImpl.java", 317, "SessionTrackerImpl.checkSession(long, Object)", f"{KE}.SessionExpiredException",
                 "session.isClosing()   (session = sessionsById.get(sessionId), non-null)", "org.apache.zookeeper.server.quorum.QuorumPeerMainTest#testQuorum", "upstream", SRV, None),
 "zk-adhoc-02": ("zk-adhoc-02", "SessionTrackerImpl.java", 323, "SessionTrackerImpl.checkSession(long, Object)", f"{KE}.SessionMovedException",
                 "session.owner != null && session.owner != owner", "org.apache.zookeeper.test.QuorumTest#testSessionMovedWithSynchronousSync", "upstream", SRV, None),
 "zk-adhoc-03": ("zk-adhoc-03", "SessionTrackerImpl.java", 330, "SessionTrackerImpl.setOwner(long, Object)", f"{KE}.SessionExpiredException",
                 "session == null || session.isClosing()   (session = sessionsById.get(id))", "org.apache.zookeeper.server.quorum.QuorumPeerMainTest#testQuorum", "upstream", SRV, None),
 "zk-adhoc-04": ("zk-adhoc-04", "ZooKeeperServer.java", 1516, "ZooKeeperServer.processConnectRequest(ServerCnxn, ConnectRequest)", CRE,
                 "request.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid   (DisconnectReason.CLIENT_ZXID_AHEAD)", "org.apache.zookeeper.test.ReadOnlyModeTest#testSeekForRwServer", "upstream", SRV, None),
 "zk-adhoc-06": ("zk-adhoc-06", "quorum/Leader.java", 1522, "Leader.waitForEpochAck(long, StateSummary)", IOE,
                 "!electionFinished && ss.getCurrentEpoch() != -1 && ss.isMoreRecentThan(leaderStateSummary)", "org.apache.zookeeper.server.quorum.QuorumPeerMainTest#testQuorum", "upstream", SRV, None),
 "zk-adhoc-07": ("zk-adhoc-07", "quorum/Learner.java", 522, "Learner.registerWithLeader(int)", IOE,
                 "qp.getType() == Leader.LEADERINFO && !(newEpoch > self.getAcceptedEpoch()) && !(newEpoch == self.getAcceptedEpoch())   (newEpoch = epoch of qp.getZxid())", "org.apache.zookeeper.test.QuorumRestartTest#testRollingRestart", "upstream", SRV, None),
 "zk-adhoc-10": ("zk-adhoc-10", "quorum/ObserverMaster.java", 371, "ObserverMaster.removeProposedPacket(long)", "java.lang.RuntimeException",
                 "pkt != null && !(pkt.getZxid() > zxid) && pkt.getZxid() != zxid   (pkt = proposedPkts.peek())", "org.apache.zookeeper.test.ObserverMasterTest#testInOrderCommits[1]", "upstream", SRV, None),
 "zk-adhoc-11": ("zk-adhoc-11", "quorum/QuorumPeer.java", 1236, "QuorumPeer.loadDataBase()", IOE,
                 "epochOfZxid > currentEpoch && !currentTmp.exists()", "org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile", "upstream", SRV, None),
 "zk-adhoc-12": ("zk-adhoc-12", "quorum/QuorumPeer.java", 1256, "QuorumPeer.loadDataBase()", IOE,
                 "acceptedEpoch < currentEpoch", "org.apache.zookeeper.server.quorum.QuorumPeerMainTest#testQuorum", "upstream", SRV, None),
 "zk-adhoc-13": ("zk-adhoc-13", "quorum/ReadOnlyZooKeeperServer.java", 126, "ReadOnlyZooKeeperServer.validateSession(ServerCnxn, long)", CRE,
                 "((LearnerSessionTracker) sessionTracker).isGlobalSession(sessionId)   (DisconnectReason.RENEW_GLOBAL_SESSION_IN_RO_MODE)", "org.apache.zookeeper.test.ReadOnlyModeTest#testConnectionEvents", "upstream", SRV, None),
 "zk-adhoc-b1": ("zk-bugs-quota-init", "FinalRequestProcessor.java", 674, "FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)", f"{KE}.NoNodeException",
                 "n == null   (n = zks.getZKDatabase().getNode(path))", "org.apache.zookeeper.test.TestAdhocWorkloadB1#run", "ported", SRV,
                 ["org.apache.zookeeper.server.FinalRequestProcessor", "org.apache.zookeeper.cli.SetQuotaCommand", "org.apache.zookeeper.server.DataTree", "org.apache.zookeeper.server.NodeHashMapImpl"]),
 "zk-adhoc-b2": ("zk-bugs-election-offer", "FinalRequestProcessor.java", 674, "FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)", f"{KE}.NoNodeException",
                 "n == null   (n = zks.getZKDatabase().getNode(path))", "org.apache.zookeeper.recipes.leader.LeaderElectionSupportTest#testNodes3", "upstream", "zookeeper-recipes/zookeeper-recipes-election",
                 ["org.apache.zookeeper.server.FinalRequestProcessor", "org.apache.zookeeper.recipes.leader.LeaderElectionSupport", "org.apache.zookeeper.server.DataTree", "org.apache.zookeeper.server.NodeHashMapImpl"]),
 "zk-adhoc-b3": ("zk-bugs-container-reuse", "FinalRequestProcessor.java", 674, "FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)", f"{KE}.NoNodeException",
                 "n == null   (n = zks.getZKDatabase().getNode(path))", "org.apache.zookeeper.server.TestAdhocWorkloadB3#run", "ported", SRV,
                 ["org.apache.zookeeper.server.ContainerManager", "org.apache.zookeeper.server.PrepRequestProcessor", "org.apache.zookeeper.server.FinalRequestProcessor", "org.apache.zookeeper.server.DataTree", "org.apache.zookeeper.server.NodeHashMapImpl"]),
 "zk-adhoc-b4": ("zk-bugs-retry-seq-quota", "ZooKeeperServer.java", 2201, "ZooKeeperServer.checkQuota(String, long, long, String)", f"{KE}.QuotaExceededException",
                 "checkCountQuota && newCount > countLimit && isCountHardLimit   (newCount = currentStats.getCount() + countDiff)", "org.apache.zookeeper.retry.TestAdhocWorkloadB4#run", "ported", "zookeeper-contrib/zookeeper-contrib-zooinspector",
                 ["org.apache.zookeeper.retry.ZooKeeperRetry", "org.apache.zookeeper.server.PrepRequestProcessor", "org.apache.zookeeper.server.ZooKeeperServer", "org.apache.zookeeper.server.DataTree"]),
 "zk-adhoc-b5": ("zk-bugs-trunc-sync", "ZKDatabase.java", 341, "ZKDatabase.addCommittedProposal(Request)", "java.lang.IllegalStateException",
                 "!committedLog.isEmpty() && request.zxid > maxCommittedLog && !allowDiscontinuousProposals && request.zxid != maxCommittedLog + 1 && ZxidUtils.getEpochFromZxid(request.zxid) <= ZxidUtils.getEpochFromZxid(maxCommittedLog)",
                 "org.apache.zookeeper.server.quorum.TestAdhocWorkloadB5#run", "ported", SRV,
                 ["org.apache.zookeeper.server.ZKDatabase", "org.apache.zookeeper.server.quorum.Learner", "org.apache.zookeeper.server.quorum.QuorumPeer", "org.apache.zookeeper.server.quorum.LearnerHandler", "org.apache.zookeeper.server.persistence.FileTxnSnapLog", "org.apache.zookeeper.server.persistence.FileTxnLog"]),
 "zk-adhoc-b6": ("zk-bugs-observer-master", "ZKDatabase.java", 341, "ZKDatabase.addCommittedProposal(Request)", "java.lang.IllegalStateException",
                 "!committedLog.isEmpty() && request.zxid > maxCommittedLog && !allowDiscontinuousProposals && request.zxid != maxCommittedLog + 1 && ZxidUtils.getEpochFromZxid(request.zxid) <= ZxidUtils.getEpochFromZxid(maxCommittedLog)",
                 "org.apache.zookeeper.server.quorum.TestAdhocWorkloadB6#run", "ported", SRV,
                 ["org.apache.zookeeper.server.ZKDatabase", "org.apache.zookeeper.server.DataTree", "org.apache.zookeeper.server.quorum.LearnerHandler", "org.apache.zookeeper.server.quorum.ObserverMaster"]),
}
GC_WORKLOAD = {"zk-adhoc-b1": "org.apache.zookeeper.test.CausynthQuotaRetryTest#raisesARetriedHardQuota",
               "zk-adhoc-b3": "org.apache.zookeeper.server.CausynthContainerReuseTest#keepsTheReplacementOfACleanedContainer",
               "zk-adhoc-b4": "org.apache.zookeeper.retry.CausynthZooKeeperRetryQuotaTest#createsTwoSequentialChildrenUnderAHardQuota",
               "zk-adhoc-b5": "org.apache.zookeeper.server.quorum.CausynthTruncSyncTest#aTruncSyncedFollowerRestarts",
               "zk-adhoc-b6": "org.apache.zookeeper.server.quorum.CausynthObserverMasterSyncTest#aProposalPendingAtTheObserverMastersStart"}
EXTRA = {"zk-adhoc-b4": "  jvm_properties: -Dzookeeper.enforceQuota=true\n  maven_profile: full-build"}


def study_scope():
    text = subprocess.run(["git", "-C", "/bulk/GraphChecker", "show",
                           "origin/system/zookeeper:experiments/zookeeper/zk-adhoc/checks.tsv"],
                          capture_output=True, text=True, check=True).stdout
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        out[f"zk-adhoc-{f[0]}"] = [s.split(":", 1)[1].replace("/", ".") for s in f[5:] if s.strip()]
    return out


def main():
    scopes = study_scope()
    (ROOT / "targets").mkdir(parents=True, exist_ok=True)
    cols = ["case", "gc_case", "gc_branch", "site_upstream", "method", "thrown", "guard", "workload", "workload_origin",
            "gc_workload", "module", "scope", "tree", "status"]
    with open(ROOT / "inventory.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for case, (gc, file, line, method, thrown, guard, workload, origin, module, scope) in ROWS.items():
            scope = scope or scopes[case]
            w.writerow([case, gc, "system/zookeeper", f"{S}/{file}:{line}", method, thrown, guard, workload, origin,
                        GC_WORKLOAD.get(case, workload), module, " ".join(scope), f"apache/zookeeper {BASE}", ""])
            q = '"' + guard.replace("\\", "\\\\").replace('"', '\\"') + '"'
            prof = " -Pfull-build" if case == "zk-adhoc-b4" else ""
            y = [f"id: {case}", "system: Apache ZooKeeper", "source_tree: /set/by/run-case.sh", f"base_commit: {BASE}",
                 "check:", f"  file: {S}/{file}", f"  line: {line}", f"  method: {method}", f"  thrown: {thrown}",
                 f"  guard: {q}", "workload:", f"  module: {module}", f"  test: {workload}",
                 "  note: the test reaches the check's method and passes; the check does not fail in it"]
            if case in EXTRA:
                y.append(EXTRA[case])
            y += ["scope_hint:"] + [f"  - {c}" for c in scope] + [
                  "build:", "  env: /set/by/run-case.sh",
                  f'  prepare: "mvn -B install -DskipTests -Dmaven.javadoc.skip=true -Pfull-build   (already done once)"',
                  f"  test_command: \"mvn -B -o surefire:test{prof} -pl {module} -Dtest='<Class>#<method>' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false\""]
            (ROOT / "targets" / f"{case}.yaml").write_text("\n".join(y) + "\n")


if __name__ == "__main__":
    main()
