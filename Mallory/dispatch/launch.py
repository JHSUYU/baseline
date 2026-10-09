"""Launch each disjoint Mallory shard in a durable local tmux session."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

try:
    from .scheduler import DEFAULT_KEY, ssh_prefix
except ImportError:
    from scheduler import DEFAULT_KEY, ssh_prefix


HOSTS = ("node0", "node1", "node2")


def scheduler_argv(host: str, phase: str, cohort: str = "",
                   case_config_template: str = "Mallory/cases/{case_id}.json",
                   lane_id: str = "", core_release_manifest: str = "") -> list[str]:
    suffix = f"-{cohort}" if cohort else ""
    command = ["python3", "Mallory/dispatch/scheduler.py",
            "--manifest", f"Mallory/dispatch/shards/{host}.json",
            "--hosts-file", f"Mallory/dispatch/shards/{host}-hosts.json",
            "--inventory", "Mallory/cases/inventory.json",
            "--case-config-template", case_config_template,
            "--source-reference", "Mallory/dispatch/source_reference.json",
            "--phase", phase,
            "--state-root", f"data/mallory/dispatch/{host}{suffix}",
            "--scratch-root", f"/tmp/mallory-scratch/{host}",
            "--build-root", f"/tmp/mallory-build/{host}",
            "--max-parallel", "1"]
    if cohort:
        command.extend(["--calibration-output-root", f"data/mallory/calibration_{cohort}"])
    if lane_id:
        command.extend(["--lane-id", lane_id])
    if core_release_manifest:
        command.extend(["--core-release-manifest", core_release_manifest])
    return command


def on_host(host: str, key: Path, argv: list[str], cwd: Path,
            timeout: int = 180) -> subprocess.CompletedProcess:
    if host == "node0":
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    endpoint = {"name": host, "kind": "ssh", "address": f"ZhenyuLi@{host}"}
    script = shlex.join(["/bin/sh", "-lc", f"cd {shlex.quote(str(cwd))} && {shlex.join(argv)}"])
    return subprocess.run(ssh_prefix(endpoint, key) + [script],
                          capture_output=True, text=True, timeout=timeout)


def launch_one(host: str, phase: str, repo: Path, key: Path, apply: bool,
               cohort: str = "", case_config_template: str = "Mallory/cases/{case_id}.json",
               extra_artifacts: list[Path] | None = None,
               lane_id: str = "", skip_stage: bool = False,
               core_release_manifest: str = "") -> bool:
    suffix = f"-{cohort}" if cohort else ""
    name = f"mallory-{host}-{phase}{suffix}" + (f"-{lane_id}" if lane_id else "")
    command = scheduler_argv(host, phase, cohort, case_config_template,
                             lane_id, core_release_manifest)
    if core_release_manifest:
        release_root = Path(core_release_manifest).resolve().parent
        pythonpath = (str(release_root) + os.pathsep + str(repo) +
                      (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""))
        command = ["env", f"PYTHONPATH={pythonpath}", *command]
    log = repo / f"data/mallory/dispatch/{host}{suffix}/{phase}.log"
    if not apply:
        print(f"{host}: tmux session {name}; {shlex.join(command)}")
        return True
    if host != "node0" and not skip_stage:
        stage_command = [sys.executable, str(repo / "Mallory/dispatch/stage.py"),
                         "--repo", str(repo), "--hosts", host, "--apply"]
        for artifact in extra_artifacts or []:
            stage_command.extend(["--extra-artifact", str(artifact)])
        staged = subprocess.run(stage_command,
                                capture_output=True, text=True, timeout=210)
        if staged.returncode:
            print(f"{host}: stage failed: {staged.stderr.strip()}", file=sys.stderr)
            return False
        print(staged.stdout.strip(), flush=True)
    validation = on_host(host, key, command + ["--validate-only"], repo)
    print(validation.stdout.strip(), flush=True)
    if validation.returncode:
        print(f"{host}: preflight failed: {validation.stderr.strip()}", file=sys.stderr)
        return False
    present = on_host(host, key, ["tmux", "has-session", "-t", name], repo, timeout=15)
    if present.returncode == 0:
        print(f"{host}: existing tmux session {name}; leaving it running")
        return True
    if present.returncode != 1:
        print(f"{host}: tmux check failed: {present.stderr.strip()}", file=sys.stderr)
        return False
    created = on_host(host, key, ["mkdir", "-p", str(log.parent)], repo, timeout=15)
    if created.returncode:
        print(f"{host}: log directory creation failed: {created.stderr.strip()}", file=sys.stderr)
        return False
    shell_command = shlex.join(command) + " >> " + shlex.quote(str(log)) + " 2>&1"
    started = on_host(host, key, ["tmux", "new-session", "-d", "-s", name,
                                  "-c", str(repo), shell_command], repo, timeout=15)
    if started.returncode:
        print(f"{host}: tmux launch failed: {started.stderr.strip()}", file=sys.stderr)
        return False
    checked = on_host(host, key, ["tmux", "has-session", "-t", name], repo, timeout=15)
    if checked.returncode:
        print(f"{host}: session exited after launch; inspect {log}", file=sys.stderr)
        return False
    print(f"{host}: running in tmux {name}; log {log}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--hosts", nargs="+", default=list(HOSTS))
    parser.add_argument("--phase", choices=("calibration", "campaign"), default="calibration")
    parser.add_argument("--cohort", default="", help="version suffix such as v2 for recalibration")
    parser.add_argument("--case-config-template", default="Mallory/cases/{case_id}.json")
    parser.add_argument("--extra-artifact", type=Path, action="append", default=[])
    parser.add_argument("--lane-id", default="", help="host-local exclusive JVM lane")
    parser.add_argument("--core-release-manifest", default="",
                        help="immutable pinned core release required for fault campaigns")
    parser.add_argument("--skip-stage", action="store_true",
                        help="use separately SHA-verified live-safe selected staging")
    parser.add_argument("--apply", action="store_true", help="stage, preflight, and start tmux")
    args = parser.parse_args(argv)
    if args.cohort and (not args.cohort.isascii() or not args.cohort.isalnum()):
        parser.error("cohort must be ASCII letters and digits")
    if args.lane_id and (not args.lane_id.isascii() or
                         not all(c.isalnum() or c in "._-" for c in args.lane_id)):
        parser.error("lane ID must contain ASCII letters, digits, periods, underscores, or hyphens")
    for host in args.hosts:
        if host not in HOSTS:
            parser.error(f"invalid host: {host}")
    if args.skip_stage and args.extra_artifact:
        parser.error("--skip-stage cannot be combined with --extra-artifact")
    good = [launch_one(host, args.phase, args.repo.resolve(), args.ssh_key,
                       args.apply, args.cohort, args.case_config_template,
                       args.extra_artifact, args.lane_id,
                       args.skip_stage, args.core_release_manifest) for host in args.hosts]
    return 0 if all(good) else 2


if __name__ == "__main__":
    raise SystemExit(main())
