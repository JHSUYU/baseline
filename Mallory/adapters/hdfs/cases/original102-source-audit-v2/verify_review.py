#!/usr/bin/env python3
"""Verify pinned source and evidence bytes for the HDFS 13/18/37 review."""

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
REVIEW = Path(__file__).with_name("review.json")


def main():
    review = json.loads(REVIEW.read_text())
    assert review["schema_version"] == 1
    assert {case["case_id"] for case in review["cases"]} == {
        "HDFS-13", "HDFS-18", "HDFS-37"
    }
    for entry in review["artifacts"]:
        path = Path(entry["path"])
        if not path.is_absolute():
            path = REPO / path
        assert path.is_file(), path
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"], (path, digest)
    print(f"verified {len(review['artifacts'])} SHA-256 artifacts")


if __name__ == "__main__":
    main()
