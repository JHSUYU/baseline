#!/usr/bin/env python3
"""Seal SOLR-39's passing preemptive healthy run and strict-path deficit."""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
NAME = "SOLR-39-preemptive-healthy-node1-v3"
RAW = BASE / "data/mallory/pilot_observations" / NAME
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-39/preemptive-healthy-v3/admission-healthy-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
EXPECTED_GO = "9cf87305d401c4fa4871c2f2f063198401e8faf6324321c53ccb955cb8df1253"
SOURCE = "/users/ZhenyuLi/baseline/data/mallory/calibration_solr39_preemptive_healthy_v3_node1/SOLR-39"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(path.read_text())


def main():
    remote = {}
    for line in INDEX.read_text().splitlines():
        digest, name = line.split("  ", 1)
        name = name.removeprefix("./")
        if name in remote or not name or ".." in Path(name).parts:
            raise RuntimeError(f"invalid indexed name: {name}")
        remote[name] = digest
        if sha(RAW / name) != digest:
            raise RuntimeError(f"node1 raw differs: {name}")
    if not remote or sha(GO) != EXPECTED_GO:
        raise RuntimeError("raw SHA index or dispatch GO missing")
    result = load(RAW / "result.json")
    trial = load(RAW / "trials/r0000/result.json")
    pilot = load(RAW / "trials/r0000/pilot-result.json")
    selection = load(RAW / "late-watcher-selection.json")
    reference = load(RAW / "reference-audit.json")
    diagnostic = load(RAW / "late-path-diagnostic.json")
    junit = trial["junit_validation"]
    if (result["case_id"] != "SOLR-39"
            or result["status"] != "calibration_complete"
            or result["healthy_seed_valid"] is not True
            or result["fault_trials_completed"] != 0
            or result["new_bug"] is not None
            or trial["trial_id"] != 0 or trial["plan"]
            or trial["return_code"] != 0
            or trial["feedback"]["target_reached"] is not True
            or trial["feedback"]["target_threw"] is not False
            or trial["site_catalog_validation"]["valid"] is not True
            or junit["status"] != "passed" or junit["runner"] != "solr_junit_wrapper"
            or (junit["tests"], junit["failures"], junit["errors"]) != (1, 0, 0)
            or pilot["target_check_count"] != 11
            or pilot["target_throw_count"] != 0
            or pilot["target_nodes"] != ["node2", "node3", "node4"]
            or selection["status"] != "no_qualified_late_door"
            or selection["exact_target_checks"] != 11
            or selection["late_in_closure_candidates"]
            or reference["identity_markers"] != 1250
            or reference["paired_field_events"] != 1250
            or reference["unpaired_markers"] != 0
            or reference["transform_errors"] != 0
            or len(reference["candidate_paths"]) != 5
            or diagnostic["source_backed_reference_paths"] != 5
            or diagnostic["late_reference_paths"] != 3
            or diagnostic["strict_late_graph_paths"] != 0
            or len(diagnostic["paths"]) != 5
            or any(path["event_time_graph_witness"] for path in diagnostic["paths"])):
        raise RuntimeError("SOLR-39 v3 healthy/path outcome changed")
    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("v3 healthy evidence already sealed")
    manifest.write_text(json.dumps({"schema_version": 1, "files": members},
                                   indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz") as output:
        for name in sorted(members):
            output.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as saved:
        found = {}
        for item in saved:
            if item.isfile():
                name = item.name.removeprefix(f"{NAME}/")
                found[name] = hashlib.sha256(saved.extractfile(item).read()).hexdigest()
        if found != members:
            raise RuntimeError("archive member mismatch")
    receipt.write_text(json.dumps({
        "schema_version": 1, "case_id": "SOLR-39",
        "kind": "passing_healthy_seed_without_strict_late_graph_path",
        "source_host": "node1", "source_path": SOURCE,
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": result["status"], "duration_seconds": result["duration_seconds"],
        "junit_1_0_0": True, "healthy_seed_valid": True,
        "exact_target_checks": 11, "target_nodes": pilot["target_nodes"],
        "observed_typed_doors": result["healthy_observed_door_events"],
        "reference_markers_paired": 1250,
        "source_backed_reference_paths": 5, "late_reference_paths": 3,
        "strict_late_graph_paths": 0,
        "fault_injection_performed": False,
        "new_bug_confirmed": False,
        "admission_go_sha256": EXPECTED_GO,
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "late_watcher_selection_sha256": sha(RAW / "late-watcher-selection.json"),
        "reference_audit_sha256": sha(RAW / "reference-audit.json"),
        "late_path_diagnostic_sha256": sha(RAW / "late-path-diagnostic.json"),
        "trace_gzip_sha256": sha(RAW / "trials/r0000/events.jsonl.gz"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
