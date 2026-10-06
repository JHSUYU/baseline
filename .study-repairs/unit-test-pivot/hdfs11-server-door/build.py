"""Add one real server-side SASL read fault door in an isolated HDFS-11 scope.

The GraphChecker core jar and Hadoop jars remain unchanged.  The extra
library-catalog row is served from a classpath resource overlay for this run.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
PIVOT = HERE.parent
GRAPH = Path("/users/ZhenyuLi/.graphchecker-builds/unit-test-core-0889fb01f-fea8c862bb5c.jar")
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
SCOPE = PIVOT / "hdfs11-param-expanded/scope"
CATALOG_NAME = "edu/uva/liftlab/graphchecker/library-catalog.jsonl"
CATALOG = HERE / "catalog-overlay" / CATALOG_NAME
STATIC = HERE / "static"
WOVEN = HERE / "instrumented"
LINEAGE = HERE / "lineage"
TARGET = HERE / "target.yaml"

SERVER_READ = {
    "schemaVersion": 1, "kind": "DOOR", "transport": "HDFS_SASL",
    "direction": "SERVER_READ",
    "method": "<org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferServer: "
              "org.apache.hadoop.hdfs.protocol.datatransfer.IOStreamPair "
              "doSaslHandshake(org.apache.hadoop.hdfs.net.Peer,java.io.OutputStream,"
              "java.io.InputStream,java.util.Map,javax.security.auth.callback.CallbackHandler)>",
    "before": "<org.apache.hadoop.hdfs.protocol.datatransfer.sasl.DataTransferSaslUtil: "
              "org.apache.hadoop.hdfs.protocol.datatransfer.sasl."
              "DataTransferSaslUtil$SaslMessageWithHandshake "
              "readSaslMessageWithHandshakeSecret(java.io.InputStream)>",
    "faults": ["java.io.EOFException", "java.net.SocketTimeoutException"],
}


def run(command, log, timeout=180):
    before = time.monotonic()
    with log.open("w") as stream:
        try:
            exit_code = subprocess.run(command, stdout=stream,
                                       stderr=subprocess.STDOUT,
                                       timeout=timeout, check=False).returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    return {"exit": exit_code, "seconds": round(time.monotonic()-before, 3),
            "log": str(log)}


def main():
    HERE.mkdir(exist_ok=True)
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(GRAPH) as archive:
        base = archive.read(CATALOG_NAME).decode()
    CATALOG.write_text(base.rstrip() + "\n" + json.dumps(SERVER_READ) + "\n")
    TARGET.write_text("exception_target: hdfs-adhoc-11 "
                      "org.apache.hadoop.hdfs.security.token.block."
                      "BlockTokenSecretManager 553 InvalidEncryptionKeyException\n")
    with ZipFile(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar") as archive:
        for name in archive.namelist():
            if name.endswith(".class"):
                destination = LINEAGE / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
    jars = sorted((HADOOP / "share/hadoop").rglob("*.jar"))
    cp = os.pathsep.join(str(path) for path in jars)
    graph_cp = os.pathsep.join((str(CATALOG.parents[4]), str(GRAPH), cp))
    if STATIC.exists(): shutil.rmtree(STATIC)
    STATIC.mkdir()
    seed = [str(JDK / "java"), "-Xmx4g",
            "-Dcausynth.output.dir=" + str(STATIC),
            "-Dcausynth.target.spec=" + str(TARGET),
            "-Dcausynth.lineage.roots=" + str(LINEAGE),
            "-Dcausynth.loop.default.bound=8",
            "-cp", graph_cp,
            "edu.uva.liftlab.graphchecker.GraphCheckerMain",
            "-i", str(SCOPE), "-x", cp, "-o", str(HERE / "seed-output")]
    manifest = {"catalogDoor": SERVER_READ, "scopeClassFiles":
                len(list(SCOPE.rglob("*.class"))), "classpathJars": len(jars),
                "graphJar": str(GRAPH), "seed": run(seed, HERE / "seed.log")}
    if manifest["seed"]["exit"] == 0:
        if WOVEN.exists(): shutil.rmtree(WOVEN)
        WOVEN.mkdir()
        weave = [str(JDK / "java"), "-Xmx4g",
                 "-Dcausynth.trace.mode=region-state",
                 "-Dcausynth.region.skeletons=" +
                 str(STATIC / "region_skeletons.jsonl.gz"),
                 "-cp", graph_cp,
                 "edu.uva.liftlab.graphchecker.GraphCheckerMain",
                 "-i", str(SCOPE), "-x", cp, "-o", str(WOVEN)]
        manifest["weave"] = run(weave, HERE / "weave.log")
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
