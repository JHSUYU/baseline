#!/usr/bin/env python3
"""Compile SOLR-05 actor/context hooks from clean Solr 8.11.4 sources."""

from pathlib import Path
import subprocess

CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "solr-source"
OUT = CASE / "generated"
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"


def prepare(relative: str, replacements: list[tuple[str, str]]) -> Path:
    source = (SOURCE / relative).read_text()
    for before, after in replacements:
        count = source.count(before)
        if count != 1:
            raise RuntimeError(f"Expected one match in {relative}, got {count}: {before!r}")
        source = source.replace(before, after)
    path = OUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def main() -> None:
    controller = prepare("solr/core/src/java/org/apache/solr/cloud/ZkController.java", [
        ("    zkStateReader = new ZkStateReader(zkClient, () -> {\n      if (cc != null) cc.securityNodeChanged();\n    });",
         "    zkStateReader = new ZkStateReader(zkClient, () -> {\n      if (cc != null) cc.securityNodeChanged();\n    });\n"
         "    baseline.solr05v2.FeedbackProbe.registerNode(zkClient, zkStateReader, nodeName);"),
        ("    MDCLoggingContext.setCoreDescriptor(cc, desc);\n    try {\n      // pre register has published our down state",
         "    MDCLoggingContext.setCoreDescriptor(cc, desc);\n"
         "    baseline.solr05v2.FeedbackProbe.enterRegister(zkClient, zkStateReader, nodeName, "
         "desc.getCloudDescriptor().getCollectionName(), desc.getCloudDescriptor().getShardId(), "
         "desc.getCloudDescriptor().getCoreNodeName(), coreName);\n"
         "    try {\n      // pre register has published our down state"),
        ("      Replica replica = getReplicaOrNull(zkStateReader.getClusterState().getCollectionOrNull(collection), shardId, coreZkNodeName);\n      if (replica == null) {",
         "      Replica replica = getReplicaOrNull(zkStateReader.getClusterState().getCollectionOrNull(collection), shardId, coreZkNodeName);\n"
         "      baseline.solr05v2.FeedbackProbe.targetCheck(replica == null, collection, shardId, "
         "coreZkNodeName, coreName, zkClient, zkStateReader, nodeName);\n"
         "      if (replica == null) {"),
        ("      return shardId;\n    } finally {\n      MDCLoggingContext.clear();\n    }\n  }\n\n  private Replica getReplicaOrNull",
         "      return shardId;\n    } finally {\n"
         "      baseline.solr05v2.FeedbackProbe.exitRegister(zkClient, coreName);\n"
         "      MDCLoggingContext.clear();\n    }\n  }\n\n  private Replica getReplicaOrNull"),
    ])
    io = prepare("solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java", [
        ("  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr05v2.FeedbackProbe.io(\"EXISTS_WATCH\", path, this);"),
        ("  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr05v2.FeedbackProbe.io(\"EXISTS\", path, this);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr05v2.FeedbackProbe.io(\"GET_CHILDREN\", path, this);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr05v2.FeedbackProbe.io(\"GET_CHILDREN_STAT\", path, this);"),
        ("  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr05v2.FeedbackProbe.io(\"GET_DATA\", path, this);"),
        ("  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr05v2.FeedbackProbe.io(\"SET_DATA\", path, this);"),
    ])
    cluster = prepare("solr/test-framework/src/java/org/apache/solr/cloud/MiniSolrCloudCluster.java", [
        ("    jetty.start();\n    jettys.add(jetty);\n    return jetty;",
         "    jetty.start();\n"
         "    baseline.solr05v2.FeedbackProbe.registerJettyRole(name, jetty.getNodeName());\n"
         "    jettys.add(jetty);\n    return jetty;"),
    ])
    cp = (CASE / "classpath.txt").read_text().strip()
    subprocess.run([JAVAC, "-cp", cp, "-d", str(CASE / "classes"),
                    str(CASE / "probe/FeedbackProbe.java"), str(controller), str(io),
                    str(cluster)], check=True)


if __name__ == "__main__":
    main()
