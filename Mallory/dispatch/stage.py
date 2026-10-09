"""Stage only Mallory source/config and the shaded Java agent on remote nodes."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import sys

try:
    from .scheduler import DEFAULT_KEY, ssh_prefix
except ImportError:
    from scheduler import DEFAULT_KEY, ssh_prefix


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_command(host: dict, key: Path, argv: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(ssh_prefix(host, key) + [shlex.join(argv)],
                          capture_output=True, text=True, timeout=timeout)


def remote_free_bytes(host: dict, key: Path, path: Path) -> int:
    script = "import shutil,sys; print(shutil.disk_usage(sys.argv[1]).free)"
    result = remote_command(host, key, ["python3", "-c", script, str(path)])
    if result.returncode:
        raise RuntimeError(f"{host['name']}: disk probe failed: {result.stderr.strip()}")
    return int(result.stdout.strip())


def remote_sha256(host: dict, key: Path, path: Path) -> str:
    result = remote_command(host, key, ["sha256sum", str(path)])
    if result.returncode:
        raise RuntimeError(f"{host['name']}: hash probe failed for {path}: {result.stderr.strip()}")
    return result.stdout.split()[0]


def rsync_argv(repo: Path, address: str, key: Path, agent_jar: Path) -> tuple[list[str], list[str]]:
    ssh = shlex.join(["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes",
                      "-o", "BatchMode=yes", "-o", "ConnectTimeout=4"])
    source = ["rsync", "-az", "--checksum", "--mkpath", "--exclude=target/",
              "--exclude=__pycache__/", "--exclude=*.pyc", "--exclude=.git/",
              "-e", ssh, str(repo / "Mallory") + "/",
              f"{address}:{repo / 'Mallory'}/"]
    jar = ["rsync", "-az", "--checksum", "--mkpath", "-e", ssh,
           str(agent_jar), f"{address}:{repo / 'Mallory/instrumentation/target/mallory-agent.jar'}"]
    return source, jar


def selected_files(repo: Path, paths: list[Path]) -> list[Path]:
    """Resolve a live-safe allowlist without following links out of Mallory."""
    allowed = repo / "Mallory"
    files = []
    for item in paths:
        path = (repo / item).resolve() if not item.is_absolute() else item.resolve()
        if not path.is_relative_to(allowed) or not path.exists():
            raise ValueError(f"selected stage path is missing or outside Mallory: {item}")
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        for candidate in candidates:
            if (candidate.is_file() and not candidate.is_symlink()
                    and "__pycache__" not in candidate.parts
                    and candidate.suffix != ".pyc"):
                files.append(candidate)
    return sorted(set(files))


def stage_selected(host: dict, repo: Path, key: Path, paths: list[Path],
                   min_free_bytes: int, apply: bool) -> None:
    files = selected_files(repo, paths)
    if not files:
        raise ValueError("selected stage paths contain no regular files")
    ssh = shlex.join(["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes",
                      "-o", "BatchMode=yes", "-o", "ConnectTimeout=4"])
    # --relative preserves paths below repo.  This mode stages only explicitly
    # named files; it cannot overwrite an in-flight campaign's runner/JAR.
    command = ["rsync", "-az", "--checksum", "--mkpath", "--relative", "-e", ssh,
               *(str(file.relative_to(repo)) for file in files),
               f"{host['address']}:{repo}/"]
    if not apply:
        print(f"{host['name']} selected ({len(files)} files): {shlex.join(command)}")
        return
    free = remote_free_bytes(host, key, repo)
    if free < min_free_bytes:
        raise RuntimeError(f"{host['name']}: {free} free bytes below stage threshold {min_free_bytes}")
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{host['name']}: selected rsync failed: {result.stderr.strip()}")
    for local in files:
        if sha256(local) != remote_sha256(host, key, local):
            raise RuntimeError(f"{host['name']}: selected stage SHA mismatch: {local}")
    remaining = remote_free_bytes(host, key, repo)
    if remaining < min_free_bytes:
        raise RuntimeError(f"{host['name']}: staged successfully but free space fell below threshold")
    print(f"{host['name']}: selected stage verified ({len(files)} files); "
          f"free={remaining / (1024 ** 3):.2f} GiB")


def stage_one(host: dict, repo: Path, key: Path, agent_jar: Path,
              min_free_bytes: int, apply: bool,
              extra_artifacts: list[Path] | None = None) -> None:
    code, jar = rsync_argv(repo, host["address"], key, agent_jar)
    extra_artifacts = extra_artifacts or []
    ssh = shlex.join(["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes",
                      "-o", "BatchMode=yes", "-o", "ConnectTimeout=4"])
    extras = []
    for artifact in extra_artifacts:
        source = artifact.resolve()
        if not source.is_relative_to(repo / "Mallory") or not source.is_file():
            raise ValueError(f"extra artifact must be an existing Mallory file: {artifact}")
        extras.append((source, ["rsync", "-az", "--checksum", "--mkpath", "-e", ssh,
                                str(source), f"{host['address']}:{source}"]))
    if not apply:
        print(f"{host['name']} code: {shlex.join(code)}")
        print(f"{host['name']} agent: {shlex.join(jar)}")
        for _, command in extras:
            print(f"{host['name']} extra: {shlex.join(command)}")
        return
    free = remote_free_bytes(host, key, repo)
    if free < min_free_bytes:
        raise RuntimeError(f"{host['name']}: {free} free bytes below stage threshold {min_free_bytes}")
    for command in (code, jar, *(command for _, command in extras)):
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError(f"{host['name']}: rsync failed: {result.stderr.strip()}")
    for relative in ("Mallory/dispatch/worker.py", "Mallory/dispatch/scheduler.py",
                     "Mallory/dispatch/source_reference.json", "Mallory/dispatch/shards/ownership.json",
                     "Mallory/core/campaign.py", "Mallory/cases/inventory.json",
                     "Mallory/instrumentation/target/mallory-agent.jar"):
        local = repo / relative
        if local.is_file() and sha256(local) != remote_sha256(host, key, local):
            raise RuntimeError(f"{host['name']}: staged file hash mismatch: {relative}")
    for local, _ in extras:
        if sha256(local) != remote_sha256(host, key, local):
            raise RuntimeError(f"{host['name']}: staged extra artifact hash mismatch: {local}")
    remaining = remote_free_bytes(host, key, repo)
    if remaining < min_free_bytes:
        raise RuntimeError(f"{host['name']}: staged successfully but free space fell below threshold")
    print(f"{host['name']}: staged and verified; free={remaining / (1024 ** 3):.2f} GiB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--agent-jar", type=Path)
    parser.add_argument("--hosts", nargs="+", default=["node1", "node2"])
    parser.add_argument("--min-free-gib", type=float, default=8)
    parser.add_argument("--extra-artifact", type=Path, action="append", default=[],
                        help="additional Mallory target artifact, preserved at same remote path")
    parser.add_argument("--selected", type=Path, action="append", default=[],
                        help="live-safe allowlist path under Mallory; bypass full source/JAR stage")
    parser.add_argument("--apply", action="store_true", help="perform rsync; default only prints commands")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    agent_jar = (args.agent_jar or repo / "Mallory/instrumentation/target/mallory-agent.jar").resolve()
    if not (repo / "Mallory/dispatch/worker.py").is_file() or not agent_jar.is_file():
        parser.error("Mallory worker and shaded agent jar must exist before staging")
    if args.min_free_gib <= 0:
        parser.error("min-free-gib must be positive")
    for name in args.hosts:
        if name not in ("node1", "node2"):
            parser.error(f"unexpected remote host {name!r}")
        host = {"name": name, "kind": "ssh", "address": f"ZhenyuLi@{name}"}
        try:
            if args.selected:
                if args.extra_artifact:
                    parser.error("--selected and --extra-artifact cannot be combined")
                stage_selected(host, repo, args.ssh_key, args.selected,
                               int(args.min_free_gib * 1024 ** 3), args.apply)
            else:
                stage_one(host, repo, args.ssh_key, agent_jar,
                          int(args.min_free_gib * 1024 ** 3), args.apply,
                          args.extra_artifact)
        except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as exc:
            print(f"{name}: unavailable: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
