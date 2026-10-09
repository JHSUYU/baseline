#!/usr/bin/env python3
"""Build a separate read-only ZK diagnostic probe without touching V2 classes."""

from pathlib import Path
import shutil
import subprocess


WORK = Path(__file__).resolve().parents[1]
CLASSES = WORK / "diagnostic/classes"
SOURCE = WORK / "diagnostic/generated/FeedbackProbe.java"


def main() -> None:
    shutil.copytree(WORK / "classes", CLASSES, dirs_exist_ok=True)
    source = (WORK / "probe/FeedbackProbe.java").read_text()
    before = ('    event("TARGET_CHECK", (couldNotRemove ? "not_removed" : "removed")\n'
              '        + "\\t" + identity);\n'
              '    if (couldNotRemove) event("TARGET_EXCEPTION", identity);')
    after = ('    event("TARGET_CHECK", (couldNotRemove ? "not_removed" : "removed")\n'
             '        + "\\t" + identity);\n'
             '    if (Boolean.getBoolean("solr09.diagnostic.read_actual")) {\n'
             '      try {\n'
             '        org.apache.zookeeper.data.Stat stat = new org.apache.zookeeper.data.Stat();\n'
             '        byte[] raw = overseerClient.getData("/collections/" + collection + "/state.json",\n'
             '            null, stat, true);\n'
             '        String json = new String(raw, java.nio.charset.StandardCharsets.UTF_8);\n'
             '        event("ZK_ACTUAL_STATE", "collection=" + safe(collection)\n'
             '            + "\\treplica=" + safe(replicaName)\n'
             '            + "\\treplica_present=" + json.contains("\\\"" + replicaName + "\\\"")\n'
             '            + "\\tzk_version=" + stat.getVersion()\n'
             '            + "\\traw_json=" + safe(json));\n'
             '      } catch (Exception error) {\n'
             '        event("ZK_ACTUAL_STATE_ERROR", error.getClass().getName()\n'
             '            + ":" + safe(error.getMessage()));\n'
             '      }\n'
             '    }\n'
             '    if (couldNotRemove) event("TARGET_EXCEPTION", identity);')
    if source.count(before) != 1:
        raise RuntimeError("Selected target check changed; diagnostic build refused")
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE.write_text(source.replace(before, after))
    original_cp = (WORK / "classpath.txt").read_text().strip()
    cp = str(CLASSES) + ":" + original_cp
    subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
                    "-cp", cp, "-d", str(CLASSES), str(SOURCE)], check=True)
    (WORK / "diagnostic/classpath.txt").write_text(cp + "\n")


if __name__ == "__main__":
    main()
