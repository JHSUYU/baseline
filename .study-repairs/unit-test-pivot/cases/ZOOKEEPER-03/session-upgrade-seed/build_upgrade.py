#!/usr/bin/env python3
"""Build the isolated actor-aware trace agent for an original quorum JUnit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/zk03-independent-unit")
ORIGINAL_COMMIT = "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"
GENERIC_AGENT = Path("/users/ZhenyuLi/zk03-actor-v2-build/zk03-actor-v2-agent.jar")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
BUILD = HERE / "build"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    commit = subprocess.check_output(["git", "-C", str(SOURCE),
                                      "rev-parse", "HEAD"], text=True).strip()
    if commit != ORIGINAL_COMMIT:
        raise RuntimeError("ZooKeeper original source commit changed")
    classes = {
        "org/apache/zookeeper/test/SessionUpgradeTest":
            SOURCE / "zookeeper-server/target/test-classes/org/apache/zookeeper/test/SessionUpgradeTest.class",
        "org/apache/zookeeper/server/SessionTrackerImpl":
            SOURCE / "zookeeper-server/target/classes/org/apache/zookeeper/server/SessionTrackerImpl.class",
        "org/apache/zookeeper/server/quorum/LeaderSessionTracker":
            SOURCE / "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/LeaderSessionTracker.class",
    }
    sources = sorted((HERE / "src/research/zkactor/zk03upgrade").glob("*.java"))
    if len(sources) != 3 or any(not path.is_file() for path in classes.values()):
        raise RuntimeError("isolated agent sources or original classes absent")
    class_dir = BUILD / "classes"
    class_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JDK / "javac"), "-source", "8", "-target", "8",
                    "-cp", str(GENERIC_AGENT) + ":" + str(ASM),
                    "-d", str(class_dir)] + [str(path) for path in sources],
                   check=True)
    smoke_cp = ":".join((str(class_dir), str(GENERIC_AGENT), str(ASM),
                         str(SOURCE / "zookeeper-server/target/classes"),
                         str(SOURCE / "zookeeper-server/target/test-classes")))
    smoke = subprocess.check_output([str(JDK / "java"), "-Xverify:all", "-cp",
        smoke_cp,
        "research.zkactor.zk03upgrade.UpgradeTransformSmoke",
        str(classes["org/apache/zookeeper/test/SessionUpgradeTest"]),
        str(classes["org/apache/zookeeper/server/SessionTrackerImpl"])],
        text=True).strip()
    manifest = BUILD / "manifest.mf"
    manifest.write_text("Manifest-Version: 1.0\n"
                        "Premain-Class: research.zkactor.zk03upgrade.UpgradeAgent\n\n")
    jar = BUILD / "zk03-session-upgrade-agent.jar"
    subprocess.run([str(JDK / "jar"), "cfm", str(jar), str(manifest),
                    "-C", str(class_dir), "research/zkactor/zk03upgrade"],
                   check=True)
    receipt = {"status": "compiled_no_jvm", "original_commit": commit,
               "original_junit": "org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower",
               "agent_sha256": sha(jar),
               "generic_agent_sha256": sha(GENERIC_AGENT),
               "asm_sha256": sha(ASM),
               "offline_transform_smoke": smoke,
               "original_classes_sha256": {k: sha(v) for k, v in classes.items()},
               "sources_sha256": {str(x.relative_to(HERE)): sha(x) for x in sources}}
    (BUILD / "build-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
