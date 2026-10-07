#!/usr/bin/env python3
"""Fresh unchanged-JUnit and actor-overlay healthy seeds for SOLR-18."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from actor_audit import audit
from build import CLEAN_CLASSES, CLASSES, HERE
from run_native import RUN_ROOT, run


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    clean = subprocess.run([
        sys.executable, str(HERE / "original_run.py"),
        str(RUN_ROOT / "original-a"), "--timeout", "300",
    ], check=False)
    if clean.returncode:
        raise RuntimeError("Unmodified released JUnit failed")
    actor = run("healthy-v2-b", timeout=300)
    if actor["junit_exit"] != 0 or actor["test_started_count"] != 1:
        raise RuntimeError("Actor-aware healthy JUnit failed")
    junit = Path("org/apache/solr/cloud/AliasIntegrationTest.class")
    if sha(CLEAN_CLASSES / junit) != sha(CLASSES / junit):
        raise RuntimeError("Original JUnit bytecode differs between classpaths")
    first = json.loads((RUN_ROOT / "healthy-v2-a/run.json").read_text())
    second = json.loads((RUN_ROOT / "healthy-v2-b/run.json").read_text())
    for item in (first, second):
        if item["junit_exit"] or item["assumption_failure_count"]:
            raise RuntimeError("Actor-aware seed failed or skipped")
    reports = [audit(RUN_ROOT / name / "events.tsv", [])
               for name in ("healthy-v2-a", "healthy-v2-b")]
    if not all(item["selected_target"] and item["target_json_equal"]
               and item["target_actor"] and
               item["relevant_same_client_io_selectors"] for item in reports):
        raise RuntimeError("Selected actor check or I/O missing from healthy seed")
    receipt = {
        "original_a": json.loads((RUN_ROOT / "original-a/run.json").read_text()),
        "actor_seed_a": first,
        "actor_seed_b": second,
        "target_actor_counts": [len(item["relevant_same_client_io_selectors"])
                                for item in reports],
        "source_junit_sha_equal": True,
        "junit_class_sha256": sha(CLEAN_CLASSES / junit),
    }
    (HERE / "calibration.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"original_pass": True, "actor_pass": True,
                      "relevant_io_sites": receipt["target_actor_counts"]},
                     sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
