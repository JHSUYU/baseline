#!/usr/bin/env python3
"""Add case-local observation hooks to clean Solr 8.11.4 Java sources."""

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
    maintain = prepare("solr/core/src/java/org/apache/solr/cloud/api/collections/MaintainRoutedAliasCmd.java", [
        ("    if (ra == null) {\n      throw new SolrException(SolrException.ErrorCode.SERVER_ERROR, \"MaintainRoutedAlias called on non-routed alias\");",
         "    baseline.solr103940.FeedbackProbe.targetCheck(ra == null, \"SOLR-10\", aliasName, routeValue);\n    if (ra == null) {\n      throw new SolrException(SolrException.ErrorCode.SERVER_ERROR, \"MaintainRoutedAlias called on non-routed alias\");"),
    ])
    route = prepare("solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java", [
        ("    if (aliasProperties.isEmpty()) {\n      throw RoutedAlias.newAliasMustExistException(aliasName);",
         "    baseline.solr103940.FeedbackProbe.targetCheck(aliasProperties.isEmpty(), \"SOLR-40\", aliasName, \"getAliasProps\");\n    if (aliasProperties.isEmpty()) {\n      throw RoutedAlias.newAliasMustExistException(aliasName);"),
        ("    if (collections == null) {\n      throw RoutedAlias.newAliasMustExistException(getAliasName());",
         "    baseline.solr103940.FeedbackProbe.targetCheck(collections == null, \"SOLR-39\", getAliasName(), \"lookupShardLeadersOfCollections\");\n    if (collections == null) {\n      throw RoutedAlias.newAliasMustExistException(getAliasName());"),
    ])
    io_source = "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    io = prepare(io_source, [
        ("  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"EXISTS_WATCH\", path);"),
        ("  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"EXISTS\", path);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"GET_CHILDREN\", path);"),
        ("  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"GET_CHILDREN_STAT\", path);"),
        ("  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"GET_DATA\", path);"),
        ("  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {",
         "  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {\n    baseline.solr103940.FeedbackProbe.io(\"SET_DATA\", path);"),
    ])
    cp = (CASE / "instrumented-classpath.txt").read_text().strip()
    command = ["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac", "-cp", cp, "-d", str(CASE / "classes-probe"),
               str(CASE / "probe/FeedbackProbe.java"), str(maintain), str(route), str(io)]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
