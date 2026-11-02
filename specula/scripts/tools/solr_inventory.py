#!/usr/bin/env python3
"""Write solr/inventory.tsv and solr/targets/<case>.yaml (operator tool, B2).

Sites: the fork's markers (/bulk/wt/lucene-solr-checks) mapped to upstream apache/lucene-solr faca81bff1 (branch_8_11,
8.11.4) with find_sites.py, read by hand.  Workloads and scope: GraphChecker origin/system/solr-cloudlab
experiments/solr/solr-adhoc/checks.tsv; solr-adhoc-22 (GraphChecker's solr-18406, marker "solr-18406") from
experiments/solr/solr-18406/case.sh.
"""
import csv, re, subprocess
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc/solr")
BASE = "faca81bff1"
GCB = "origin/system/solr-cloudlab"
C = "solr/core/src/java/org/apache/solr"
SE = "org.apache.solr.common.SolrException"
REG = "ZkController.register(String, CoreDescriptor, boolean, boolean, boolean)"
FACTORY = "; the statement is `throw RoutedAlias.newAliasMustExistException(...)`, whose body throws this SolrException (SERVICE_UNAVAILABLE) at RoutedAlias.java:72"
ROWS = {
 "05": (f"{C}/cloud/ZkController.java", 1274, REG, SE,
        "replica == null   (replica = getReplicaOrNull(zkStateReader.getClusterState().getCollectionOrNull(collection), shardId, coreZkNodeName))"),
 "07": (f"{C}/cloud/ZkController.java", 1326, REG, SE,
        "core == null   (core = cc.getCore(desc.getName()), in try (SolrCore core = ...))"),
 "09": (f"{C}/cloud/api/collections/DeleteReplicaCmd.java", 278,
        "DeleteReplicaCmd.deleteCore(Slice, String, String, ZkNodeProps, String, NamedList, Runnable, boolean)", SE,
        "!callable.call()   (in if (!parallel); callable returns Boolean.FALSE when ocmh.waitForCoreNodeGone(collectionName, shard, replicaName, 30000) is false after ocmh.deleteCoreNode(collectionName, replicaName, replica, core))"),
 "10": (f"{C}/cloud/api/collections/MaintainRoutedAliasCmd.java", 117,
        "MaintainRoutedAliasCmd.call(ClusterState, ZkNodeProps, NamedList)", SE,
        "ra == null   (ra = RoutedAlias.fromProps(aliasName, aliasMetadata); aliasMetadata = ocmh.zkStateReader.aliasesManager.getAliases().getCollectionAliasProperties(aliasName), non-empty)"),
 "13": (f"{C}/cloud/api/collections/RoutedAlias.java", 350,
        "RoutedAlias.doSynchronous(AddUpdateCommand, CandidateCollection, CoreContainer)", SE,
        "!observedCols.contains(targetCollectionDesc.creationCollection)   (observedCols = zkController.zkStateReader.aliasesManager.getAliases().getCollectionAliasListMap().get(getAliasName()), after updateParsedCollectionAliases(zkController.zkStateReader, true))"),
 "14": (f"{C}/cloud/api/collections/SplitShardCmd.java", 167,
        "SplitShardCmd.split(ClusterState, ZkNodeProps, NamedList<Object>)", SE,
        "leaderZnodeStat == null   (leaderZnodeStat = zkStateReader.getZkClient().exists(ZkStateReader.LIVE_NODES_ZKNODE + \"/\" + parentShardLeader.getNodeName(), null, true))"),
 "19": (f"{C}/core/CoreContainer.java", 1330,
        "CoreContainer.create(String, Path, Map<String, String>, boolean)", SE,
        "getZkController() != null && !Overseer.isLegacy(getZkController().getZkStateReader()) && cd.getCloudDescriptor().getCoreNodeName() == null   (three nested ifs)"),
 "21": (f"{C}/core/CoreContainer.java", 1765,
        "CoreContainer.reload(String, UUID)", "java.lang.AssertionError",
        "assert replica != null;   (fails when replica == null; replica = docCollection.getReplica(cd.getCloudDescriptor().getCoreNodeName()), inside if (docCollection != null); a Java assert, active only with -ea)"),
 "22": (f"{C}/core/IndexDeletionPolicyWrapper.java", 177,
        "IndexDeletionPolicyWrapper.getAndSaveCommitPoint(Long)", "java.lang.IllegalStateException",
        "(null != commit && false != commit.isDeleted()) || (null == commit && null != latestCommit && generation < latestCommit.getGeneration())   (commit = knownCommits.get(generation))"),
 "31": (f"{C}/handler/admin/CollectionsHandler.java", 1477,
        "CollectionsHandler.forceLeaderElection(SolrQueryRequest, CollectionsHandler)", SE,
        "leader != null && leader.getState() == State.ACTIVE   (leader = slice.getLeader(); slice = zkController.getClusterState().getCollection(collectionName).getSlice(sliceId))"),
 "38": (f"{C}/update/processor/DistributedZkUpdateProcessor.java", 1023,
        "DistributedZkUpdateProcessor.doDefensiveChecks(DistribPhase)", SE,
        "(isLeader && !localIsLeader) || (isSubShardLeader && !localIsLeader)   (localIsLeader = cloudDesc.isLeader(), re-read up to 5 times, 500 ms apart, while the same condition holds)"),
 "39": (f"{C}/update/processor/RoutedAliasUpdateProcessor.java", 247,
        "RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections()", SE,
        "collections == null   (collections = zkController.getZkStateReader().getAliases().getCollectionAliasListMap().get(getAliasName()))" + FACTORY),
 "40": (f"{C}/update/processor/RoutedAliasUpdateProcessor.java", 133,
        "RoutedAliasUpdateProcessor.getAliasProps(SolrQueryRequest, String)", SE,
        "aliasProperties.isEmpty()   (aliasProperties = zkController.getZkStateReader().getAliases().getCollectionAliasProperties(aliasName))" + FACTORY
        + "; its caller RoutedAliasUpdateProcessor.wrap rethrows it as a SERVER_ERROR SolrException (line 122)"),
}
PORTED = {"22": "org.apache.solr.handler.TestAdhocWorkload22#run"}
GC_CASE = {"22": "solr-18406"}
# Ant finds Ivy only on its own classpath: -lib puts the case's Ivy jar there (-Divy_install_path alone does not;
# it works on these nodes only because ~/.ant/lib holds the same jar).
# The test security manager is off: Solr's test policy (solr/server/etc/security.policy) lets tests read only the
# tree and ~/.ivy2/cache, but solr/*/lib hold Ivy's symlinks into $IVY_USER_DIR/cache, so with it on Log4j finds no
# provider and every SolrTestCaseJ4 suite fails in setup (checked 2026-11-02 on AddReplicaTest).
# Extra test properties a workload needs to run at all: ForceLeaderTest is @Nightly upstream, and
# TimeRoutedAliasUpdateProcessorTest inherits @AwaitsFix from RoutedAliasUpdateProcessorTest, and its setup
# (createConfigSet: ConfigSets CREATE from the trusted _default, unauthenticated) is refused in 8.11.4 unless the
# test JVM sets Solr's back-compat switch solr.disableConfigSetsCreateAuthChecks (-Dargs keeps the default
# -XX:TieredStopAtLevel=1).
AF = " -Dtests.awaitsfix=true -Dargs='-XX:TieredStopAtLevel=1 -Dsolr.disableConfigSetsCreateAuthChecks=true'"
EXTRA = {"31": " -Dtests.nightly=true", "10": AF, "13": AF, "39": AF, "40": AF}
STATUS = {"22": "PORT_BLOCKED: the hold after the follower's file list needs IndexFetcher's test hook "
                "(assert testWait.getAsBoolean() after fetchFileList), which faca81bff1 lacks; see workloads/solr-adhoc-22.md"}


def gc_show(path):
    return subprocess.run(["git", "-C", "/bulk/GraphChecker", "show", f"{GCB}:{path}"],
                          capture_output=True, text=True, check=True).stdout


def scope_class(s):
    return s.split(":", 1)[1].replace("/", ".")


def main():
    tsv = {}
    for line in gc_show("experiments/solr/solr-adhoc/checks.tsv").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        tsv[f[0]] = (f"{f[1]}#{f[2]}", [scope_class(s) for s in f[5:] if s.strip()])
    case_sh = gc_show("experiments/solr/solr-18406/case.sh")
    cls = re.search(r"^test_class=(\S+)", case_sh, re.M).group(1)
    meth = re.search(r"^test_method=(\S+)", case_sh, re.M).group(1)
    scope = re.search(r"^scope=\((.*?)^\)", case_sh, re.M | re.S).group(1).split()
    tsv["22"] = (f"{cls}#{meth}", [scope_class(s) for s in scope])

    (ROOT / "targets").mkdir(parents=True, exist_ok=True)
    cols = ["case", "gc_case", "gc_branch", "site_upstream", "method", "thrown", "guard", "workload", "workload_origin",
            "gc_workload", "module", "scope", "tree", "status"]
    with open(ROOT / "inventory.tsv", "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for n, (file, line, method, thrown, guard) in ROWS.items():
            case = f"solr-adhoc-{n}"
            gcw, scope = tsv[n]
            wl = PORTED.get(n, gcw)
            w.writerow([case, GC_CASE.get(n, case), GCB.split("/", 1)[1], f"{file}:{line}", method, thrown, guard, wl,
                        "ported" if n in PORTED else "upstream", gcw, "solr/core", " ".join(scope),
                        f"apache/lucene-solr {BASE}", STATUS.get(n, "")])
            q = '"' + guard.replace("\\", "\\\\").replace('"', '\\"') + '"'
            tc = ("cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=<Class> -Dtests.method=<method> -Dtests.jvms=1"
                  + EXTRA.get(n, "") + " -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib")
            y = [f"id: {case}", "system: Apache Solr", "source_tree: /set/by/run-case.sh", f"base_commit: {BASE}", "check:",
                 f"  file: {file}", f"  line: {line}", f"  method: {method}", f"  thrown: {thrown}", f"  guard: {q}", "workload:",
                 "  module: solr/core", f"  test: {wl}",
                 "  note: the test reaches the check's method and passes; the check does not fail in it",
                 "scope_hint:"] + [f"  - {c}" for c in scope] + [
                 "build:", "  env: /set/by/run-case.sh",
                 '  prepare: "ant ivy-bootstrap -Divy_install_path=$IVY_USER_DIR/lib && cd solr && ant -lib $IVY_USER_DIR/lib compile compile-test -Divy_install_path=$IVY_USER_DIR/lib   (already done once)"',
                 f'  test_command: "{tc}"']
            (ROOT / "targets" / f"{case}.yaml").write_text("\n".join(y) + "\n")


if __name__ == "__main__":
    main()
