#!/usr/bin/env python3
"""Build a separate fresh-state differential control after the original guard wait."""

from pathlib import Path
import shutil
import subprocess


WORK = Path(__file__).resolve().parents[1]
CLASSES = WORK / "differential-control/classes"
SOURCE = WORK / "differential-control/generated/DeleteReplicaCmd.java"
ORIGINAL_WOVEN = (WORK / "probe/generated/solr/core/src/java/org/apache/solr/"
                  "cloud/api/collections/DeleteReplicaCmd.java")


def main() -> None:
    shutil.copytree(WORK / "classes", CLASSES, dirs_exist_ok=True)
    source = ORIGINAL_WOVEN.read_text()
    before = "        boolean coreNodeGone = callable.call();\n"
    after = ("        boolean coreNodeGone = callable.call();\n"
             "        // Diagnostic control only: the original JUnit and injected faults are unchanged.\n"
             "        // The selected Boolean is changed only if a fresh server read proves\n"
             "        // the target replica is absent after both original 30s waits.\n"
             "        if (!coreNodeGone) {\n"
             "          try {\n"
             "            org.apache.zookeeper.data.Stat freshStat = new org.apache.zookeeper.data.Stat();\n"
             "            byte[] actual = ocmh.zkStateReader.getZkClient().getData(\n"
             "                \"/collections/\" + collectionName + \"/state.json\", null, freshStat, true);\n"
             "            String freshJson = new String(actual, java.nio.charset.StandardCharsets.UTF_8);\n"
             "            boolean freshContainsReplica = freshJson.contains(\"\\\"\" + replicaName + \"\\\"\");\n"
             "            System.out.println(\"SOLR09_DIFFERENTIAL_FRESH_STATE replica=\" + replicaName\n"
             "                + \" present=\" + freshContainsReplica + \" version=\" + freshStat.getVersion());\n"
             "            if (!freshContainsReplica) coreNodeGone = true;\n"
             "          } catch (Exception freshError) {\n"
             "            System.out.println(\"SOLR09_DIFFERENTIAL_FRESH_STATE_ERROR \"\n"
             "                + freshError.getClass().getName());\n"
             "          }\n"
             "        }\n")
    if source.count(before) != 1:
        raise RuntimeError("Selected original guard changed; control build refused")
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE.write_text(source.replace(before, after))
    cp = str(CLASSES) + ":" + (WORK / "classpath.txt").read_text().strip()
    subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
                    "-cp", cp, "-d", str(CLASSES), str(SOURCE)], check=True)
    (WORK / "differential-control/classpath.txt").write_text(cp + "\n")


if __name__ == "__main__":
    main()
