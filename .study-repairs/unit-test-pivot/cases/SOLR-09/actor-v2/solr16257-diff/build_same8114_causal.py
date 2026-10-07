#!/usr/bin/env python3
"""Build an experimental same-version cache-absence refresh control.

The original Solr 8.11.4 test and fault hooks stay fixed. This is deliberately
not the SOLR-16257 upstream patch: that patch does not cleanly apply here.
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


CASE = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parent / "same8114-causal"
SOURCE = CASE / "timeout-diagnostic/generated"
CLASSES = ROOT / "classes"
GENERATED = ROOT / "generated"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, got {count}")
    return source.replace(before, after)


def main() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CASE / "timeout-diagnostic/classes", CLASSES, dirs_exist_ok=True)

    probe = (SOURCE / "FeedbackProbe.java").read_text()
    probe_end = "\n}\n"
    if not probe.endswith(probe_end):
        raise RuntimeError("probe class closing anchor changed")
    probe_method = '''
  /** Observe each bounded same-reader refresh without changing the selected guard. */
  public static synchronized void causalRefresh(String phase,
      org.apache.solr.common.cloud.ZkStateReader reader, String collection, int attempt,
      boolean cachePresent, long remainingLatch) {
    event("CAUSAL_REFRESH", "phase=" + safe(phase)
        + "\\tcollection=" + safe(collection)
        + "\\tattempt=" + attempt
        + "\\tcache_present=" + cachePresent
        + "\\tlatch_count=" + remainingLatch
        + "\\treader_id=" + System.identityHashCode(reader)
        + "\\tclient_id=" + System.identityHashCode(reader.getZkClient()));
  }
'''
    (GENERATED / "FeedbackProbe.java").write_text(
        probe[:-len(probe_end)] + probe_method + probe_end
    )
    shutil.copyfile(SOURCE / "DeleteReplicaCmd.java", GENERATED / "DeleteReplicaCmd.java")

    reader = (SOURCE / "ZkStateReader.java").read_text()
    before = '''      if (!latch.await(wait, unit)) {
        baseline.solr09.FeedbackProbe.preTimeoutState(this, collection);
        throw new TimeoutException(
            "Timeout waiting to see state for collection="'''
    after = '''      if (!latch.await(wait, unit)) {
        baseline.solr09.FeedbackProbe.preTimeoutState(this, collection);
        // Experimental causal control: an existing registration with no cached
        // collection state can mean that an initial ZK read lost its watch.
        // Reuse StateWatcher.refreshAndWatch so its existing ConnectionLoss and
        // SessionExpired handling remains unchanged. Only this timeout path
        // may retry; no selected DeleteReplicaCmd Boolean is modified.
        if (collectionWatches.containsKey(collection)
            && watchedCollectionStates.get(collection) == null) {
          for (int attempt = 1; attempt <= 3 && latch.getCount() != 0; attempt++) {
            baseline.solr09.FeedbackProbe.causalRefresh("before", this, collection,
                attempt, watchedCollectionStates.get(collection) != null, latch.getCount());
            new StateWatcher(collection).refreshAndWatch();
            baseline.solr09.FeedbackProbe.causalRefresh("after", this, collection,
                attempt, watchedCollectionStates.get(collection) != null, latch.getCount());
          }
        }
        if (latch.getCount() != 0)
          throw new TimeoutException(
            "Timeout waiting to see state for collection="'''
    reader = replace_once(reader, before, after, "DocCollection waitForState timeout")
    (GENERATED / "ZkStateReader.java").write_text(reader)

    cp = str(CLASSES) + ":" + (CASE / "classpath.txt").read_text().strip()
    command = [
        "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac",
        "-cp", cp, "-d", str(CLASSES),
        str(GENERATED / "FeedbackProbe.java"),
        str(GENERATED / "DeleteReplicaCmd.java"),
        str(GENERATED / "ZkStateReader.java"),
    ]
    subprocess.run(command, check=True)
    (ROOT / "classpath.txt").write_text(cp + "\n")
    receipt = {
        "classification": "experimental_same_8_11_4_causal_control",
        "upstream_patch_claimed": False,
        "original_test_changed": False,
        "original_target_boolean_changed": False,
        "compiled_classes": {name: sha256(CLASSES / name) for name in (
            "baseline/solr09/FeedbackProbe.class",
            "org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class",
            "org/apache/solr/common/cloud/ZkStateReader.class",
        )},
        "generated_source_sha256": {name: sha256(GENERATED / name) for name in (
            "FeedbackProbe.java", "DeleteReplicaCmd.java", "ZkStateReader.java"
        )},
        "diagnostic_target_class_sha256": sha256(
            CASE / "timeout-diagnostic/classes/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"
        ),
    }
    (ROOT / "build_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"compiled": True, "reader": receipt["compiled_classes"][
        "org/apache/solr/common/cloud/ZkStateReader.class"]}), flush=True)


if __name__ == "__main__":
    main()
