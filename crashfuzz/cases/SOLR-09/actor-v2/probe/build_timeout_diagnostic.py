#!/usr/bin/env python3
"""Build a separate read-only snapshot just before waitForState removes its watcher."""

from pathlib import Path
import shutil
import subprocess


WORK = Path(__file__).resolve().parents[1]
CLASSES = WORK / "timeout-diagnostic/classes"
GENERATED = WORK / "timeout-diagnostic/generated"
SOURCE_PROBE = GENERATED / "FeedbackProbe.java"
SOURCE_COMMAND = GENERATED / "DeleteReplicaCmd.java"
SOURCE_READER = GENERATED / "ZkStateReader.java"


def main() -> None:
    shutil.copytree(WORK / "directory-diagnostic/classes", CLASSES, dirs_exist_ok=True)
    probe = (WORK / "directory-diagnostic/generated/FeedbackProbe.java").read_text()
    method = '''
  /** Diagnostic only: inspect the selected reader immediately before timeout cleanup. */
  public static synchronized void preTimeoutState(
      org.apache.solr.common.cloud.ZkStateReader reader, String collection) {
    if (!Boolean.getBoolean("solr09.diagnostic.read_actual")
        || reader.getZkClient() != targetOverseerClient) return;
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
      boolean corePresent = false;
      if (state != null) {
        for (org.apache.solr.common.cloud.Slice slice : state.getSlices()) {
          for (org.apache.solr.common.cloud.Replica replica : slice.getReplicas()) {
            if (replica.getCoreName().equals(targetCore)) corePresent = true;
          }
        }
      }
      event("PRE_TIMEOUT_READER_STATE", "collection=" + safe(collection)
          + "\\tcore=" + safe(targetCore)
          + "\\twatch_present=" + (watch != null)
          + "\\twatcher_count=" + watcherCount
          + "\\tcore_ref_count=" + coreRefCount
          + "\\tcached_present=" + (state != null)
          + "\\tcached_core_present=" + corePresent
          + "\\tcached_version=" + (state == null ? -1 : state.getZNodeVersion())
          + "\\treader_id=" + System.identityHashCode(reader)
          + "\\tclient_id=" + System.identityHashCode(reader.getZkClient()));
    } catch (Exception error) {
      event("PRE_TIMEOUT_READER_STATE_ERROR", error.getClass().getName()
          + ":" + safe(error.getMessage()));
    }
  }
'''
    marker = "\n}\n"
    if not probe.endswith(marker):
        raise RuntimeError("Diagnostic probe end changed")
    GENERATED.mkdir(parents=True, exist_ok=True)
    SOURCE_PROBE.write_text(probe[:-len(marker)] + method + marker)
    shutil.copyfile(WORK / "directory-diagnostic/generated/DeleteReplicaCmd.java", SOURCE_COMMAND)

    original = (WORK / "solr-source/solr/solrj/src/java/org/apache/solr/"
                "common/cloud/ZkStateReader.java").read_text()
    before = '''      if (!latch.await(wait, unit))
        throw new TimeoutException(
            "Timeout waiting to see state for collection="'''
    after = '''      if (!latch.await(wait, unit)) {
        baseline.solr09.FeedbackProbe.preTimeoutState(this, collection);
        throw new TimeoutException(
            "Timeout waiting to see state for collection="'''
    if original.count(before) != 1:
        raise RuntimeError("DocCollection waitForState timeout changed")
    replaced = original.replace(before, after)
    before_end = '''                + docCollectionReference.get());
    } finally {'''
    after_end = '''                + docCollectionReference.get());
      }
    } finally {'''
    if replaced.count(before_end) != 1:
        raise RuntimeError("DocCollection timeout close changed")
    SOURCE_READER.write_text(replaced.replace(before_end, after_end))

    cp = str(CLASSES) + ":" + (WORK / "classpath.txt").read_text().strip()
    subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
                    "-cp", cp, "-d", str(CLASSES), str(SOURCE_PROBE),
                    str(SOURCE_COMMAND), str(SOURCE_READER)], check=True)
    (WORK / "timeout-diagnostic/classpath.txt").write_text(cp + "\n")


if __name__ == "__main__":
    main()
