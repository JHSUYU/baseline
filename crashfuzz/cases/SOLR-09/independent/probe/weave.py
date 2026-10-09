#!/usr/bin/env python3
"""Add case-local delete-replica target and ZooKeeper I/O hooks."""

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
    zk = prepare("solr/core/src/java/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.java", [
        ("        if (!callable.call())\n          throw new SolrException(SolrException.ErrorCode.SERVER_ERROR,",
         "        boolean coreNodeGone = callable.call();\n"
         "        baseline.solr09.FeedbackProbe.targetCheck(!coreNodeGone, collectionName, shard, replicaName, core, isLive);\n"
         "        if (!coreNodeGone)\n          throw new SolrException(SolrException.ErrorCode.SERVER_ERROR,"),
    ])
    io_source = "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    io = prepare(io_source, [
        ("  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"EXISTS_WATCH\", path);"),
        ("  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"EXISTS\", path);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"GET_CHILDREN\", path);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"GET_CHILDREN_STAT\", path);"),
        ("  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"GET_DATA\", path);"),
        ("  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr09.FeedbackProbe.io(\"SET_DATA\", path);"),
    ])
    cp = (CASE / "classpath.txt").read_text().strip()
    command = ["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac", "-cp", cp, "-d", str(CASE / "classes"),
               str(CASE / "probe/FeedbackProbe.java"), str(zk), str(io)]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
