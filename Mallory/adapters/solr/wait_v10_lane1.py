#!/usr/bin/env python3
"""Wait for SOLR-05's verified archive, then calibrate ten v10 cases on lane1."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parents[3]
ARCHIVE = REPO / "data/mallory/replays/SOLR-05-v4-junit"
KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "ZhenyuLi@node2"]
REMOTE_BATCH = "/users/ZhenyuLi/baseline/Mallory/adapters/solr/run_v10_identity_batch.py"
COHORTS = (
    {"name": "identity", "case_ids": ("SOLR-09", "SOLR-14", "SOLR-18"),
     "remote": "/users/ZhenyuLi/baseline/data/mallory/calibration_v10_lane1",
     "local": REPO / "data/mallory/calibration_v10_lane1",
     "session": "mallory-solr-v10-identity-lane1"},
    {"name": "remaining", "case_ids": ("SOLR-10", "SOLR-13", "SOLR-39", "SOLR-40",
                                       "SOLR-31", "SOLR-36", "SOLR-37"),
     "remote": "/users/ZhenyuLi/baseline/data/mallory/calibration_v10_lane1_remaining",
     "local": REPO / "data/mallory/calibration_v10_lane1_remaining",
     "session": "mallory-solr-v10-remaining-lane1"},
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def archived_and_audited() -> bool:
    result, receipt, audit, final_audit, final_receipt, initial = (ARCHIVE / name for name in
        ("result.json", "sync-receipt.json", "offline-causal-audit.json",
         "offline-causal-audit-release-5820.json", "final-release-audit-receipt.json",
         "offline-causal-audit-initial.json"))
    if not all(path.is_file() for path in
               (result, receipt, audit, final_audit, final_receipt, initial)):
        return False
    expected = digest(result)
    synced = json.loads(receipt.read_text(encoding="utf-8"))
    checked = json.loads(audit.read_text(encoding="utf-8"))
    final = json.loads(final_receipt.read_text(encoding="utf-8"))
    return (synced.get("case_id") == "SOLR-05"
            and synced.get("result_sha256") == expected
            and checked.get("case_id") == "SOLR-05"
            and checked.get("campaign_result_sha256") == expected
            and final.get("result_sha256") == expected
            and final.get("core_release_id") ==
                "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
            and final.get("pinned_audit_sha256") == digest(final_audit)
            and final.get("canonical_audit_sha256") == digest(audit)
            and final.get("initial_audit_sha256") == digest(initial))


def ssh(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(SSH + [command], text=True, capture_output=True)


def session_active(name: str) -> bool:
    result = ssh("tmux has-session -t " + name)
    if result.returncode == 255:
        raise RuntimeError("cannot inspect node2 tmux: " + result.stderr.strip())
    return result.returncode == 0


def lane_free() -> bool:
    result = ssh("flock -n /tmp/mallory-lanes/solr-lane1.lock true")
    if result.returncode == 255:
        raise RuntimeError("cannot inspect node2 lane lock: " + result.stderr.strip())
    return result.returncode == 0


def batch_terminal(cohort: dict) -> bool:
    result = ssh("test -f " + cohort["remote"] + "/batch-result.json")
    if result.returncode == 255:
        raise RuntimeError("cannot inspect node2 batch result: " + result.stderr.strip())
    return result.returncode == 0


def collect(cohort: dict) -> None:
    remote_manifest_script = '''import hashlib,json,pathlib
root=pathlib.Path(''' + repr(cohort["remote"]) + ''')
files={}
for path in sorted(root.rglob("*")):
 if path.is_symlink(): raise ValueError("symlink in calibration evidence: " + str(path))
 if path.is_file(): files[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(files,sort_keys=True))
'''
    manifest = ssh("python3 - <<'PY'\n" + remote_manifest_script + "\nPY")
    if manifest.returncode:
        raise RuntimeError("remote v10 manifest failed: " + manifest.stderr.strip())
    expected = json.loads(manifest.stdout)
    if "batch-result.json" not in expected:
        raise RuntimeError("remote v10 batch is not terminal")
    local_output = cohort["local"]
    local_output.parent.mkdir(parents=True, exist_ok=True)
    if not local_output.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".solr-v10-" + cohort["name"] + "-sync-",
                                          dir=local_output.parent))
        try:
            subprocess.run(["rsync", "-az", "--checksum", "-e",
                            "ssh -i " + str(KEY) + " -o IdentitiesOnly=yes",
                            "ZhenyuLi@node2:" + cohort["remote"] + "/",
                            str(temporary) + "/"], check=True)
            actual = {str(path.relative_to(temporary)): digest(path)
                      for path in temporary.rglob("*") if path.is_file()}
            if actual != expected:
                raise ValueError("v10 evidence hash manifest differs after transfer")
            os.replace(temporary, local_output)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    else:
        actual = {str(path.relative_to(local_output)): digest(path)
                  for path in local_output.rglob("*") if path.is_file()
                  and path.name not in {"collection-receipt.json", "healthy-summary.json"}}
        if actual != expected:
            raise ValueError("existing v10 collection differs from remote evidence")
    receipt = {"schema_version": 1, "case_ids": list(cohort["case_ids"]),
               "cohort": cohort["name"],
               "batch_result_sha256": expected["batch-result.json"],
               "remote_files_verified": len(expected), "remote_root": cohort["remote"]}
    (local_output / "collection-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summarizer = REPO / "Mallory/adapters/solr/summarize_calibration.py"
    for case_id in receipt["case_ids"]:
        campaign = local_output / case_id
        if ((campaign / "trials/r0000/result.json").is_file()
                and (campaign / "trials/r0000/pilot-result.json").is_file()):
            subprocess.run([sys.executable, str(summarizer), str(campaign),
                            "--out", str(campaign / "healthy-summary.json")], check=True)
    print("v10 " + cohort["name"] + " evidence SHA-synced: " + str(local_output), flush=True)


def main() -> int:
    previous = None
    for cohort in COHORTS:
        while True:
            try:
                ready = (archived_and_audited() if previous is None else
                         (previous["local"] / "collection-receipt.json").is_file())
                prior_session = ("mallory-solr05-v4-junit" if previous is None
                                 else previous["session"])
                if (ready and not session_active(prior_session)
                        and not session_active(cohort["session"]) and lane_free()):
                    command = ("tmux new-session -d -s " + cohort["session"]
                               + " 'python3 " + REMOTE_BATCH + " --cohort " + cohort["name"]
                               + " > " + cohort["remote"] + ".log 2>&1'")
                    started = ssh(command)
                    if started.returncode:
                        raise RuntimeError("could not launch v10 batch: " + started.stderr.strip())
                    print("launched " + cohort["session"], flush=True)
                    break
                print("waiting for verified prior cohort and free lane1: "
                      + cohort["name"], flush=True)
            except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
                print("waiter retry: " + str(error), flush=True)
            time.sleep(30)
        while True:
            if batch_terminal(cohort):
                try:
                    collect(cohort)
                    break
                except (OSError, ValueError, json.JSONDecodeError, RuntimeError,
                        subprocess.CalledProcessError) as error:
                    print("v10 collection retry: " + str(error), flush=True)
            if not session_active(cohort["session"]):
                if not batch_terminal(cohort):
                    raise RuntimeError("v10 batch exited without terminal result; inspect "
                                       + cohort["remote"] + ".log")
            time.sleep(30)
        previous = cohort
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
