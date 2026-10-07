#!/usr/bin/env python3
"""Compile independent source-level observation hooks; leave Solr sources untouched."""

from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
SOURCE = CASE / "solr-source"
GENERATED = HERE / "generated"
CLASSES = HERE / "classes"


def patched(relative: str, replacements: list[tuple[str, str]]) -> Path:
    original = (SOURCE / relative).read_text()
    for before, after in replacements:
        count = original.count(before)
        if count != 1:
            raise RuntimeError(f"{relative}: anchor count {count} for {before!r}")
        original = original.replace(before, after)
    destination = GENERATED / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(original)
    return destination


def main() -> None:
    java = "solr/core/src/java/org/apache/solr/"
    sources = [HERE / "ActorProbe.java"]
    sources.append(patched(java + "cloud/api/collections/CreateCollectionCmd.java", [
        ("          sreq.params.set(CoreAdminParams.CORE_NODE_NAME, replicas.get(e.getKey()).getName());\n"
         "          shardHandler.submit(sreq, sreq.shards[0], sreq.params);",
         "          sreq.params.set(CoreAdminParams.CORE_NODE_NAME, replicas.get(e.getKey()).getName());\n"
         "          baseline.solr19v2.ActorProbe.sender(\"CREATE_COLLECTION\", sreq.params, sreq.nodeName, sreq.shards[0]);\n"
         "          shardHandler.submit(sreq, sreq.shards[0], sreq.params);"),
    ]))
    sources.append(patched(java + "cloud/api/collections/AddReplicaCmd.java", [
        ("      shardRequestTracker.sendShardRequest(createReplica.node, params, shardHandler);",
         "      baseline.solr19v2.ActorProbe.sender(\"ADD_REPLICA\", params, createReplica.node, "
         "zkStateReader.getBaseUrlForNodeName(createReplica.node));\n"
         "      shardRequestTracker.sendShardRequest(createReplica.node, params, shardHandler);"),
    ]))
    sources.append(patched(java + "handler/admin/CoreAdminOperation.java", [
        ("    CoreContainer coreContainer = it.handler.coreContainer;\n    Path instancePath;",
         "    CoreContainer coreContainer = it.handler.coreContainer;\n"
         "    baseline.solr19v2.ActorProbe.receiver(params, coreParams, "
         "coreContainer.getZkController() == null ? \"NONCLOUD\" : coreContainer.getZkController().getNodeName());\n"
         "    Path instancePath;"),
    ]))
    sources.append(patched(java + "core/CoreDescriptor.java", [
        ("    loadExtraProperties();\n    buildSubstitutableProperties();",
         "    baseline.solr19v2.ActorProbe.descriptor(\"BEFORE_FILE\", name, instanceDir, "
         "coreProps.get(CORE_NODE_NAME), coreProperties.getProperty(CORE_NODE_NAME));\n"
         "    loadExtraProperties();\n"
         "    baseline.solr19v2.ActorProbe.descriptor(\"AFTER_FILE\", name, instanceDir, "
         "coreProps.get(CORE_NODE_NAME), coreProperties.getProperty(CORE_NODE_NAME));\n"
         "    buildSubstitutableProperties();"),
        ("    if (Files.exists(propertiesFile)) {",
         "    boolean baselineSolr19FileExists = Files.exists(propertiesFile);\n"
         "    baseline.solr19v2.ActorProbe.file(coreProperties.getProperty(CORE_NAME), "
         "propertiesFile, baselineSolr19FileExists, coreProperties.getProperty(CORE_NODE_NAME));\n"
         "    if (baselineSolr19FileExists) {"),
        ("      try (InputStream is = Files.newInputStream(propertiesFile)) {",
         "      baseline.solr19v2.ActorProbe.fileOpen(coreProperties.getProperty(CORE_NAME), propertiesFile);\n"
         "      try (InputStream is = Files.newInputStream(propertiesFile)) {"),
    ]))
    sources.append(patched(java + "core/CoreContainer.java", [
        ("          if (cd.getCloudDescriptor().getCoreNodeName() == null) {\n"
         "            throw new SolrException(ErrorCode.SERVER_ERROR, \"non legacy mode coreNodeName missing \" + parameters.toString());",
         "          baseline.solr19v2.ActorProbe.target(coreName, getZkController().getNodeName(), "
         "instancePath, parameters.get(CoreDescriptor.CORE_NODE_NAME), "
         "cd.getCloudDescriptor().getCoreNodeName(), cd.getCloudDescriptor().getCoreNodeName() == null);\n"
         "          if (cd.getCloudDescriptor().getCoreNodeName() == null) {\n"
         "            throw new SolrException(ErrorCode.SERVER_ERROR, \"non legacy mode coreNodeName missing \" + parameters.toString());"),
    ]))
    sources.append(patched(java + "cloud/ZkController.java", [
        ("    this.overseerRunningMap = Overseer.getRunningMap(zkClient);",
         "    baseline.solr19v2.ActorProbe.bindZkClient(zkClient, nodeName, zkServerAddress);\n"
         "    this.overseerRunningMap = Overseer.getRunningMap(zkClient);"),
    ]))
    io_source = "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    io_methods = [
        ("EXISTS_WATCH", "  public Stat exists(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {"),
        ("EXISTS", "  public Boolean exists(final String path, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {"),
        ("GET_CHILDREN", "  public List<String> getChildren(final String path, final Watcher watcher, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {"),
        ("GET_CHILDREN_STAT", "  public List<String> getChildren(final String path, final Watcher watcher,Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {"),
        ("GET_DATA", "  public byte[] getData(final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {"),
        ("SET_DATA", "  public Stat setData(final String path, final byte data[], final int version, boolean retryOnConnLoss)\n      throws KeeperException, InterruptedException {"),
    ]
    sources.append(patched(io_source, [
        (anchor, anchor + "\n    baseline.solr19v2.ActorProbe.io(\"" + operation + "\", path, getZkServerAddress(), this);")
        for operation, anchor in io_methods
    ]))
    CLASSES.mkdir(parents=True, exist_ok=True)
    cp = (CASE / "original-classpath.txt").read_text().strip()
    command = ["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac", "-cp", cp,
               "-d", str(CLASSES)] + [str(source) for source in sources]
    subprocess.run(command, check=True)
    print("compiled", len(sources) - 1, "source overlays into", CLASSES)


if __name__ == "__main__":
    main()
