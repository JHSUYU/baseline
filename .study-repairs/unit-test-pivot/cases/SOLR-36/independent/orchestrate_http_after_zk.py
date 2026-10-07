#!/usr/bin/env python3
"""Start the calibrated HTTP stage after the frozen ZK extension terminates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
RPC = HERE / "rpc-stage"
CAMPAIGN = HERE / "campaign"
SSH = ("ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "ZhenyuLi@node2")
ZK_SESSION = "solr36_37_zk_extend_128"
HTTP_SESSION = "solr36_37_http_fuzz"
MIRROR_SESSION = "solr36_37_http_mirror"
SEED_SESSION = "solr36_37_http_sender_seeds"


def remote(command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run((*SSH, command), text=True, capture_output=True,
                          check=check)


def remote_state() -> dict:
    path = CAMPAIGN / "state.json"
    return json.loads(remote("cat " + shlex.quote(str(path))).stdout)


def remote_session(name: str) -> bool:
    return remote("tmux has-session -t " + shlex.quote("=" + name),
                  check=False).returncode == 0


def local_session(name: str) -> bool:
    return subprocess.run(("tmux", "has-session", "-t", "=" + name),
                          capture_output=True).returncode == 0


def wait_for_zk() -> None:
    while True:
        state = remote_state()
        count = len(state["completed"])
        status = state["status"]
        print(f"ZK status={status} selected={count} active="
              f"{state['active']['number'] if state['active'] else None}", flush=True)
        if status == "running":
            if not remote_session(ZK_SESSION):
                raise RuntimeError("ZK checkpoint is running but its tmux exited")
            time.sleep(30)
            continue
        if status != "budget_complete" or count != 128 or state["active"] is not None:
            raise RuntimeError(f"ZK stopped at {status}/{count}; review before HTTP")
        for _ in range(12):
            if not remote_session(ZK_SESSION):
                return
            time.sleep(10)
        raise RuntimeError("ZK tmux remained active after terminal checkpoint")


def finalize_zk() -> None:
    subprocess.run((sys.executable, str(HERE / "finalize.py")), check=True,
                   timeout=600)
    for case_id in ("SOLR-36", "SOLR-37"):
        result = json.loads((HERE.parent.parent / case_id / "result.json").read_text())
        if result.get("unreviewed_exact_target_throw_trial_numbers"):
            raise RuntimeError(f"{case_id} has an unreviewed target exception")
        audit = result["campaign_final_audit"]
        if audit["fault_trials"] != 128:
            raise RuntimeError(f"{case_id} final audit is not at 128")


def freeze_zk() -> None:
    destination = CAMPAIGN / "milestone-0128"
    if destination.exists():
        raise RuntimeError("128-trial milestone already exists; inspect before restart")
    destination.mkdir()
    subprocess.run(("rsync", "-a", "-e",
                    "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes "
                    "-o IdentitiesOnly=yes -o BatchMode=yes",
                    "ZhenyuLi@node2:" + str(CAMPAIGN / "state.json"),
                    str(destination / "state.json")), check=True)
    files = ["state.json", "finalizer.done"]
    shutil.copy2(CAMPAIGN / "finalizer.done", destination / "finalizer.done")
    for case_id in ("SOLR-36", "SOLR-37"):
        for prefix in ("progress", "identity-audit", "final-audit"):
            name = f"{prefix}-{case_id}.json"
            shutil.copy2(CAMPAIGN / name, destination / name)
            files.append(name)
    manifest = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                for name in files}
    (destination / "sha256.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Frozen {destination}", flush=True)


def verify_frozen_zk() -> None:
    destination = CAMPAIGN / "milestone-0128"
    manifest = json.loads((destination / "sha256.json").read_text())
    if any(hashlib.sha256((destination / name).read_bytes()).hexdigest() != digest
           for name, digest in manifest.items()):
        raise RuntimeError("frozen 128-trial ZK milestone checksum mismatch")
    state = json.loads((destination / "state.json").read_text())
    if (state["status"] != "budget_complete" or len(state["completed"]) != 128
            or state["active"] is not None):
        raise RuntimeError("frozen ZK milestone is not terminal at 128")
    for case_id in ("SOLR-36", "SOLR-37"):
        result = json.loads((HERE.parent.parent / case_id / "result.json").read_text())
        if (result.get("unreviewed_exact_target_throw_trial_numbers")
                or result.get("campaign_final_audit", {}).get("fault_trials") != 128):
            raise RuntimeError(f"{case_id} frozen audit is not reviewable")


def verify_http_static_inputs() -> None:
    for relative in ("fuzz_rpc.py", "run_stages.py", "record_seeds.py",
                     "seed_audit.py", "solrsubshard-rpc-agent.jar",
                     "agent-build.json", "src/research/solrsubshard/Probe.java"):
        local_digest = hashlib.sha256((RPC / relative).read_bytes()).hexdigest()
        remote_digest = remote("sha256sum " + shlex.quote(str(RPC / relative)))
        if remote_digest.stdout.split()[0] != local_digest:
            raise RuntimeError(f"HTTP input differs on node2: {relative}")
    build = json.loads((RPC / "agent-build.json").read_text())
    if build["agent_sha256"] != hashlib.sha256(
            (RPC / "solrsubshard-rpc-agent.jar").read_bytes()).hexdigest():
        raise RuntimeError("HTTP sender-aware agent does not match build record")


def calibrate_http() -> None:
    if remote_session(SEED_SESSION):
        raise RuntimeError("HTTP sender calibration tmux already exists")
    command = ("cd " + shlex.quote(str(RPC))
               + " && python3 record_seeds.py >> sender-seeds.log 2>&1")
    remote("tmux new-session -d -s " + shlex.quote(SEED_SESSION)
           + " " + shlex.quote(command))
    for _ in range(180):
        if not remote_session(SEED_SESSION):
            break
        time.sleep(10)
    else:
        raise RuntimeError("HTTP sender calibration exceeded thirty minutes")
    report = json.loads(remote("cat " + shlex.quote(str(RPC / "seed-audit.json"))).stdout)
    build = json.loads((RPC / "agent-build.json").read_text())
    selection = json.loads(remote("cat " + shlex.quote(
        str(RPC / "seed-selection.json"))).stdout)
    if (len(report["runs"]) != 2
            or [run["run"] for run in report["runs"]] != selection["selected_runs"]
            or any(run["agent_sha256"] != build["agent_sha256"]
                   for run in report["runs"])
            or [run["trace_sha256"] for run in report["runs"]]
               != selection["trace_sha256"]
            or len(report["stable_exact_parent_child_command_families"]) < 4):
        raise RuntimeError("two original sender-aware JUnits did not calibrate")
    for name in ("seed-audit.json", "seed-selection.json"):
        subprocess.run(("rsync", "-a", "-e",
                        "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes "
                        "-o IdentitiesOnly=yes -o BatchMode=yes",
                        "ZhenyuLi@node2:" + str(RPC / name),
                        str(RPC / name)), check=True)
    print("Two sender-aware original JUnit seeds passed", flush=True)


def verify_http_inputs() -> None:
    verify_http_static_inputs()
    for name in ("seed-audit.json", "seed-selection.json"):
        local_seed = hashlib.sha256((RPC / name).read_bytes()).hexdigest()
        remote_seed = remote("sha256sum " + shlex.quote(str(RPC / name)))
        if remote_seed.stdout.split()[0] != local_seed:
            raise RuntimeError(f"HTTP calibrated {name} differs on node2")
    if remote_session(HTTP_SESSION) or local_session(MIRROR_SESSION):
        raise RuntimeError("HTTP stage tmux already exists; inspect before restart")
    if (RPC / "campaign" / "state.json").exists():
        raise RuntimeError("HTTP checkpoint already exists on node0")
    remote_checkpoint = remote("test -e " + shlex.quote(str(RPC / "campaign" / "state.json")),
                               check=False)
    if remote_checkpoint.returncode == 0:
        raise RuntimeError("HTTP checkpoint already exists on node2")


def launch_http() -> None:
    command = ("cd " + shlex.quote(str(RPC))
               + " && python3 run_stages.py"
               + " >> http-fuzz.log 2>&1")
    remote("tmux new-session -d -s " + shlex.quote(HTTP_SESSION)
           + " " + shlex.quote(command))
    for _ in range(30):
        if not remote_session(HTTP_SESSION):
            raise RuntimeError("HTTP tmux exited before its checkpoint appeared")
        ready = remote("test -s " + shlex.quote(str(RPC / "campaign" / "progress.json"))
                       + " && test -s "
                       + shlex.quote(str(RPC / "campaign" / "stage-status.json")),
                       check=False)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("HTTP tmux did not publish its initial checkpoint")
    subprocess.run(("tmux", "new-session", "-d", "-s", MIRROR_SESSION,
                    "cd " + shlex.quote(str(RPC))
                    + " && python3 mirror.py >> http-mirror.log 2>&1"), check=True)
    print(f"HTTP launched: node2 {HTTP_SESSION}; node0 {MIRROR_SESSION}", flush=True)


def main() -> None:
    if not (CAMPAIGN / "milestone-0128").exists():
        wait_for_zk()
        finalize_zk()
        freeze_zk()
    verify_frozen_zk()
    verify_http_static_inputs()
    calibrate_http()
    verify_http_inputs()
    launch_http()


if __name__ == "__main__":
    main()
