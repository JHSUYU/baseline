#!/usr/bin/env python3
"""Preserve the completed lane8 HBASE-12 campaign without changing node1 evidence."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CASE = ROOT / "data/mallory/cases/HBASE-12"
ARCHIVE = ROOT / "data/mallory/evidence_archives/campaign_legacy_lane8/HBASE-12.tar.gz"
REMOTE_ARCHIVE = ROOT / "data/mallory/evidence_archives/campaign_legacy_lane8/HBASE-12.tar.gz"
RELEASE_ID = "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
RELEASE = ROOT / "Mallory/dispatch/releases" / RELEASE_ID
HOST = "ZhenyuLi@node1"
KEY = "/users/ZhenyuLi/.ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", HOST]
FLOOR = 5 * 1024**3
SAFETY = 128 * 1024**2


def run(argv, *, check=True, env=None):
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    if check and proc.returncode:
        raise RuntimeError(f"{argv[0]} exited {proc.returncode}: {proc.stderr[-1200:]}")
    return proc


def remote(argv):
    return run(SSH + [shlex.join([str(item) for item in argv])]).stdout


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes():
    code = (
        "import hashlib,json,pathlib,sys; "
        "root=pathlib.Path(sys.argv[1]); "
        "files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='.campaign.lock'); "
        "print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() "
        "for p in files},sort_keys=True))"
    )
    return json.loads(remote(["python3", "-c", code, CASE]))


def ensure_space(additional):
    free = shutil.disk_usage(ROOT).free
    if free - additional < FLOOR + SAFETY:
        raise RuntimeError(f"node0 floor held: free={free}, additional={additional}, "
                           f"required_floor={FLOOR + SAFETY}")


def verify_archive(members):
    observed = {}
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for member in archive:
            name = Path(member.name)
            if (not (member.isdir() or member.isfile()) or
                    not name.parts or name.parts[0] != "HBASE-12" or
                    ".." in name.parts):
                raise RuntimeError(f"unsafe archive member: {member.name}")
            if not member.isfile():
                continue
            item = archive.extractfile(member)
            if item is None:
                raise RuntimeError(f"unreadable member: {member.name}")
            observed[str(Path(*name.parts[1:]))] = hashlib.sha256(item.read()).hexdigest()
    if observed != members:
        raise RuntimeError("archive member hashes differ from node1 terminal files")


def extract_or_check(members):
    created = not CASE.exists()
    if created:
        expanded = int(remote(["du", "-sb", CASE]).split()[0])
        ensure_space(expanded)
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            archive.extractall(CASE.parent)
    local = {str(path.relative_to(CASE)): sha(path)
             for path in sorted(CASE.rglob("*"))
             if path.is_file() and path.name != ".campaign.lock"}
    if local != members:
        raise RuntimeError("node0 canonical files differ from node1 terminal files")
    return created


def main():
    original = ROOT / "data/mallory/evidence_archives/campaign/HBASE-12.tar.manifest.json"
    remote_result = json.loads(remote(["cat", CASE / "result.json"]))
    if (remote_result.get("case_id") != "HBASE-12" or
            remote_result.get("status") != "budget_exhausted" or
            remote_result.get("fault_trials_completed") != 80):
        raise RuntimeError("node1 result is not the expected terminal case")
    config = json.loads(remote(["cat", CASE / "config.json"]))
    if config["core_release"]["release_id"] != RELEASE_ID:
        raise RuntimeError("campaign core release differs")
    if sha(RELEASE / "manifest.json") != config["core_release"]["manifest_sha256"]:
        raise RuntimeError("pinned core manifest differs")

    before = source_hashes()
    if "result.json" not in before or "offline-causal-audit.json" not in before:
        raise RuntimeError("terminal result or remote audit absent")
    remote(["mkdir", "-p", REMOTE_ARCHIVE.parent])
    if run(SSH + [shlex.join(["test", "-f", str(REMOTE_ARCHIVE)])], check=False).returncode:
        remote(["tar", "--exclude=.campaign.lock", "-C", CASE.parent,
                "-czf", str(REMOTE_ARCHIVE) + ".tmp", CASE.name])
        remote(["mv", str(REMOTE_ARCHIVE) + ".tmp", REMOTE_ARCHIVE])
    after = source_hashes()
    if before != after:
        raise RuntimeError("node1 source changed while archiving")
    remote_archive_sha = remote(["sha256sum", REMOTE_ARCHIVE]).split()[0]
    remote_archive_size = int(remote(["stat", "-c", "%s", REMOTE_ARCHIVE]).strip())
    if not ARCHIVE.exists():
        ensure_space(remote_archive_size)
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(str(ARCHIVE) + ".tmp")
        run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
             f"{HOST}:{REMOTE_ARCHIVE}", str(temp)])
        if sha(temp) != remote_archive_sha:
            raise RuntimeError("transferred archive SHA differs from node1")
        os.replace(temp, ARCHIVE)
    if sha(ARCHIVE) != remote_archive_sha:
        raise RuntimeError("local archive SHA differs from node1")
    verify_archive(after)
    created_case_copy = extract_or_check(after)

    members_path = HERE / "member-sha256.json"
    members_path.write_text(json.dumps(after, indent=2, sort_keys=True) + "\n")
    env = dict(os.environ, PYTHONPATH=f"{RELEASE}:{ROOT}")
    node0_audit_path = HERE / "node0-offline-causal-audit.json"
    audit_run = run([sys.executable, "-m", "Mallory.core.audit", "--campaign", str(CASE),
                     "--out", str(node0_audit_path)], check=False, env=env)
    if audit_run.returncode not in (0, 2):
        raise RuntimeError(f"pinned offline audit failed: {audit_run.stderr[-1200:]}")
    node0_audit = json.loads(node0_audit_path.read_text())
    remote_audit = json.loads((CASE / "offline-causal-audit.json").read_text())
    result = json.loads((CASE / "result.json").read_text())
    if (node0_audit["campaign_result_sha256"] != after["result.json"] or
            remote_audit["campaign_result_sha256"] != after["result.json"] or
            node0_audit["core_source_sha256"] != remote_audit["core_source_sha256"]):
        raise RuntimeError("pinned audit result or core differs")
    source_test = Path(config["mapping"]["source_root"]) / (
        "hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/TestRegionMove.java")
    if sha(source_test) != config["mapping"]["test_source_sha256"]:
        raise RuntimeError("source test pin differs")
    test = source_test.read_text()
    if "admin.disableTable(tableName);" not in test or "catch (DoNotRetryIOException e)" not in test:
        raise RuntimeError("expected-exception source phase absent")

    compact_result = HERE / "terminal-result.json"
    compact_config = HERE / "terminal-config.json"
    shutil.copy2(CASE / "result.json", compact_result)
    shutil.copy2(CASE / "config.json", compact_config)
    if sha(compact_result) != after["result.json"] or sha(compact_config) != after["config.json"]:
        raise RuntimeError("compact result or config differs")
    if created_case_copy:
        # The full verified archive is offhost on node0. Retain only compact
        # review files after the pinned audit to restore the node0 disk margin.
        shutil.rmtree(CASE)

    prior_manifest = json.loads(remote(["cat", original]))
    prior_manifest_sha = remote(["sha256sum", original]).split()[0]
    prior_result_sha = prior_manifest["source_result_sha256"]
    receipt = {
        "schema_version": 1, "case_id": "HBASE-12",
        "kind": "lane8_legacy_terminal_preservation",
        "source_host": "node1", "source_case_path": str(CASE),
        "source_archive_path": str(REMOTE_ARCHIVE),
        "archive_path": str(ARCHIVE), "archive_sha256": sha(ARCHIVE),
        "member_count": len(after), "member_sha256_path": str(members_path),
        "member_manifest_sha256": sha(members_path),
        "result_sha256": after["result.json"], "config_sha256": after["config.json"],
        "compact_result_path": str(compact_result),
        "compact_config_path": str(compact_config),
        "node0_expanded_copy_removed_after_audit": created_case_copy,
        "remote_audit_sha256": after["offline-causal-audit.json"],
        "node0_audit_sha256": sha(node0_audit_path),
        "core_release_id": RELEASE_ID,
        "core_manifest_sha256": sha(RELEASE / "manifest.json"),
        "status": result["status"],
        "fault_trials_completed": result["fault_trials_completed"],
        "duration_seconds": result["duration_seconds"],
        "healthy_junit_status": result["healthy_junit_validation"]["status"],
        "strict_injected_trials": result["strict_injected_trials"],
        "strict_target_trials": result["strict_target_trials"],
        "exact_exception_trials": result["exact_exception_trials"],
        "target_exception_candidate_trials": result["target_exception_candidate_trials"],
        "test_source_sha256": sha(source_test),
        "audit_report_gate_passed": node0_audit["report_gate_passed"],
        "audit_target_claims_reverified": node0_audit["target_claims_reverified"],
        "audit_applied_fault_identity_valid": node0_audit["applied_fault_identity_valid"],
        "audit_target_retained_fault_trials": node0_audit["target_retained_fault_trials"],
        "audit_named_applied_faults": node0_audit["named_applied_faults"],
        "oracle_limit": "TestRegionMove#testDisableAndMove disables table at 115-116 and "
                        "catches expected DoNotRetryIOException at 118-123; class-only "
                        "exception evidence does not establish exact @763 throw causality.",
        "hq_admission": False,
        "previous_archive_manifest_sha256": prior_manifest_sha,
        "previous_archive_result_sha256": prior_result_sha,
        "previous_archive_stale": prior_result_sha != after["result.json"],
    }
    (HERE / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": receipt["status"], "archive_sha256": receipt["archive_sha256"],
                      "member_count": len(after), "result_sha256": receipt["result_sha256"],
                      "audit_sha256": receipt["node0_audit_sha256"],
                      "receipt_sha256": sha(HERE / "receipt.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
