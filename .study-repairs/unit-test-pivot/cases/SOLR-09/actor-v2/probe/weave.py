#!/usr/bin/env python3
"""Case-local source hooks with node and selected-reader identity."""

from pathlib import Path
import subprocess


CASE = Path(__file__).resolve().parents[1]
ROOT = CASE / "solr-source"
OUT = CASE / "probe/generated"


def prepare(relative: str, replacements: list[tuple[str, str]]) -> Path:
    source = (ROOT / relative).read_text()
    for before, after in replacements:
        count = source.count(before)
        if count != 1:
            raise RuntimeError(f"Expected one replacement in {relative}: {count} for {before!r}")
        source = source.replace(before, after)
    output = OUT / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source)
    return output


def main() -> None:
    command = prepare("solr/core/src/java/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.java", [
        ("    ShardHandler shardHandler = ocmh.shardHandlerFactory.getShardHandler(ocmh.overseer.getCoreContainer().getUpdateShardHandler().getDefaultHttpClient());",
         "    baseline.solr09.FeedbackProbe.bindTargetReader(ocmh.zkStateReader.getZkClient(), "
         "ocmh.overseer.getCoreContainer().getZkController().getNodeName(), "
         "replica.getNodeName(), replica.getCoreName());\n"
         "    ShardHandler shardHandler = ocmh.shardHandlerFactory.getShardHandler(ocmh.overseer.getCoreContainer().getUpdateShardHandler().getDefaultHttpClient());"),
        ("        if (!callable.call())\n          throw new SolrException(SolrException.ErrorCode.SERVER_ERROR,",
         "        boolean coreNodeGone = callable.call();\n"
         "        baseline.solr09.FeedbackProbe.targetCheck(!coreNodeGone, collectionName, shard, replicaName, core, isLive, "
         "ocmh.zkStateReader.getZkClient(), "
         "ocmh.overseer.getCoreContainer().getZkController().getNodeName());\n"
         "        if (!coreNodeGone)\n          throw new SolrException(SolrException.ErrorCode.SERVER_ERROR,"),
    ])
    io_source = "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    io = prepare(io_source, [
        ("  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"EXISTS_WATCH\", path, this);"),
        ("  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"EXISTS\", path, this);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"GET_CHILDREN\", path, this);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"GET_CHILDREN_STAT\", path, this);"),
        ("  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"GET_DATA\", path, this);"),
        ("  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"SET_DATA\", path, this);"),
    ])
    controller = prepare("solr/core/src/java/org/apache/solr/cloud/ZkController.java", [
        ("      }});\n\n\n    this.overseerRunningMap = Overseer.getRunningMap(zkClient);",
         "      }});\n"
         "    baseline.solr09.FeedbackProbe.registerNode(zkClient, nodeName);\n\n"
         "    this.overseerRunningMap = Overseer.getRunningMap(zkClient);"),
    ])
    http = prepare("solr/core/src/java/org/apache/solr/handler/component/ShardRequestor.java", [
        ("        ssr.nl = httpShardHandler.request(url, req);",
         "        baseline.solr09.FeedbackProbe.httpPost("
         "params.get(\"qt\"), params.get(\"action\"), params.get(\"core\"), "
         "sreq.nodeName, url);\n"
         "        ssr.nl = httpShardHandler.request(url, req);"),
    ])
    cp = (CASE / "classpath.txt").read_text().strip()
    subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
                    "-cp", cp, "-d", str(CASE / "classes"),
                    str(CASE / "probe/FeedbackProbe.java"),
                    str(command), str(io), str(controller), str(http)], check=True)


if __name__ == "__main__":
    main()
