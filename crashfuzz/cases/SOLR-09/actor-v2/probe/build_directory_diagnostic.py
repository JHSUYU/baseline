#!/usr/bin/env python3
"""Build a separate guard-time filesystem snapshot for the selected core."""

from pathlib import Path
import shutil
import subprocess


WORK = Path(__file__).resolve().parents[1]
CLASSES = WORK / "directory-diagnostic/classes"
SOURCE_PROBE = WORK / "directory-diagnostic/generated/FeedbackProbe.java"
SOURCE_COMMAND = WORK / "directory-diagnostic/generated/DeleteReplicaCmd.java"


def main() -> None:
    shutil.copytree(WORK / "map-diagnostic/classes", CLASSES, dirs_exist_ok=True)
    probe = (WORK / "map-diagnostic/generated/FeedbackProbe.java").read_text()
    method = '''
  /** Diagnostic only: read the selected core's on-disk instance and data paths. */
  public static synchronized void coreDirectoryState(String core) {
    if (!Boolean.getBoolean("solr09.diagnostic.read_actual")) return;
    java.io.File scratch = new java.io.File(System.getProperty("java.io.tmpdir"));
    java.io.File[] suites = scratch.listFiles();
    if (suites == null) return;
    for (java.io.File suite : suites) {
      java.io.File[] temps = suite.listFiles();
      if (temps == null) continue;
      for (java.io.File temp : temps) {
        if (!temp.getName().startsWith("tempDir")) continue;
        java.io.File[] nodes = temp.listFiles();
        if (nodes == null) continue;
        for (java.io.File node : nodes) {
          if (!node.getName().matches("node[0-9]+")) continue;
          java.io.File instance = new java.io.File(node, core);
          java.io.File data = new java.io.File(instance, "data");
          event("CORE_DIR_STATE", "core=" + safe(core)
              + "\\tinstance=" + safe(instance.getAbsolutePath())
              + "\\tinstance_exists=" + instance.exists()
              + "\\tdata_exists=" + data.exists());
        }
      }
    }
  }
'''
    marker = "\n}\n"
    if not probe.endswith(marker):
        raise RuntimeError("Diagnostic probe end changed")
    SOURCE_PROBE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_PROBE.write_text(probe[:-len(marker)] + method + marker)

    command = (WORK / "map-diagnostic/generated/DeleteReplicaCmd.java").read_text()
    before = ("        baseline.solr09.FeedbackProbe.readerMapState("
              "ocmh.zkStateReader, collectionName, shard, replicaName);")
    after = ("        baseline.solr09.FeedbackProbe.coreDirectoryState(core);\n"
             + before)
    if command.count(before) != 1:
        raise RuntimeError("Selected guard diagnostic hook changed")
    SOURCE_COMMAND.write_text(command.replace(before, after))
    cp = str(CLASSES) + ":" + (WORK / "classpath.txt").read_text().strip()
    subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
                    "-cp", cp, "-d", str(CLASSES),
                    str(SOURCE_PROBE), str(SOURCE_COMMAND)], check=True)
    (WORK / "directory-diagnostic/classpath.txt").write_text(cp + "\n")


if __name__ == "__main__":
    main()
