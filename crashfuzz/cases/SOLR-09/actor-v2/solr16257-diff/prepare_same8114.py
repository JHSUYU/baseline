#!/usr/bin/env python3
"""Freeze same-version classpaths and identities before remote calibration."""

import hashlib
import json
import shutil
from pathlib import Path


CASE = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "same8114-causal"
ORIGINAL_SOURCE = CASE / "solr-source"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    STAGE.mkdir(parents=True, exist_ok=True)
    baseline = STAGE / "baseline-classes"
    causal = STAGE / "causal-classes"
    shutil.copytree(CASE / "timeout-diagnostic/classes", baseline, dirs_exist_ok=True)
    shutil.copytree(STAGE / "classes", causal, dirs_exist_ok=True)
    original_classpath = (CASE / "classpath.txt").read_text().strip()
    original_classes = str(CASE / "classes")
    original_testfiles = str(CASE.parent / "http-stage2/solr-source/solr/core/src/test-files")
    staged_testfiles = str(STAGE / "source/solr/core/src/test-files")
    if original_classpath.count(original_classes) != 1:
        raise RuntimeError("class path anchor mismatch")
    if original_classpath.count(original_testfiles) != 1:
        raise RuntimeError("test resources anchor mismatch")
    for name, classes in (("baseline", baseline), ("causal", causal)):
        classpath = original_classpath.replace(original_classes, str(classes)).replace(
            original_testfiles, staged_testfiles)
        (STAGE / f"{name}-classpath.txt").write_text(classpath + "\n")
    test_class = Path("org/apache/solr/cloud/DeleteReplicaTest.class")
    baseline_sha = sha256(baseline / test_class)
    causal_sha = sha256(causal / test_class)
    if baseline_sha != causal_sha:
        raise RuntimeError("original JUnit bytecode differs")
    original = ORIGINAL_SOURCE / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    receipt = {
        "version": "Solr 8.11.4",
        "original_test_class_sha256": baseline_sha,
        "baseline_target_class_sha256": sha256(
            baseline / "org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"),
        "causal_target_class_sha256": sha256(
            causal / "org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"),
        "original_reader_source_sha256": sha256(original),
        "reader_diagnostic_class_sha256": sha256(
            baseline / "org/apache/solr/common/cloud/ZkStateReader.class"),
        "reader_causal_class_sha256": sha256(
            causal / "org/apache/solr/common/cloud/ZkStateReader.class"),
        "source_bundle_bytes_approx": 296_000_000,
    }
    (STAGE / "identity_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
