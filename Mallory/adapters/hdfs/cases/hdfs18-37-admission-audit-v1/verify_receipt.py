#!/usr/bin/env python3
"""Verify the offline HDFS-18/HDFS-37 source-pin audit without a JVM."""

import gzip
import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
RECEIPT = HERE / "receipt.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def check_junit_stdout(path: Path) -> None:
    output = path.read_text(encoding="utf-8")
    assert "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0" in output
    assert "BUILD SUCCESS" in output


def main() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 1
    assert receipt["jvm_started"] is False
    assert receipt["campaign_or_checklist_changed"] is False

    for section in ("source_pins", "artifact_pins"):
        for name, item in receipt[section].items():
            path = Path(item["path"])
            assert path.is_file(), (name, path)
            assert sha256(path) == item["sha256"], (name, path)

    source_root = Path(receipt["source_pins"]["DataStorage"]["path"]).parents[11]
    source_commit = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()
    assert source_commit == receipt["source_commit"]

    artifacts = receipt["artifact_pins"]
    check_junit_stdout(Path(artifacts["hdfs18_baseline_stdout"]["path"]))
    check_junit_stdout(Path(artifacts["hdfs37_baseline_stdout"]["path"]))

    h18 = list(events(Path(artifacts["hdfs18_baseline_events"]["path"])))
    first_inserts = [
        e for e in h18
        if "DatanodeDescriptor#injectStorage" in e.get("site", "")
        and "@522:branch:1" in e["site"]
    ]
    selected18 = [
        e for e in h18
        if "DatanodeDescriptor#injectStorage" in e.get("site", "")
        and "@537:" in e["site"]
    ]
    assert [e["seq"] for e in first_inserts] == [373]
    assert not selected18

    h37 = list(events(Path(artifacts["hdfs37_baseline_events"]["path"])))
    checks37 = [
        e for e in h37
        if e.get("type") == "TARGET_CHECK"
        and "DataStorage#doRollback" in e.get("site", "")
        and ("@940:" in e["site"] or "@941:" in e["site"])
    ]
    throws37 = [
        e for e in h37
        if e.get("type") == "TARGET_THROW"
        and "DataStorage#doRollback" in e.get("site", "")
        and "@947:" in e["site"]
    ]
    assert [e["seq"] for e in checks37[:2]] == [2566, 2568]
    assert [e["seq"] for e in throws37] == [3829, 5637, 5668]

    sites18 = json.loads(Path(artifacts["hdfs18_site_file"]["path"]).read_text())
    sites37 = json.loads(Path(artifacts["hdfs37_site_file"]["path"]).read_text())
    assert sites18["doors"] == [] and sites18["nodeBindings"] == []
    assert any(
        d.get("method") == "retrieveNamespaceInfo"
        and d.get("exception_class") == "java.io.IOException"
        for d in sites37["doors"]
    )

    print(json.dumps({
        "status": "offline_audit_receipt_verified",
        "source_commit": source_commit,
        "source_pins": len(receipt["source_pins"]),
        "artifact_pins": len(artifacts),
        "hdfs18_selected_events": len(selected18),
        "hdfs37_first_checks": [e["seq"] for e in checks37[:2]],
        "hdfs37_expected_throws": [e["seq"] for e in throws37],
        "jvm_started": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
