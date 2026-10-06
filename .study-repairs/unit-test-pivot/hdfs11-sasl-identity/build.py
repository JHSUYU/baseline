"""Patch one already-woven Hadoop 3.4.3 SASL server class in isolation."""

from pathlib import Path
import argparse
import os
import subprocess
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
PIVOT = HERE.parent
GRAPH = Path("/users/ZhenyuLi/.graphchecker-builds/unit-test-core-0889fb01f-fea8c862bb5c.jar")
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
DEFAULT_WOVEN = PIVOT / "hdfs11-param-expanded/instrumented"
CLASS = Path("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer.class")
CLIENT_CLASS = Path("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class")
REGISTRATION_CLASS = Path("org/apache/hadoop/hdfs/server/datanode/BPOfferService.class")
DEFAULT_OVERLAY = HERE / "overlay"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--woven", type=Path, default=DEFAULT_WOVEN)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    args = parser.parse_args()
    woven = args.woven.resolve()
    overlay = args.overlay.resolve()
    overlay.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(JDK / "javac"), "-cp", str(GRAPH), "-d", str(overlay),
        str(HERE / "HdfsSaslRequestIdentity.java"),
        str(HERE / "PatchSaslReceive.java"),
    ], check=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    cp = os.pathsep.join((str(overlay), str(woven), str(GRAPH), hadoop_cp))
    subprocess.run([
        str(JDK / "java"), "-cp", cp, "PatchSaslReceive",
        "sasl", str(woven / CLASS), str(overlay / CLASS),
    ], env=env, check=True)
    subprocess.run([
        str(JDK / "java"), "-cp", cp, "PatchSaslReceive",
        "client", str(woven / CLIENT_CLASS), str(overlay / CLIENT_CLASS),
    ], env=env, check=True)
    original = HERE / "source" / REGISTRATION_CLASS
    original.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar") as archive:
        original.write_bytes(archive.read(str(REGISTRATION_CLASS)))
    subprocess.run([
        str(JDK / "java"), "-cp", cp, "PatchSaslReceive",
        "registration", str(original), str(overlay / REGISTRATION_CLASS),
    ], env=env, check=True)
    print(overlay)


if __name__ == "__main__":
    main()
