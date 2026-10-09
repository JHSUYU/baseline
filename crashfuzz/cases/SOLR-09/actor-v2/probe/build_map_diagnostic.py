#!/usr/bin/env python3
"""Build a separate read-only watcher-map diagnostic for novelty review."""

from pathlib import Path
import shutil
import subprocess


WORK = Path(__file__).resolve().parents[1]
CLASSES = WORK / "map-diagnostic/classes"
SOURCE_PROBE = WORK / "map-diagnostic/generated/FeedbackProbe.java"
SOURCE_COMMAND = WORK / "map-diagnostic/generated/DeleteReplicaCmd.java"
V2_COMMAND = (WORK / "probe/generated/solr/core/src/java/org/apache/solr/"
              "cloud/api/collections/DeleteReplicaCmd.java")


def main() -> None:
    shutil.copytree(WORK / "classes", CLASSES, dirs_exist_ok=True)
    probe = (WORK / "diagnostic/generated/FeedbackProbe.java").read_text()
    method = '''
  /** Diagnostic only: inspect both existing maps without refreshing either. */
  public static synchronized void readerMapState(
      org.apache.solr.common.cloud.ZkStateReader reader,
      String collection, String shard, String replicaName) {
    if (!Boolean.getBoolean("solr09.diagnostic.read_actual")) return;
    try {
      java.lang.reflect.Field watchesField = reader.getClass().getDeclaredField("collectionWatches");
      java.lang.reflect.Field cachedField = reader.getClass().getDeclaredField("watchedCollectionStates");
      watchesField.setAccessible(true);
      cachedField.setAccessible(true);
      java.util.Map<?, ?> watches = (java.util.Map<?, ?>) watchesField.get(reader);
      java.util.Map<?, ?> cached = (java.util.Map<?, ?>) cachedField.get(reader);
      Object watch = watches.get(collection);
      int watcherCount = -1;
      int coreRefCount = -1;
      if (watch != null) {
        java.lang.reflect.Field stateWatchersField = watch.getClass().getDeclaredField("stateWatchers");
        java.lang.reflect.Field coreRefCountField = watch.getClass().getDeclaredField("coreRefCount");
        stateWatchersField.setAccessible(true);
        coreRefCountField.setAccessible(true);
        watcherCount = ((java.util.Set<?>) stateWatchersField.get(watch)).size();
        coreRefCount = coreRefCountField.getInt(watch);
      }
      org.apache.solr.common.cloud.DocCollection state =
          (org.apache.solr.common.cloud.DocCollection) cached.get(collection);
      org.apache.solr.common.cloud.Slice slice = state == null ? null : state.getSlice(shard);
      boolean replicaPresent = slice != null && slice.getReplica(replicaName) != null;
      event("READER_MAP_STATE", "collection=" + safe(collection)
          + "\\twatch_present=" + watches.containsKey(collection)
          + "\\tcached_present=" + (state != null)
          + "\\tcached_replica_present=" + replicaPresent
          + "\\tcached_version=" + (state == null ? -1 : state.getZNodeVersion())
          + "\\twatcher_count=" + watcherCount
          + "\\tcore_ref_count=" + coreRefCount
          + "\\treader_id=" + System.identityHashCode(reader)
          + "\\tclient_id=" + System.identityHashCode(reader.getZkClient()));
    } catch (Exception error) {
      event("READER_MAP_STATE_ERROR", error.getClass().getName()
          + ":" + safe(error.getMessage()));
    }
  }
'''
    marker = "\n}\n"
    if not probe.endswith(marker):
        raise RuntimeError("Diagnostic probe end changed")
    SOURCE_PROBE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_PROBE.write_text(probe[:-len(marker)] + method + marker)

    command = V2_COMMAND.read_text()
    before = ('        baseline.solr09.FeedbackProbe.targetCheck(!coreNodeGone, collectionName, shard, '
              'replicaName, core, isLive, ocmh.zkStateReader.getZkClient(), '
              'ocmh.overseer.getCoreContainer().getZkController().getNodeName());')
    after = ('        baseline.solr09.FeedbackProbe.readerMapState('
             'ocmh.zkStateReader, collectionName, shard, replicaName);\n' + before)
    if command.count(before) != 1:
        raise RuntimeError("Selected guard diagnostic hook changed")
    SOURCE_COMMAND.write_text(command.replace(before, after))
    cp = str(CLASSES) + ":" + (WORK / "classpath.txt").read_text().strip()
    subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
                    "-cp", cp, "-d", str(CLASSES),
                    str(SOURCE_PROBE), str(SOURCE_COMMAND)], check=True)
    (WORK / "map-diagnostic/classpath.txt").write_text(cp + "\n")


if __name__ == "__main__":
    main()
