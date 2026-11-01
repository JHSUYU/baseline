#!/usr/bin/env python3
"""Write hdfs/inventory.tsv and hdfs/targets/<case>.yaml (operator tool, B2).

Sites were read by hand: the fork's marked throw (/bulk/wt/hadoop-hdfs-study-r7, find_sites.py)
mapped to the same statement at upstream 734dd8a67cd.  Workloads and scope come from
GraphChecker origin/system/hdfs-cloudlab experiments/hadoop/hdfs-adhoc/checks.tsv.
"""
import csv, subprocess
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc/hdfs")
BASE = "734dd8a67cd"
H = "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs"
P = "org.apache.hadoop.hdfs"
IOE, AE, ISE, IAE = "java.io.IOException", "java.lang.AssertionError", "java.lang.IllegalStateException", "java.lang.IllegalArgumentException"
INV_TOKEN = "org.apache.hadoop.security.token.SecretManager.InvalidToken"
INCONS = "org.apache.hadoop.hdfs.server.common.InconsistentFSStateException"
SNAP = "org.apache.hadoop.hdfs.protocol.SnapshotException"
TRANS = "(StorageDirectory, NamespaceInfo, StartupOption, List<Callable<StorageDirectory>>, Configuration)"
APPEND = "FSDirAppendOp.appendFile(FSNamesystem, String, FSPermissionChecker, String, String, boolean, boolean)"

# case: (fork site, upstream file, upstream line, method, thrown, guard as written upstream)
SITES = {
 "05": ("qjournal/client/QuorumOutputStream.java:108", "qjournal/client/QuorumOutputStream.java", 106, "QuorumOutputStream.flushAndSync(boolean)", AE, "assert bufToSend.getLength() == numReadyBytes;"),
 "06": ("qjournal/client/QuorumOutputStream.java:112", "qjournal/client/QuorumOutputStream.java", 108, "QuorumOutputStream.flushAndSync(boolean)", AE, "assert data.length == bufToSend.getLength();"),
 "07": ("qjournal/server/Journal.java:930", "qjournal/server/Journal.java", 926, "Journal.acceptRecovery(RequestInfo, SegmentStateProto, URL)", AE, "txnRange(currentSegment).contains(committedTxnId.get()) && !txnRange(segment).contains(committedTxnId.get())"),
 "08": ("qjournal/server/Journal.java:488", "qjournal/server/Journal.java", 487, "Journal.checkRequest(RequestInfo)", IOE, "reqInfo.getEpoch() < lastPromisedEpoch.get()"),
 "09": ("qjournal/server/Journal.java:507", "qjournal/server/Journal.java", 504, "Journal.checkRequest(RequestInfo)", IAE, "if (reqInfo.hasCommittedTxId()) { Preconditions.checkArgument(reqInfo.getCommittedTxId() >= committedTxnId.get(), ...); }   (fails when the condition is false)"),
 "10": ("qjournal/server/Journal.java:521", "qjournal/server/Journal.java", 518, "Journal.checkWriteRequest(RequestInfo)", IOE, "reqInfo.getEpoch() != lastWriterEpoch.get()"),
 "11": ("security/token/block/BlockTokenSecretManager.java:584", "security/token/block/BlockTokenSecretManager.java", 559, "BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])", "org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException", "key == null   (key = allKeys.get(keyId))"),
 "12": ("security/token/block/BlockTokenSecretManager.java:542", "security/token/block/BlockTokenSecretManager.java", 518, "BlockTokenSecretManager.retrievePassword(BlockTokenIdentifier)", INV_TOKEN, "key == null   (key = allKeys.get(identifier.getKeyId()))"),
 "14": ("security/token/block/BlockTokenSecretManager.java:441", "security/token/block/BlockTokenSecretManager.java", 418, "BlockTokenSecretManager.checkAccess(Token<BlockTokenIdentifier>, String, ExtendedBlock, BlockTokenIdentifier.AccessMode, StorageType[], String[])", INV_TOKEN, "!MessageDigest.isEqual(retrievePassword(id), token.getPassword())"),
 "15": ("server/blockmanagement/BlockInfo.java:450", "server/blockmanagement/BlockInfo.java", 447, "BlockInfo.commitBlock(Block)", ISE, "Preconditions.checkState(!isComplete());   (fails when the block is complete)"),
 "16": ("server/blockmanagement/BlockInfo.java:429", "server/blockmanagement/BlockInfo.java", 428, "BlockInfo.setGenerationStampAndVerifyReplicas(long)", ISE, "Preconditions.checkState(uc != null && !isComplete());   (fails when the condition is false)"),
 "19": ("server/datanode/BPOfferService.java:781", "server/datanode/BPOfferService.java", 777, "BPOfferService.processCommandFromActive(DatanodeCommand, InetSocketAddress)", AE, "case DNA_FINALIZE: assert getBlockPoolId().equals(bp);   (bp = ((FinalizeCommand) cmd).getBlockPoolId())"),
 "20": ("server/datanode/BPOfferService.java:617", "server/datanode/BPOfferService.java", 615, "BPOfferService.updateActorStatesFromHeartbeat(BPServiceActor, NNHAStatusHeartbeat)", AE, "if (bpServiceToActive == actor) { assert txid >= lastActiveClaimTxId; }"),
 "21": ("server/datanode/BPServiceActor.java:293", "server/datanode/BPServiceActor.java", 289, "BPServiceActor.checkNNVersion(NamespaceInfo)", "org.apache.hadoop.hdfs.server.common.IncorrectVersionException", "VersionUtil.compareVersions(nnVersion, minimumNameNodeVersion) < 0   (the exception is created at this line and thrown at line 292)"),
 "22": ("server/datanode/BlockPoolSliceStorage.java:395", "server/datanode/BlockPoolSliceStorage.java", 393, "BlockPoolSliceStorage.doTransition" + TRANS, IOE, "getNamespaceID() != nsInfo.getNamespaceID()"),
 "23": ("server/datanode/BlockPoolSliceStorage.java:402", "server/datanode/BlockPoolSliceStorage.java", 399, "BlockPoolSliceStorage.doTransition" + TRANS, IOE, "!blockpoolID.equals(nsInfo.getBlockPoolID())"),
 "24": ("server/datanode/BlockPoolSliceStorage.java:425", "server/datanode/BlockPoolSliceStorage.java", 421, "BlockPoolSliceStorage.doTransition" + TRANS, IOE, "reached when neither earlier return is taken: !(this.layoutVersion == DataNodeLayoutVersion.getCurrentLayoutVersion() && this.cTime == nsInfo.getCTime()) && !(this.layoutVersion > DataNodeLayoutVersion.getCurrentLayoutVersion() || this.cTime < nsInfo.getCTime())"),
 "25": ("server/datanode/BlockPoolSliceStorage.java:186", "server/datanode/BlockPoolSliceStorage.java", 185, "BlockPoolSliceStorage.loadStorageDirectory(NamespaceInfo, StorageLocation, StartupOption, List<Callable<StorageDirectory>>, Configuration)", IOE, "!doTransition(sd, nsInfo, startOpt, callables, conf) && getCTime() != nsInfo.getCTime()"),
 "26": ("server/datanode/BlockPoolSliceStorage.java:628", "server/datanode/BlockPoolSliceStorage.java", 621, "BlockPoolSliceStorage.doRollback(StorageDirectory, NamespaceInfo)", INCONS, "!(prevInfo.getLayoutVersion() >= DataNodeLayoutVersion.getCurrentLayoutVersion() && prevInfo.getCTime() <= nsInfo.getCTime())"),
 "27": ("server/datanode/BlockPoolSliceStorage.java:516", "server/datanode/BlockPoolSliceStorage.java", 510, "BlockPoolSliceStorage.doUpgrade(String, StorageDirectory, NamespaceInfo, File, File, File, int, Configuration)", AE, "assert this.namespaceID == nsInfo.getNamespaceID();"),
 "28": ("server/datanode/BlockRecoveryWorker.java:566", "server/datanode/BlockRecoveryWorker.java", 565, "BlockRecoveryWorker.getDatanodeID(String)", IOE, "bpos == null   (bpos = datanode.getBPOfferService(bpid))"),
 "29": ("server/datanode/BlockRecoveryWorker.java:606", "server/datanode/BlockRecoveryWorker.java", 604, "BlockRecoveryWorker.getActiveNamenodeForBP(String)", IOE, "bpos == null   (bpos = datanode.getBPOfferService(bpid))"),
 "30": ("server/datanode/BlockRecoveryWorker.java:611", "server/datanode/BlockRecoveryWorker.java", 609, "BlockRecoveryWorker.getActiveNamenodeForBP(String)", IOE, "activeNN == null   (activeNN = bpos.getActiveNN())"),
 "31": ("server/datanode/DataNode.java:1839", "server/datanode/DataNode.java", 1838, "DataNode.getBPOSForBlock(ExtendedBlock)", IOE, "bpos == null   (bpos = blockPoolManager.get(block.getBlockPoolId()))"),
 "33": ("server/datanode/DataStorage.java:261", "server/datanode/DataStorage.java", 259, "DataStorage.VolumeBuilder.build()", AE, "assert bpStorage != null;   (bpStorage = this.storage.bpStorageMap.get(bpid))"),
 "34": ("server/datanode/DataStorage.java:744", "server/datanode/DataStorage.java", 741, "DataStorage.doTransition" + TRANS, IOE, "!federationSupported && getNamespaceID() != nsInfo.getNamespaceID()"),
 "35": ("server/datanode/DataStorage.java:754", "server/datanode/DataStorage.java", 750, "DataStorage.doTransition" + TRANS, IOE, "federationSupported && !getClusterID().equals(nsInfo.getClusterID())"),
 "37": ("server/datanode/DataStorage.java:947", "server/datanode/DataStorage.java", 942, "DataStorage.doRollback(StorageDirectory, NamespaceInfo)", INCONS, "!(prevInfo.getLayoutVersion() >= DataNodeLayoutVersion.getCurrentLayoutVersion() && prevInfo.getCTime() <= nsInfo.getCTime())"),
 "38": ("server/namenode/FSDirAppendOp.java:123", "server/namenode/FSDirAppendOp.java", 122, APPEND, "java.lang.UnsupportedOperationException", "lpPolicy != null && lpPolicy.getId() == file.getStoragePolicyID()"),
 "39": ("server/namenode/FSDirAppendOp.java:134", "server/namenode/FSDirAppendOp.java", 133, APPEND, "org.apache.hadoop.ipc.RetriableException", "lastBlock != null && lastBlock.getBlockUCState() == BlockUCState.COMMITTED"),
 "40": ("server/namenode/FSDirAppendOp.java:140", "server/namenode/FSDirAppendOp.java", 139, APPEND, IOE, "lastBlock != null && lastBlock.getBlockUCState() != BlockUCState.COMMITTED && lastBlock.isComplete() && !blockManager.isSufficientlyReplicated(lastBlock)"),
 "45": ("server/namenode/FSEditLog.java:1471", "server/namenode/FSEditLog.java", 1469, "FSEditLog.endCurrentLogSegment(boolean)", ISE, "Preconditions.checkState(isSegmentOpen(), \"Bad state: %s\", state);   (fails when no segment is open)"),
 "48": ("server/namenode/INodeDirectory.java:360", "server/namenode/INodeDirectory.java", 356, "INodeDirectory.replaceChild(INode, INode, INodeMap)", ISE, "Preconditions.checkState(oldChild == children.get(i) || oldChild == children.get(i).asReference().getReferredINode().asReference().getReferredINode());   (fails when the condition is false)"),
 "49": ("server/namenode/snapshot/DirectorySnapshottableFeature.java:190", "server/namenode/snapshot/DirectorySnapshottableFeature.java", 189, "DirectorySnapshottableFeature.addSnapshot(INodeDirectory, SnapshotManager, String, LeaseManager, long)", SNAP, "n + 1 > snapshotQuota   (n = getNumSnapshots())"),
 "50": ("server/namenode/snapshot/DirectorySnapshottableFeature.java:200", "server/namenode/snapshot/DirectorySnapshottableFeature.java", 198, "DirectorySnapshottableFeature.addSnapshot(INodeDirectory, SnapshotManager, String, LeaseManager, long)", SNAP, "i >= 0   (i = searchSnapshot(nameBytes): a snapshot with the same name exists)"),
 "52": ("server/namenode/snapshot/FSImageFormatPBSnapshot.java:468", "server/namenode/snapshot/FSImageFormatPBSnapshot.java", 466, "FSImageFormatPBSnapshot.Saver.serializeSnapshotSection(OutputStream)", ISE, "Preconditions.checkState(i == sm.getNumSnapshots());   (fails when the count of serialized snapshots differs)"),
}

PORTED = {"12": ("org.apache.hadoop.hdfs.server.datanode.TestAdhocWorkload12", "run")}


def checks_tsv():
    text = subprocess.run(["git", "-C", "/bulk/GraphChecker", "show",
                           "origin/system/hdfs-cloudlab:experiments/hadoop/hdfs-adhoc/checks.tsv"],
                          capture_output=True, text=True, check=True).stdout
    rows = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        scope = []
        for s in f[5:]:
            s = s.strip()
            if not s:
                continue
            cls = s.split(":", 1)[1].replace("/", ".")
            if cls not in scope:
                scope.append(cls)
        rows[f[0]] = (f[1], f[2], scope)
    return rows


def main():
    rows = checks_tsv()
    assert sorted(rows) == sorted(SITES), set(rows) ^ set(SITES)
    (ROOT / "targets").mkdir(parents=True, exist_ok=True)
    cols = ["case", "gc_case", "gc_branch", "site_fork", "site_upstream", "method", "thrown", "guard",
            "workload", "workload_origin", "gc_workload", "scope", "tree", "status"]
    with open(ROOT / "inventory.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for n in sorted(SITES):
            case = f"hdfs-adhoc-{n}"
            fork_site, ufile, uline, method, thrown, guard = SITES[n]
            tclass, tmethod, scope = rows[n]
            gc_workload = f"{tclass}#{tmethod}"
            if n in PORTED:
                workload, origin = "#".join(PORTED[n]), "ported"
            else:
                workload, origin = gc_workload, "upstream"
            w.writerow([case, case, "system/hdfs-cloudlab", f"{H}/{fork_site}", f"{H}/{ufile}:{uline}", method,
                        thrown, guard, workload, origin, gc_workload, " ".join(scope),
                        f"apache/hadoop {BASE}" + (" (hdfs-adhoc-21: GraphChecker ran its own tree hadoop-hdfs-21; Specula uses upstream)" if n == "21" else ""),
                        ""])
            q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
            y = [f"id: {case}", "system: Apache Hadoop HDFS", "source_tree: /set/by/run-case.sh",
                 f"base_commit: {BASE}", "check:", f"  file: {H}/{ufile}", f"  line: {uline}",
                 f"  method: {method}", f"  thrown: {thrown}", f"  guard: {q(guard)}", "workload:",
                 "  module: hadoop-hdfs-project/hadoop-hdfs", f"  test: {workload}",
                 "  note: the test reaches the check's method and passes; the check does not fail in it",
                 "scope_hint:"] + [f"  - {c}" for c in scope] + [
                 "build:", "  env: /set/by/run-case.sh",
                 '  prepare: "mvn -B install -DskipTests -Dmaven.javadoc.skip=true -pl hadoop-hdfs-project/hadoop-hdfs -am   (already done once)"',
                 "  test_command: \"mvn -B -o surefire:test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='<Class>#<method>' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false\""]
            (ROOT / "targets" / f"{case}.yaml").write_text("\n".join(y) + "\n")


if __name__ == "__main__":
    main()
