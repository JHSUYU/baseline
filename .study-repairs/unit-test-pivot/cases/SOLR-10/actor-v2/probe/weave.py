#!/usr/bin/env python3
"""Compile observation-only hooks against clean Solr 8.11.4 source."""

from pathlib import Path
import subprocess


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "work/solr-source"
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
    maintain = prepare("solr/core/src/java/org/apache/solr/cloud/api/collections/MaintainRoutedAliasCmd.java", [
        ("    if (ra == null) {\n      throw new SolrException(SolrException.ErrorCode.SERVER_ERROR, \"MaintainRoutedAlias called on non-routed alias\");",
         "    baseline.solr103940.FeedbackProbe.targetCheck(ra == null, \"SOLR-10\", aliasName, routeValue, "
         "ocmh.zkStateReader.getZkClient(), aliasesManager, "
         "ocmh.overseer.getCoreContainer().getZkController().getNodeName());\n"
         "    if (ra == null) {\n      throw new SolrException(SolrException.ErrorCode.SERVER_ERROR, \"MaintainRoutedAlias called on non-routed alias\");"),
    ])
    route = prepare("solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java", [
        ("    if (aliasProperties.isEmpty()) {\n      throw RoutedAlias.newAliasMustExistException(aliasName);",
         "    baseline.solr103940.FeedbackProbe.targetCheck(aliasProperties.isEmpty(), \"SOLR-40\", "
         "aliasName, req.getCore().getName(), zkController.getZkStateReader().getZkClient(), "
         "zkController.getZkStateReader().aliasesManager, zkController.getNodeName());\n"
         "    if (aliasProperties.isEmpty()) {\n      throw RoutedAlias.newAliasMustExistException(aliasName);"),
        ("    if (collections == null) {\n      throw RoutedAlias.newAliasMustExistException(getAliasName());",
         "    baseline.solr103940.FeedbackProbe.targetCheck(collections == null, \"SOLR-39\", "
         "getAliasName(), req.getCore().getName(), zkController.getZkStateReader().getZkClient(), "
         "zkController.getZkStateReader().aliasesManager, zkController.getNodeName());\n"
         "    if (collections == null) {\n      throw RoutedAlias.newAliasMustExistException(getAliasName());"),
    ])
    io = prepare("solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java", [
        ("  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"EXISTS_WATCH\", path, this);"),
        ("  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"EXISTS\", path, this);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"GET_CHILDREN\", path, this);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"GET_CHILDREN_STAT\", path, this);"),
        ("  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"GET_DATA\", path, this);"),
        ("  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"SET_DATA\", path, this);"),
    ])
    controller = prepare("solr/core/src/java/org/apache/solr/cloud/ZkController.java", [
        ("    zkStateReader = new ZkStateReader(zkClient, () -> {\n      if (cc != null) cc.securityNodeChanged();\n    });",
         "    zkStateReader = new ZkStateReader(zkClient, () -> {\n      if (cc != null) cc.securityNodeChanged();\n    });\n"
         "    baseline.solr103940.FeedbackProbe.registerNode(zkClient, zkStateReader.aliasesManager, nodeName);"),
    ])
    cluster = prepare("solr/test-framework/src/java/org/apache/solr/cloud/MiniSolrCloudCluster.java", [
        ("    jetty.start();\n    jettys.add(jetty);\n    return jetty;",
         "    jetty.start();\n"
         "    baseline.solr103940.FeedbackProbe.registerJettyRole(name, jetty.getNodeName());\n"
         "    jettys.add(jetty);\n    return jetty;"),
    ])
    cp = (CASE / "classpath.txt").read_text().strip()
    subprocess.run([JAVAC, "-cp", cp, "-d", str(CASE / "classes"),
                    str(CASE / "probe/FeedbackProbe.java"), str(maintain), str(route),
                    str(io), str(controller), str(cluster)], check=True)


if __name__ == "__main__":
    main()
