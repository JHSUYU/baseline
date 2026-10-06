#!/usr/bin/env python3
"""Node0-owned checklist coordinator for isolated JUnit workers.

Only node0's local filesystem stores this ledger. Node0 claims a case, pushes
its command through authenticated SSH to a worker tmux session, heartbeats the
central lease, and pulls the worker's artifacts back with rsync.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator


SCHEMA = 1
CASE_ID = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")
WORKER_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
TERMINAL = {"quality_complete", "no_cluster_test", "source_excluded",
            "confirmed_bug"}
REVIEW = {"candidate_review"}
MIN_TTL = 1
MAX_TTL = 86400


def local_account() -> str:
    """Unix account authenticated by node0's SSH server or local scheduler."""
    return pwd.getpwuid(os.getuid()).pw_name


def require_case_id(value: str) -> str:
    if not CASE_ID.fullmatch(value):
        raise ValueError(f"invalid case id: {value!r}")
    return value


def require_worker(value: str) -> str:
    if not WORKER_ID.fullmatch(value):
        raise ValueError(f"invalid worker id: {value!r}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """O_EXCL temp file plus rename; readers see either complete JSON version."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def case_lock(directory: Path) -> Iterator[None]:
    """A short local ext3 critical section; never held during the trial."""
    fd = os.open(directory / ".coord.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("rows", value.get("checks"))
    if not isinstance(value, list):
        raise ValueError("manifest needs a JSON list or rows/checks list")
    seen: set[str] = set()
    result = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("manifest contains a non-object row")
        case_id = require_case_id(row.get("case_id", ""))
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        result.append(row)
    if not result:
        raise ValueError("empty checklist")
    return result


class Ledger:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.cases = self.root / "cases"

    def assert_owner(self) -> None:
        if not self.root.is_dir() or not self.cases.is_dir():
            raise ValueError(f"ledger not initialized: {self.root}")
        if self.root.stat().st_uid != os.getuid():
            raise PermissionError("ledger must be accessed by its owning Unix user")

    def directory(self, case_id: str) -> Path:
        directory = self.cases / require_case_id(case_id)
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"unknown case: {case_id}")
        return directory

    def manifest(self) -> list[dict[str, Any]]:
        self.assert_owner()
        return read_json(self.root / "manifest.json")["rows"]

    def initialize(self, manifest_path: Path) -> dict[str, Any]:
        rows = load_manifest(manifest_path)
        if self.root.exists() and self.root.stat().st_uid != os.getuid():
            raise PermissionError("existing ledger is owned by another Unix user")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cases.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(self.cases, 0o700)
        manifest_file = self.root / "manifest.json"
        if manifest_file.exists():
            old = read_json(manifest_file)["rows"]
            if [r["case_id"] for r in old] != [r["case_id"] for r in rows]:
                raise ValueError("initialized checklist differs; use another ledger root")
        else:
            atomic_json(manifest_file, {"schema_version": SCHEMA, "rows": rows})
        created = 0
        for row in rows:
            directory = self.cases / row["case_id"]
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                if not directory.is_dir() or directory.is_symlink():
                    raise ValueError(f"invalid case directory: {directory}")
            record_file = directory / "coord.json"
            with case_lock(directory):
                if record_file.exists():
                    continue
                status = row.get("status")
                if status not in TERMINAL and status not in REVIEW:
                    status = "pending"
                atomic_json(record_file, {
                    "schema_version": SCHEMA, "case_id": row["case_id"],
                    "system": row.get("system", ""), "status": status,
                    "attempt": 0, "last_outcome": row.get("status"),
                    "updated_at": time.time(),
                })
                created += 1
        return {"cases": len(rows), "created": created, "root": str(self.root)}

    @staticmethod
    def _lease(directory: Path) -> dict[str, Any] | None:
        lease_dir = directory / "lease.d"
        if not lease_dir.exists():
            return None
        if not lease_dir.is_dir() or lease_dir.is_symlink():
            raise ValueError(f"invalid lease directory: {lease_dir}")
        lease_file = lease_dir / "owner.json"
        if lease_file.exists():
            return read_json(lease_file)
        # A process may have died between atomic mkdir and writing owner.json.
        return {"expires_at": lease_dir.stat().st_mtime + 60,
                "token": None, "orphaned": True}

    @staticmethod
    def _expire(directory: Path, lease: dict[str, Any]) -> None:
        stale = directory / f"lease.stale.{int(time.time())}.{uuid.uuid4().hex}.d"
        os.rename(directory / "lease.d", stale)

    def claim(self, worker: str, system: str | None = None,
              case_id: str | None = None, ttl: int = 180,
              exclude: set[str] | None = None) -> dict[str, Any]:
        require_worker(worker)
        if not MIN_TTL <= ttl <= MAX_TTL:
            raise ValueError(f"TTL must be between {MIN_TTL} and {MAX_TTL} seconds")
        rows = self.manifest()
        if case_id:
            require_case_id(case_id)
            rows = [row for row in rows if row["case_id"] == case_id]
            if not rows:
                raise ValueError(f"unknown case: {case_id}")
        if system:
            rows = [row for row in rows if row.get("system", "").lower().startswith(
                system.lower())]
        for row in rows:
            if row["case_id"] in (exclude or set()):
                continue
            directory = self.directory(row["case_id"])
            with case_lock(directory):
                record = read_json(directory / "coord.json")
                if record["status"] not in {"pending", "claimed"}:
                    continue
                lease = self._lease(directory)
                now = time.time()
                if lease and lease["expires_at"] > now:
                    continue
                if lease:
                    self._expire(directory, lease)
                os.mkdir(directory / "lease.d", 0o700)
                token = uuid.uuid4().hex
                attempt = int(record["attempt"]) + 1
                lease = {"schema_version": SCHEMA, "case_id": row["case_id"],
                         "token": token, "worker": worker, "attempt": attempt,
                         "started_at": now, "heartbeat_at": now,
                         "expires_at": now + ttl, "ttl_seconds": ttl,
                         "authenticated_user": local_account(),
                         "auth_source": "ssh" if os.environ.get("SSH_CONNECTION") else "local",
                         "ssh_connection": os.environ.get("SSH_CONNECTION", ""),
                         "node0": socket.gethostname()}
                atomic_json(directory / "lease.d" / "owner.json", lease)
                record.update(status="claimed", attempt=attempt,
                              worker=worker, updated_at=now)
                atomic_json(directory / "coord.json", record)
                return {"claimed": True, "case_id": row["case_id"],
                        "system": row.get("system", ""), "attempt": attempt,
                        "lease_token": token, "expires_at": lease["expires_at"],
                        "case_dir": str(directory), "check": row}
        return {"claimed": False, "reason": "no_available_case"}

    def _owned_lease(self, directory: Path, token: str) -> dict[str, Any]:
        lease = self._lease(directory)
        if lease is None or lease.get("token") != token:
            raise ValueError("lease token does not own this case")
        if lease["expires_at"] <= time.time():
            raise ValueError("lease expired; claim the case again")
        return lease

    def remote_job(self, case_id: str, token: str,
                   new_job: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Read or install tmux metadata while the caller owns the lease."""
        self.assert_owner()
        directory = self.directory(case_id)
        with case_lock(directory):
            self._owned_lease(directory, token)
            record = read_json(directory / "coord.json")
            if new_job is not None:
                record["remote_job"] = new_job
                record["updated_at"] = time.time()
                atomic_json(directory / "coord.json", record)
            return record.get("remote_job")

    def clear_remote_job(self, case_id: str, token: str) -> None:
        directory = self.directory(case_id)
        with case_lock(directory):
            self._owned_lease(directory, token)
            record = read_json(directory / "coord.json")
            record.pop("remote_job", None)
            atomic_json(directory / "coord.json", record)

    def heartbeat(self, case_id: str, token: str) -> dict[str, Any]:
        self.assert_owner()
        directory = self.directory(case_id)
        with case_lock(directory):
            record = read_json(directory / "coord.json")
            if record["status"] != "claimed":
                raise ValueError("case is not an active claim")
            lease = self._owned_lease(directory, token)
            now = time.time()
            lease["heartbeat_at"] = now
            lease["expires_at"] = now + lease["ttl_seconds"]
            atomic_json(directory / "lease.d" / "owner.json", lease)
            return {"case_id": case_id, "attempt": lease["attempt"],
                    "expires_at": lease["expires_at"]}

    def complete(self, case_id: str, token: str, outcome: str,
                 result_file: Path | None) -> dict[str, Any]:
        self.assert_owner()
        directory = self.directory(case_id)
        if not outcome or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", outcome):
            raise ValueError(f"invalid outcome: {outcome!r}")
        if result_file is None and outcome != "retryable":
            raise ValueError("result file required; rsync artifacts to node0 first")
        result = None
        if result_file is not None:
            resolved = result_file.resolve(strict=True)
            if not resolved.is_relative_to(directory.resolve()):
                raise ValueError("result file must be inside this node0 case directory")
            result = read_json(resolved)
            if result.get("case_id") != case_id or result.get("status") != outcome:
                raise ValueError("result case_id/status does not match completion")
        with case_lock(directory):
            record = read_json(directory / "coord.json")
            if record["status"] != "claimed":
                raise ValueError("case is not an active claim")
            lease = self._owned_lease(directory, token)
            now = time.time()
            if result is not None:
                # Keep each synced attempt in artifacts; publish the latest
                # checklist result atomically for the central table.
                atomic_json(directory / "result.json", result)
            record.update(status=("pending" if outcome == "retryable" else outcome),
                          last_outcome=outcome, updated_at=now,
                          completed_at=(now if outcome != "retryable" else None),
                          result_file=(str(result_file) if result_file else None))
            if result is not None and outcome not in TERMINAL | REVIEW:
                # A complete but inconclusive run may be explored again.  A
                # transport failure leaves remote_job intact for resumption.
                record.pop("remote_job", None)
            atomic_json(directory / "coord.json", record)
            shutil.rmtree(directory / "lease.d")
            return {"case_id": case_id, "attempt": lease["attempt"],
                    "status": record["status"], "last_outcome": outcome}

    def resume(self, case_id: str, reason: str) -> dict[str, Any]:
        """Explicitly reopen a completed review/repair case after a change."""
        self.assert_owner()
        if not reason.strip():
            raise ValueError("resume needs a reason or adapter/config version")
        directory = self.directory(case_id)
        with case_lock(directory):
            record = read_json(directory / "coord.json")
            if record["status"] in {"pending", "claimed"} | TERMINAL:
                raise ValueError("only nonterminal review/repair cases can resume")
            if self._lease(directory) is not None:
                raise ValueError("case has a lease directory")
            record.setdefault("resume_history", []).append({
                "at": time.time(), "prior_status": record["status"],
                "reason": reason.strip()})
            record["status"] = "pending"
            record.pop("remote_job", None)
            record["updated_at"] = time.time()
            atomic_json(directory / "coord.json", record)
            return {"case_id": case_id, "status": "pending",
                    "attempt": record["attempt"]}

    def status(self) -> dict[str, Any]:
        rows = self.manifest()
        items = []
        counts: dict[str, int] = {}
        for row in rows:
            directory = self.directory(row["case_id"])
            with case_lock(directory):
                record = read_json(directory / "coord.json")
                lease = self._lease(directory)
            current = record["status"]
            if current == "claimed" and (lease is None or
                                         lease["expires_at"] <= time.time()):
                current = "expired"
            counts[current] = counts.get(current, 0) + 1
            items.append({"case_id": row["case_id"], "system": row.get("system"),
                          "status": current, "attempt": record["attempt"],
                          "last_outcome": record.get("last_outcome"),
                          "worker": record.get("worker") if current == "claimed" else None,
                          "remote_job": record.get("remote_job")})
        return {"root": str(self.root), "total": len(items),
                "counts": counts, "cases": items}


def ssh_base(identity_file: Path) -> list[str]:
    if not identity_file.is_file():
        raise ValueError(f"SSH identity file not found: {identity_file}")
    return ["ssh", "-i", str(identity_file), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"]


def remote_path(value: str) -> str:
    if not value.startswith("/") or value == "/" or "\n" in value or "\r" in value:
        raise ValueError(f"remote directory must be an absolute path: {value!r}")
    return value.rstrip("/")


def remote_command(template: list[str], replacements: dict[str, str]) -> list[str]:
    rendered = []
    for argument in template:
        if not isinstance(argument, str):
            raise ValueError("remote command JSON must contain only strings")
        for key, value in replacements.items():
            argument = argument.replace("{" + key + "}", value)
        rendered.append(argument)
    if not rendered:
        raise ValueError("remote command cannot be empty")
    return rendered


def ssh_command(ssh: list[str], destination: str, arguments: list[str],
                *, input_text: str | None = None) -> str:
    result = subprocess.run([*ssh, destination, shlex.join(arguments)],
                            input=input_text, capture_output=True, text=True,
                            check=True)
    return result.stdout


def remote_job_state(ssh: list[str], destination: str,
                     job: dict[str, Any]) -> tuple[str, int | None]:
    exit_file = shlex.quote(job["exit_file"])
    session = shlex.quote(job["session"])
    probe = (f"if test -f {exit_file}; then printf 'done:'; cat {exit_file}; "
             f"elif tmux has-session -t {session} 2>/dev/null; "
             "then echo running; else echo missing; fi")
    result = subprocess.run([*ssh, destination, probe],
                            capture_output=True, text=True, check=True)
    output = result.stdout.strip()
    if output.startswith("done:"):
        return "done", int(output[5:])
    if output in {"running", "missing"}:
        return output, None
    raise ValueError(f"unexpected tmux probe output: {output!r}")


def launch_tmux_job(ssh: list[str], destination: str,
                    command: list[str], job: dict[str, Any]) -> None:
    meta = job["meta_dir"]
    ssh_command(ssh, destination, ["mkdir", "-p", meta])
    script_file = f"{meta}/run.sh"
    log_file = f"{meta}/run.log"
    exit_file = job["exit_file"]
    # The wrapper is durable on the worker.  The completed marker is renamed
    # into place only after the original workload process exits.
    script = ("#!/usr/bin/env bash\n"
              "set +e\n"
              "set -o pipefail\n"
              f"{shlex.join(command)} 2>&1 | tee {shlex.quote(log_file)}\n"
              "rc=${PIPESTATUS[0]}\n"
              f"printf '%s\\n' \"$rc\" > {shlex.quote(exit_file + '.tmp')}\n"
              f"mv -- {shlex.quote(exit_file + '.tmp')} {shlex.quote(exit_file)}\n"
              "exit \"$rc\"\n")
    ssh_command(ssh, destination, ["tee", script_file], input_text=script)
    ssh_command(ssh, destination,
                ["tmux", "new-session", "-d", "-s", job["session"],
                 shlex.join(["bash", script_file])])


def dispatch(ledger: Ledger, *, host: str, remote_root: str,
             command_template: list[str], identity_file: Path,
             payload_dir: Path | None = None,
             remote_payload_dir: str | None = None,
             case_id: str | None = None, system: str | None = None,
             ttl: int = 180, max_cases: int = 1,
             sync_profile: str = "summary", sync_max_mib: int = 32) -> dict[str, Any]:
    """Node0 pushes a worker command, renews the lease, then pulls artifacts.

    The SSH private key stays on node0.  The worker does not write the central
    ledger, and a disconnected scheduler leaves an expiring resumable claim.
    """
    if host not in {"node1", "node2"}:
        raise ValueError("remote host must be node1 or node2")
    if max_cases < 1:
        raise ValueError("max_cases must be at least one")
    if sync_profile not in {"summary", "trace"} or not 1 <= sync_max_mib <= 1024:
        raise ValueError("sync profile must be summary/trace and max MiB 1..1024")
    remote_root = remote_path(remote_root)
    if payload_dir is not None:
        if not payload_dir.is_dir() or remote_payload_dir is None:
            raise ValueError("payload_dir needs a directory and remote_payload_dir")
        remote_payload_dir = remote_path(remote_payload_dir)
    ssh = ssh_base(identity_file)
    # rsync -s protects the remote path from shell interpretation.  The
    # transport command contains only node0's own SSH binary and key path.
    transport = shlex.join(ssh)
    completed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _ in range(max_cases):
        claim = ledger.claim(host, system=system, case_id=case_id,
                             ttl=ttl, exclude=seen)
        if not claim["claimed"]:
            break
        case = claim["case_id"]
        seen.add(case)
        central_attempt = (ledger.directory(case) / "artifacts" /
                           f"attempt-{claim['attempt']:03d}")
        central_attempt.mkdir(parents=True, exist_ok=True)
        stop = threading.Event()
        heartbeat_errors: list[str] = []
        heartbeats: list[float] = []

        def keep_lease() -> None:
            while not stop.wait(max(1, min(ttl / 3, 30))):
                try:
                    ledger.heartbeat(case, claim["lease_token"])
                    heartbeats.append(time.time())
                except (OSError, ValueError) as exc:
                    heartbeat_errors.append(str(exc))
                    return

        renewer = threading.Thread(target=keep_lease, daemon=True)
        renewer.start()
        started = time.time()
        remote_exit = None
        outcome = "retryable"
        error = None
        actual_host = host
        session = None
        reused_remote_job = False
        evidence = None
        try:
            job = ledger.remote_job(case, claim["lease_token"])
            if job:
                actual_host = job["host"]
                if actual_host not in {"node1", "node2"}:
                    raise ValueError(f"invalid stored remote host: {actual_host}")
                destination = f"{local_account()}@{actual_host}"
                state, remote_exit = remote_job_state(ssh, destination, job)
                reused_remote_job = state in {"running", "done"}
                if state == "missing":
                    job = None
            if job is None:
                actual_host = host
                destination = f"{local_account()}@{actual_host}"
                remote_case = f"{remote_root}/{case}"
                meta = (f"{remote_case}/.coord/attempt-{claim['attempt']:03d}-"
                        f"{claim['lease_token'][:8]}")
                session = (f"adhoc_{case.replace('-', '_')}_a{claim['attempt']}_"
                           f"{claim['lease_token'][:8]}")
                job = {"host": actual_host, "case_dir": remote_case,
                       "remote_root": remote_root, "meta_dir": meta,
                       "exit_file": f"{meta}/exit.code", "session": session,
                       "attempt": claim["attempt"], "created_at": time.time()}
                # Persist the session identity before the launch.  A crashed
                # node0 dispatcher can then probe it rather than rerun it.
                ledger.remote_job(case, claim["lease_token"], job)
                mkdir_args = ["mkdir", "-p", remote_case]
                if remote_payload_dir is not None:
                    mkdir_args.append(remote_payload_dir)
                ssh_command(ssh, destination, mkdir_args)
                if payload_dir is not None:
                    subprocess.run(["rsync", "-a", "-s", "-e", transport,
                                    str(payload_dir) + "/",
                                    f"{destination}:{remote_payload_dir}/"],
                                   check=True, capture_output=True, text=True)
                replacements = {"case_id": case, "remote_root": remote_root,
                                "remote_case_dir": remote_case,
                                "remote_payload_dir": remote_payload_dir or ""}
                command = remote_command(command_template, replacements)
                launch_tmux_job(ssh, destination, command, job)
            else:
                session = job["session"]
                remote_case = job["case_dir"]

            while True:
                state, remote_exit = remote_job_state(ssh, destination, job)
                if state == "done":
                    break
                if state == "missing":
                    raise ValueError(f"tmux session vanished without exit marker: {session}")
                time.sleep(2)
            helper = Path(__file__).with_name("evidence_sync_remote.py")
            remote_helper = f"{remote_case}/.coord/evidence_sync_remote.py"
            remote_stage = (f"{remote_case}/.coord/evidence-"
                            f"{claim['attempt']:03d}-{claim['lease_token'][:8]}")
            ssh_command(ssh, destination, ["tee", remote_helper],
                        input_text=helper.read_text(encoding="utf-8"))
            evidence = json.loads(ssh_command(
                ssh, destination,
                ["python3", remote_helper, "--case-dir", remote_case,
                 "--stage-dir", remote_stage, "--profile", sync_profile,
                 "--max-bytes", str(sync_max_mib * 1024 * 1024)]))
            if (evidence.get("stage_dir") != remote_stage or
                    evidence.get("transferred_bytes", sync_max_mib * 1024 * 1024 + 1)
                    > sync_max_mib * 1024 * 1024):
                raise ValueError("remote evidence stage path or byte budget mismatch")
            subprocess.run(["rsync", "-a", "-s", "-e", transport,
                            f"{destination}:{remote_stage}/",
                            str(central_attempt) + "/"],
                           check=True, capture_output=True, text=True)
            synced_manifest = read_json(central_attempt / "evidence-manifest.json")
            if synced_manifest.get("source_case_dir") != remote_case:
                raise ValueError("synced evidence manifest has wrong remote case path")
            result_file = central_attempt / "result.json"
            if remote_exit != 0:
                error = f"remote command exited {remote_exit}"
                ledger.clear_remote_job(case, claim["lease_token"])
                ledger.complete(case, claim["lease_token"], "retryable", None)
            elif result_file.is_file():
                result = read_json(result_file)
                outcome = str(result.get("status", ""))
                if not outcome:
                    raise ValueError(f"missing result status: {result_file}")
                ledger.complete(case, claim["lease_token"], outcome, result_file)
            else:
                error = "remote trial produced no result.json"
                ledger.clear_remote_job(case, claim["lease_token"])
                ledger.complete(case, claim["lease_token"], "retryable", None)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            error = str(exc)
            try:
                ledger.complete(case, claim["lease_token"], "retryable", None)
            except (OSError, ValueError) as lease_exc:
                error += f"; lease completion failed: {lease_exc}"
        finally:
            stop.set()
            renewer.join(timeout=2)
            record = {"case_id": case, "attempt": claim["attempt"],
                      "host": actual_host, "session": session,
                      "reused_remote_job": reused_remote_job,
                      "remote_exit": remote_exit,
                      "outcome": outcome, "error": error,
                      "sync_profile": sync_profile,
                      "evidence": evidence,
                      "remote_full_artifacts": remote_case if session else None,
                      "heartbeats": len(heartbeats),
                      "heartbeat_errors": heartbeat_errors,
                      "elapsed_seconds": round(time.time() - started, 3)}
            atomic_json(central_attempt / "dispatch.json", record)
            completed.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)
    return {"host": host, "processed": len(completed), "cases": completed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--manifest", type=Path, required=True)
    claim = commands.add_parser("claim")
    claim.add_argument("--root", type=Path, required=True)
    claim.add_argument("--worker", required=True)
    claim.add_argument("--system")
    claim.add_argument("--case-id")
    claim.add_argument("--ttl-seconds", type=int, default=180)
    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--root", type=Path, required=True)
    heartbeat.add_argument("--case-id", required=True)
    heartbeat.add_argument("--token", required=True)
    complete = commands.add_parser("complete")
    complete.add_argument("--root", type=Path, required=True)
    complete.add_argument("--case-id", required=True)
    complete.add_argument("--token", required=True)
    complete.add_argument("--status", required=True)
    complete.add_argument("--result-file", type=Path)
    resume_parser = commands.add_parser("resume")
    resume_parser.add_argument("--root", type=Path, required=True)
    resume_parser.add_argument("--case-id", required=True)
    resume_parser.add_argument("--reason", required=True)
    status = commands.add_parser("status")
    status.add_argument("--root", type=Path, required=True)
    dispatch_parser = commands.add_parser("dispatch")
    dispatch_parser.add_argument("--root", type=Path, required=True)
    dispatch_parser.add_argument("--host", choices=["node1", "node2"], required=True)
    dispatch_parser.add_argument("--remote-root", required=True)
    dispatch_parser.add_argument("--command-json", type=Path, required=True,
                                 help="JSON string array; {case_id}, {remote_root}, "
                                      "{remote_case_dir}, {remote_payload_dir} expand")
    dispatch_parser.add_argument("--identity-file", type=Path,
                                 default=Path.home() / ".ssh/id_ed25519_nodes")
    dispatch_parser.add_argument("--payload-dir", type=Path)
    dispatch_parser.add_argument("--remote-payload-dir")
    dispatch_parser.add_argument("--case-id")
    dispatch_parser.add_argument("--system")
    dispatch_parser.add_argument("--ttl-seconds", type=int, default=180)
    dispatch_parser.add_argument("--max-cases", type=int, default=1)
    dispatch_parser.add_argument("--sync-profile", choices=["summary", "trace"],
                                 default="summary")
    dispatch_parser.add_argument("--sync-max-mib", type=int, default=32,
                                 help="hard per-case node0 evidence transfer cap")
    args = parser.parse_args(argv)
    ledger = Ledger(args.root)
    try:
        if args.command == "init":
            response = ledger.initialize(args.manifest)
        elif args.command == "claim":
            response = ledger.claim(args.worker, args.system, args.case_id,
                                    args.ttl_seconds)
        elif args.command == "heartbeat":
            response = ledger.heartbeat(args.case_id, args.token)
        elif args.command == "complete":
            response = ledger.complete(args.case_id, args.token, args.status,
                                       args.result_file)
        elif args.command == "resume":
            response = ledger.resume(args.case_id, args.reason)
        elif args.command == "dispatch":
            template = json.loads(args.command_json.read_text(encoding="utf-8"))
            if not isinstance(template, list):
                raise ValueError("command JSON must be a string array")
            response = dispatch(ledger, host=args.host,
                                remote_root=args.remote_root,
                                command_template=template,
                                identity_file=args.identity_file,
                                payload_dir=args.payload_dir,
                                remote_payload_dir=args.remote_payload_dir,
                                case_id=args.case_id, system=args.system,
                                ttl=args.ttl_seconds, max_cases=args.max_cases,
                                sync_profile=args.sync_profile,
                                sync_max_mib=args.sync_max_mib)
        else:
            response = ledger.status()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(response, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
