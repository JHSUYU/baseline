"""Collect terminal remote Mallory summaries and dispatcher receipts on node0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tarfile

try:
    from .scheduler import DEFAULT_KEY, ssh_prefix
    from .worker import atomic_json
except ImportError:
    from scheduler import DEFAULT_KEY, ssh_prefix
    from worker import atomic_json


REMOTE_SCAN = r'''
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
host=sys.argv[2]
cohort=sys.argv[3]
suffix='-'+cohort if cohort else ''
dispatch_subdir=sys.argv[4] if len(sys.argv)>4 else host+suffix
calibration='calibration_'+cohort if cohort else 'calibration'
ids=json.load(sys.stdin)
rows=[]
for case_id in ids:
    for phase in ('calibration','campaign'):
        summary=(root/calibration/case_id/'result.json' if phase=='calibration'
                 else root/'cases'/case_id/'result.json')
        dispatch=root/'dispatch'/dispatch_subdir/phase/'cases'/case_id/'result.json'
        if not summary.is_file() or not dispatch.is_file():
            continue
        try:
            result=json.loads(summary.read_text())
            receipt=json.loads(dispatch.read_text())
        except (OSError,ValueError):
            continue
        terminal=(('calibration_complete','healthy_seed_invalid',
                   'healthy_node_identity_missing','healthy_seed_ambiguous',
                   'healthy_no_injectable_door','healthy_attestation_failed') if phase=='calibration' else
                  ('budget_exhausted','queue_exhausted','healthy_seed_invalid',
                   'healthy_node_identity_missing','healthy_seed_ambiguous',
                   'healthy_no_injectable_door','healthy_attestation_failed',
                   'fault_trials_not_attested'))
        if (result.get('case_id')!=case_id or receipt.get('case_id')!=case_id
            or result.get('status') not in terminal
            or receipt.get('status') not in ('command_succeeded','command_failed')
            or not receipt.get('scientific_completed')
            or result.get('last_dispatch_attempt_id')!=receipt.get('attempt_id')):
            continue
        if phase=='campaign':
            # The owner-host lane finalizer archives and audits this result.
            # Wait for it to finish before node0 scans/copies the case.  This
            # keeps a second collector from racing its archive receipt write.
            audit_path=summary.parent/'offline-causal-audit.json'
            try:
                audit=json.loads(audit_path.read_text())
            except (OSError,ValueError):
                continue
            archive_receipt=result.get('evidence_archive') or {}
            if (not archive_receipt.get('sha256') or
                audit.get('campaign_result_sha256') !=
                    hashlib.sha256(summary.read_bytes()).hexdigest()):
                continue
        attempt=receipt['attempt_id']
        attempt_dir=root/'dispatch'/dispatch_subdir/phase/'cases'/case_id/'attempts'/attempt
        exit_file=attempt_dir/'exit.json'
        spec_file=attempt_dir/'spec.json'
        if not exit_file.is_file() or not spec_file.is_file():
            continue
        try:
            exit_receipt=json.loads(exit_file.read_text())
            spec=json.loads(spec_file.read_text())
        except (OSError,ValueError):
            continue
        if (exit_receipt.get('attempt_id')!=attempt or exit_receipt.get('case_id')!=case_id
            or exit_receipt.get('host')!=host or spec.get('attempt_id')!=attempt
            or spec.get('case_id')!=case_id or spec.get('host')!=host):
            continue
        files=[summary,dispatch,exit_file,spec_file]
        rows.append({'case_id':case_id,'phase':phase,'attempt_id':attempt,
                     'summary_archive_sha256':(result.get('evidence_archive') or {}).get('sha256'),
                     'core_release_id':spec.get('core_release_id'),
                     'files':{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in files}})
print(json.dumps(rows))
'''


def scan(host: dict, key: Path, root: Path, case_ids: list[str], cohort: str = "",
         dispatch_subdir: str | None = None) -> list[dict]:
    dispatch_subdir = dispatch_subdir or (host["name"] + ("-" + cohort if cohort else ""))
    command = ssh_prefix(host, key) + [shlex.join(["python3", "-c", REMOTE_SCAN,
                                                  str(root), host["name"], cohort,
                                                  dispatch_subdir])]
    result = subprocess.run(command, input=json.dumps(case_ids), capture_output=True,
                            text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"{host['name']}: scan failed: {result.stderr.strip()[:300]}")
    return json.loads(result.stdout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def attempt_provenance(spec_path: Path, case_id: str, attempt_id: str,
                       host: str, expected_release_id: str | None = None) -> dict:
    """Bind a terminal result to the exact worker specification and core release."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if (spec.get("case_id") != case_id or spec.get("attempt_id") != attempt_id
            or spec.get("host") != host):
        raise RuntimeError("worker specification differs from terminal attempt")
    release_id = spec.get("core_release_id")
    if release_id != expected_release_id:
        raise RuntimeError("worker core release differs from scanned receipt")
    if release_id:
        manifest_path = Path(spec["core_release_manifest"])
        try:
            from .core_release import verify as verify_core_release
        except ImportError:
            from core_release import verify as verify_core_release
        release = verify_core_release(manifest_path)
        if release["release_id"] != release_id:
            raise RuntimeError("worker core release manifest differs from specification")
    return {"attempt_id": attempt_id, "host": host,
            "spec_path": str(spec_path), "spec_sha256": sha256(spec_path),
            "core_release_id": release_id,
            "case_config_sha256": spec.get("case_config_sha256")}


def materialize_campaign_evidence(case_dir: Path, archive_path: Path,
                                  manifest_path: Path) -> None:
    """Install verified raw evidence beside the node0 summary for offline replay.

    The archive contains the original remote result.  The node0 result has an
    additional evidence-archive receipt, so that one member is deliberately
    left untouched.  Existing evidence may only be reused if its bytes agree.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("archive_sha256") != sha256(archive_path):
        raise RuntimeError("campaign evidence archive hash changed")
    expected = manifest.get("members")
    if not isinstance(expected, list) or len(expected) != len(set(expected)):
        raise RuntimeError("campaign evidence manifest has duplicate or missing members")
    with tarfile.open(archive_path, "r:gz") as packed:
        members = packed.getmembers()
        if set(member.name for member in members) != set(expected):
            raise RuntimeError("campaign archive members differ from manifest")
        if sum(member.size for member in members if member.name != "result.json") > (
                shutil.disk_usage(case_dir).free - 3 * 1024**3):
            raise RuntimeError("insufficient node0 disk reserve for raw campaign evidence")
        for member in members:
            relative = Path(member.name)
            if (not member.isfile() or relative.is_absolute() or
                    any(part in ("", ".", "..") for part in relative.parts)):
                raise RuntimeError(f"unsafe campaign archive member: {member.name}")
            if member.name == "result.json":
                if sha256(case_dir / "result.json") == manifest["source_result_sha256"]:
                    continue
                # The node0 summary is augmented with an evidence receipt.
                summary = json.loads((case_dir / "result.json").read_text(encoding="utf-8"))
                if summary.get("evidence_archive", {}).get("sha256") != manifest["archive_sha256"]:
                    raise RuntimeError("node0 summary is not bound to the archive")
                continue
            destination = case_dir / relative
            if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents
                                               if case_dir in parent.parents or parent == case_dir):
                raise RuntimeError(f"campaign evidence path contains a symlink: {member.name}")
            source = packed.extractfile(member)
            if source is None:
                raise RuntimeError(f"campaign evidence cannot be read: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".mallory-evidence-", dir=destination.parent,
                                             delete=False) as temporary:
                staged = Path(temporary.name)
                try:
                    shutil.copyfileobj(source, temporary, 1024 * 1024)
                except BaseException:
                    staged.unlink(missing_ok=True)
                    raise
            if destination.is_file():
                if sha256(destination) != sha256(staged):
                    staged.unlink(missing_ok=True)
                    raise RuntimeError(f"existing campaign evidence differs: {member.name}")
                staged.unlink()
            else:
                os.replace(staged, destination)


def audit_synced_campaign(repo: Path, case_dir: Path, archive_path: Path,
                          manifest_path: Path,
                          core_release_manifest: Path | None = None) -> bool:
    """Replay the immutable terminal evidence; exit 2 means scientific failure."""
    audit_path = case_dir / "offline-causal-audit.json"
    summary_path = case_dir / "result.json"
    if core_release_manifest:
        try:
            from .core_release import verify as verify_core_release
        except ImportError:
            from core_release import verify as verify_core_release
        verify_core_release(core_release_manifest)
    core_root = core_release_manifest.parent if core_release_manifest else repo
    current_core = {name: sha256(core_root / "Mallory/core" / name)
                    for name in ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
    if audit_path.is_file():
        try:
            existing = json.loads(audit_path.read_text(encoding="utf-8"))
            if (existing.get("campaign_result_sha256") == sha256(summary_path)
                    and existing.get("core_source_sha256") == current_core):
                return False
        except (OSError, ValueError):
            pass
    materialize_campaign_evidence(case_dir, archive_path, manifest_path)
    environment = os.environ.copy()
    if core_release_manifest:
        environment["PYTHONPATH"] = (str(core_root) + os.pathsep + str(repo) +
                                     (os.pathsep + environment["PYTHONPATH"]
                                      if environment.get("PYTHONPATH") else ""))
    completed = subprocess.run([sys.executable, "-m", "Mallory.core.audit",
                                "--campaign", str(case_dir), "--out", str(audit_path)],
                               cwd=repo, env=environment,
                               capture_output=True, text=True, timeout=1800)
    if completed.returncode not in (0, 2) or not audit_path.is_file():
        raise RuntimeError(f"offline causal audit could not run: {completed.stderr.strip()[:300]}")
    artifact = json.loads(audit_path.read_text(encoding="utf-8"))
    if (artifact.get("campaign_result_sha256") != sha256(summary_path)
            or artifact.get("core_source_sha256") != current_core
            or artifact.get("report_gate_passed") != (completed.returncode == 0)):
        raise RuntimeError("offline causal audit receipt is inconsistent")
    print(f"{case_dir.name}: offline causal audit "
          f"{'passed' if completed.returncode == 0 else 'failed'}")
    return True


def compact_synced_case(repo: Path, data_root: Path, case_id: str) -> None:
    """Keep the CLI's direct-script entry point compatible with package imports."""
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from Mallory.dispatch.compact import compact_case
    compact_case(data_root, case_id)


def archive_one(host: dict, key: Path, repo: Path, phase: str, case_id: str,
                cohort: str = "") -> dict:
    command = ssh_prefix(host, key) + [shlex.join([
        "python3", str(repo / "Mallory/dispatch/archive.py"),
        "--data-root", str(repo / "data/mallory"), "--phase", phase,
        "--case-id", case_id, "--cohort", cohort])]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise RuntimeError(f"{host['name']}: evidence archive failed for {case_id}: "
                           f"{result.stderr.strip()[:300]}")
    return json.loads(result.stdout)


def release_manifest_for(repo: Path, release_id: str | None) -> Path | None:
    if release_id is None:
        return None  # Preserve historical, explicitly unpinned runs.
    if not isinstance(release_id, str) or not re.fullmatch(r"[0-9a-f]{64}", release_id):
        raise RuntimeError("terminal worker core release ID is invalid")
    manifest = repo / "Mallory/dispatch/releases" / release_id / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError(f"terminal worker core release is not staged: {release_id}")
    return manifest


def collect_one(host: dict, repo: Path, key: Path, ownership: dict,
                cohort: str = "", dispatch_subdir: str | None = None) -> int:
    ids = sorted(case_id for case_id, owner in ownership["owner"].items()
                 if owner == host["name"])
    data = repo / "data/mallory"
    dispatch_subdir = dispatch_subdir or (host["name"] + ("-" + cohort if cohort else ""))
    ready = scan(host, key, data, ids, cohort, dispatch_subdir)
    if not ready:
        print(f"{host['name']}: no terminal results ready")
        return 0
    remaining = []
    audits_written = 0
    for row in ready:
        archive = archive_one(host, key, repo, row["phase"], row["case_id"], cohort)
        summary = ((f"calibration_{cohort}" if cohort else "calibration")
                   if row["phase"] == "calibration" else "cases")
        summary_path = f"{summary}/{row['case_id']}/result.json"
        if (archive["source_result_sha256"] != row["files"][summary_path]
                and row.get("summary_archive_sha256") != archive["archive_sha256"]):
            raise RuntimeError(f"{host['name']}: case changed during archive creation: {row['case_id']}")
        row["archive"] = archive
        row["files"][archive["archive_relative"]] = archive["archive_sha256"]
        row["files"][archive["manifest_relative"]] = archive["manifest_sha256"]
        existing = data / summary_path
        if existing.is_file():
            local = json.loads(existing.read_text(encoding="utf-8"))
            spec_rel = (f"dispatch/{dispatch_subdir}/"
                        f"{row['phase']}/cases/{row['case_id']}/attempts/"
                        f"{row['attempt_id']}/spec.json")
            if (local.get("evidence_archive", {}).get("sha256") == archive["archive_sha256"]
                    and local.get("last_dispatch_attempt_id") == row["attempt_id"]
                    and local.get("dispatch_provenance", {}).get("spec_sha256")
                    == row["files"][spec_rel]):
                if row["phase"] == "campaign":
                    audits_written += audit_synced_campaign(
                        repo, existing.parent, data / archive["archive_relative"],
                        data / archive["manifest_relative"],
                        release_manifest_for(repo, row.get("core_release_id")))
                    compact_synced_case(repo, data, row["case_id"])
                continue
        remaining.append(row)
    ready = remaining
    if not ready:
        print(f"{host['name']}: all terminal evidence already synced")
        return audits_written
    needed = sum(row["archive"]["archive_bytes"] for row in ready)
    if shutil.disk_usage(data).free < needed + 3 * 1024**3:
        raise RuntimeError(f"{host['name']}: insufficient node0 disk reserve for evidence archives")
    paths = sorted({path for row in ready for path in row["files"]})
    # The staging directory is on node0; remote source is read-only.
    staging = Path(tempfile.mkdtemp(prefix=f".mallory-collect-{host['name']}-", dir=data))
    try:
        ssh = shlex.join(["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes",
                          "-o", "BatchMode=yes", "-o", "ConnectTimeout=4"])
        command = ["rsync", "-az", "--checksum", "--files-from=-", "-e", ssh,
                   f"{host['address']}:{data}/", str(staging) + "/"]
        result = subprocess.run(command, input="\n".join(paths) + "\n",
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(f"{host['name']}: rsync failed: {result.stderr.strip()[:300]}")
        for row in ready:
            for relative, expected in row["files"].items():
                local = staging / relative
                if not local.is_file() or sha256(local) != expected:
                    raise RuntimeError(f"{host['name']}: copy hash mismatch: {relative}")
        for row in ready:
            for relative in row["files"]:
                source = staging / relative
                destination = data / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
            summary_dir = ((f"calibration_{cohort}" if cohort else "calibration")
                           if row["phase"] == "calibration" else "cases")
            summary = (data / summary_dir
                       / row["case_id"] / "result.json")
            result = json.loads(summary.read_text(encoding="utf-8"))
            archive = row["archive"]
            result["evidence_archive"] = {
                "path": archive["archive_relative"], "sha256": archive["archive_sha256"],
                "manifest_path": archive["manifest_relative"],
                "manifest_sha256": archive["manifest_sha256"],
                "bytes": archive["archive_bytes"]}
            spec_relative = next(path for path in row["files"] if path.endswith(
                f"/attempts/{row['attempt_id']}/spec.json"))
            result["dispatch_provenance"] = attempt_provenance(
                data / spec_relative, row["case_id"], row["attempt_id"],
                host["name"], row.get("core_release_id"))
            atomic_json(summary, result)
            if row["phase"] == "campaign":
                audits_written += audit_synced_campaign(
                    repo, summary.parent, data / archive["archive_relative"],
                    data / archive["manifest_relative"],
                    release_manifest_for(repo, row.get("core_release_id")))
                compact_synced_case(repo, data, row["case_id"])
        print(f"{host['name']}: collected {len(ready)} verified terminal cases")
        return len(ready) + audits_written
    finally:
        shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ownership", type=Path,
                        default=Path("Mallory/dispatch/shards/ownership.json"))
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--hosts", nargs="+", default=["node1", "node2"])
    parser.add_argument("--cohort", default="", help="version suffix such as v2")
    parser.add_argument("--dispatch-subdir", default="",
                        help="host-local dispatch state directory for an isolated lane")
    args = parser.parse_args(argv)
    if args.cohort and (not args.cohort.isascii() or not args.cohort.isalnum()):
        parser.error("cohort must be ASCII letters and digits")
    if (args.dispatch_subdir and (not args.dispatch_subdir.isascii()
            or not args.dispatch_subdir.replace("-", "").replace("_", "").isalnum()
            or ".." in args.dispatch_subdir)):
        parser.error("dispatch subdirectory must be one safe path component")
    if args.dispatch_subdir and len(args.hosts) != 1:
        parser.error("isolated dispatch subdirectory requires one host")
    repo = args.repo.resolve()
    ownership = json.loads(args.ownership.read_text(encoding="utf-8"))
    (repo / "data/mallory").mkdir(parents=True, exist_ok=True)
    collected = 0
    for name in args.hosts:
        if name not in ("node1", "node2"):
            parser.error(f"unexpected host {name!r}")
        host = {"name": name, "kind": "ssh", "address": f"ZhenyuLi@{name}"}
        try:
            collected += collect_one(host, repo, args.ssh_key, ownership, args.cohort,
                                     args.dispatch_subdir or None)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"{name}: collection failed: {exc}", file=sys.stderr)
            return 2
    if collected:
        result = subprocess.run([sys.executable, "-m", "Mallory.report.build"], cwd=repo)
        if result.returncode:
            print("result sync succeeded, but report regeneration failed", file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
