"""One system lane on one host; release inputs are verified before work."""

from __future__ import annotations

import argparse
import fcntl
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from Mallory.dispatch.graphchecker_port.plan import checkpoint_state, sha256


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _file_digest(path: Path) -> str:
    return sha256(path)


@functools.lru_cache(maxsize=16)
def verify_java8(configured_java: str) -> dict:
    """Check the exact executable named by a case, not the shell default."""
    executable = shutil.which(configured_java)
    if executable is None:
        raise ValueError(f"configured Java executable unavailable: {configured_java}")
    path = Path(executable).resolve()
    result = subprocess.run([str(path), "-version"], capture_output=True,
                            text=True, timeout=15)
    version = (result.stderr + "\n" + result.stdout).strip()
    if result.returncode or not re.search(r'\bversion "(?:1\.8\.|8(?:\.|\+|"))', version):
        raise ValueError(f"configured Java must be Java 8: {path}: {version[:200]}")
    return {"java_path": str(path), "java_sha256": sha256(path),
            "java_version": version.splitlines()[0]}


def classfile_major(content: bytes) -> int:
    if len(content) < 8 or content[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("invalid Java classfile header")
    return int.from_bytes(content[6:8], "big")


def _classpath_class(class_name: str, paths: list[Path]) -> bytes | None:
    relative = class_name.replace(".", "/") + ".class"
    for path in paths:
        if path.is_dir():
            candidate = path / relative
            if candidate.is_file():
                return candidate.read_bytes()
        elif path.is_file() and path.suffix == ".jar":
            with zipfile.ZipFile(path) as archive:
                try:
                    return archive.read(relative)
                except KeyError:
                    pass
    return None


def verify_input_classfiles(config: dict) -> dict:
    """Reject selected/test bytecode that the configured Java 8 cannot load."""
    manifest = json.loads(Path(config["weave_manifest"]).read_text(encoding="utf-8"))
    selected = {row["clazz"] for key in ("regions", "targets", "coverage", "frames", "doors")
                for row in manifest.get(key, []) if isinstance(row, dict)
                and isinstance(row.get("clazz"), str)}
    originals = list(config["original_class_dirs"])
    checked = 0
    for clazz in sorted(selected):
        content = _classpath_class(clazz, originals)
        if content is None:
            raise ValueError(f"selected original class absent: {clazz}")
        major = classfile_major(content)
        if major > 52:
            raise ValueError(f"selected original class requires Java >8: {clazz}: major {major}")
        checked += 1
    junit = config["junit"]["class"]
    test_content = _classpath_class(junit, [*originals, *config["test_classpath"]])
    if test_content is None:
        raise ValueError(f"JUnit class absent: {junit}")
    test_major = classfile_major(test_content)
    if test_major > 52:
        raise ValueError(f"JUnit class requires Java >8: {junit}: major {test_major}")
    return {"selected_class_count": checked, "junit_class_major": test_major}


def verify_release(document: dict, *, require_tmpfs: bool = True) -> dict:
    root = Path(document["release_root"])
    if root.is_symlink() or not root.is_dir() or (require_tmpfs and not _inside(root, Path("/dev/shm"))):
        raise ValueError("release must be an existing /dev/shm snapshot")
    expected = document.get("release_files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("release_files must pin every release file")
    if require_tmpfs and root.stat().st_mode & 0o222:
        raise ValueError("release directory is writable")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"release symlink refused: {path}")
        if require_tmpfs and path.is_dir() and path.stat().st_mode & 0o222:
            raise ValueError(f"writable release directory: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            actual.add(relative)
            if path.stat().st_mode & 0o222:
                raise ValueError(f"writable release input: {path}")
            if expected.get(relative) != _file_digest(path):
                raise ValueError(f"release hash mismatch: {path}")
    if actual != set(expected):
        raise ValueError("release manifest is missing or has extra files")
    return {"root": str(root), "files": len(actual)}


def verify_source(source: dict, *, require_tmpfs: bool = True) -> dict:
    root = Path(source["root"])
    if root.is_symlink() or not root.is_dir() or (require_tmpfs and not _inside(root, Path("/dev/shm"))):
        raise ValueError("source must be an existing /dev/shm snapshot")
    if require_tmpfs and root.stat().st_mode & 0o222:
        raise ValueError("source directory is writable")
    paths = source.get("paths")
    if not isinstance(paths, list) or not paths or paths != sorted(set(paths)):
        raise ValueError("source paths must be a sorted unique list")
    actual = set()
    digest = hashlib.sha256()
    for relative in paths:
        item = Path(relative)
        if item.is_absolute() or ".." in item.parts:
            raise ValueError("unsafe source path")
        path = root / item
        if path.is_symlink():
            if not _inside(path, root):
                raise ValueError(f"escaping source symlink: {path}")
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            if path.stat().st_mode & 0o222:
                raise ValueError(f"writable source input: {path}")
            payload = b"F" + bytes.fromhex(_file_digest(path))
        else:
            raise ValueError(f"missing source input: {path}")
        actual.add(item.as_posix())
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    # A staged source contains exactly the tracked reference files. An extra
    # class/resource could otherwise influence the JUnit classpath or build.
    all_files = set()
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            all_files.add(path.relative_to(root).as_posix())
        elif require_tmpfs and path.is_dir() and path.stat().st_mode & 0o222:
            raise ValueError(f"writable source directory: {path}")
    if all_files != actual or digest.hexdigest() != source.get("digest"):
        raise ValueError("source snapshot differs from pinned tracked files")
    return {"root": str(root), "files": len(paths), "digest": digest.hexdigest()}


def verify_inputs(document: dict, host: str, system: str,
                  *, require_tmpfs: bool = True,
                  validate_core: bool = False,
                  verify_runtime_files: bool = True) -> dict:
    if document.get("schema_version") != 1:
        raise ValueError("deployment schema must be 1")
    assignment = document.get("assignments", {}).get(system)
    if assignment != host:
        raise ValueError(f"{system} is not assigned to {host}")
    release = verify_release(document, require_tmpfs=require_tmpfs)
    if verify_runtime_files:
        required = ("Mallory/core/graphchecker_fuzzer.py",
                    "Mallory/core/graphchecker_campaign.py",
                    "Mallory/dispatch/graphchecker_port/lane.py")
        if any(relative not in document["release_files"] for relative in required):
            raise ValueError("release lacks pinned GraphChecker worker/core files")
    source = document.get("sources", {}).get(system)
    if not isinstance(source, dict):
        raise ValueError(f"missing source fingerprint for {system}")
    verified_source = verify_source(source, require_tmpfs=require_tmpfs)
    root = Path(document["release_root"])
    configs = document.get("configs")
    if not isinstance(configs, dict):
        raise ValueError("configs must be a case ID to path mapping")
    for case_id, config in configs.items():
        if not case_id.startswith(system.upper() + "-"):
            continue
        path = root / config
        if not _inside(path, root) or not path.is_file():
            raise ValueError(f"missing or escaping case config: {case_id}")
        if Path(config).as_posix() not in document["release_files"]:
            raise ValueError(f"unlisted case config: {case_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("case_id") != case_id:
            raise ValueError(f"case config identity mismatch: {case_id}")
        _verify_config_paths(raw, path, root, Path(source["root"]), case_id)
        if verify_runtime_files:
            verify_java8(raw.get("java", "java"))
        if validate_core:
            from Mallory.core.graphchecker_campaign import load_config
            from Mallory.core.graphchecker_fuzzer import _budget
            parsed = load_config(path)
            _budget(path)
            verify_input_classfiles(parsed)
    return {"host": host, "system": system,
            "release": release, "source": verified_source}


def _verify_config_paths(config: dict, config_path: Path, release: Path,
                         source: Path, case_id: str) -> None:
    """Reject configs that can read mutable artifacts outside pinned snapshots."""
    fields = ("weave_manifest", "static_scope_map", "graph_jar", "cwd_template",
              "trial_cwd_template", "original_classes")
    arrays = ("original_class_dirs", "tool_classpath", "test_classpath")
    values = [config[key] for key in fields if key in config]
    for key in arrays:
        values.extend(config.get(key, []))
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"non-string input path in {config_path}")
        path = Path(value)
        if not path.is_absolute():
            path = config_path.parent / path
        if not (_inside(path, release) or _inside(path, source)):
            raise ValueError(f"unpinned input path: {path}")
        if not path.exists():
            raise ValueError(f"missing pinned input path: {path}")
    if "trial_cwd_template" in config:
        template = Path(config["trial_cwd_template"])
        if not template.is_absolute():
            template = config_path.parent / template
        if not template.is_dir():
            raise ValueError("trial_cwd_template must be a pinned directory")
    cwd = config.get("cwd")
    if not isinstance(cwd, str):
        raise ValueError("case needs cwd")
    cwd_path = Path(cwd)
    if "cwd_template" in config:
        scratch_root = Path("/dev/shm/mallory-gc/workspaces")
        if (not cwd_path.is_absolute() or cwd_path.name != case_id
                or not _inside(cwd_path, scratch_root)
                or cwd_path == scratch_root / case_id):
            raise ValueError(f"unsafe per-case writable cwd: {cwd}")
        template = Path(config["cwd_template"])
        if not template.is_absolute():
            template = config_path.parent / template
        if not template.is_dir():
            raise ValueError("cwd_template must be a pinned directory")
    else:
        if not (_inside(cwd_path, release) or _inside(cwd_path, source)):
            raise ValueError(f"unpinned input path: {cwd_path}")
        if not cwd_path.is_dir():
            raise ValueError(f"missing cwd: {cwd_path}")


def prepare_workspace(config: dict, config_path: Path, case_id: str) -> None:
    """Create a writable case cwd from a pinned read-only template, once."""
    if "cwd_template" not in config:
        return
    root = Path(config["cwd"])
    template = Path(config["cwd_template"])
    if not template.is_absolute():
        template = config_path.parent / template
    marker = root / ".mallory-workspace.json"
    expected = {"schema_version": 1, "case_id": case_id,
                "config_sha256": sha256(config_path),
                "template": str(template.resolve())}
    if root.exists():
        try:
            actual = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError(f"unrecognized writable workspace: {root}")
        if actual != expected:
            raise ValueError(f"writable workspace receipt mismatch: {root}")
        return
    if not root.parent.is_dir():
        raise ValueError("writable workspace parent must be staged explicitly")
    temporary = root.parent / ("." + case_id + ".staging")
    if temporary.exists():
        raise ValueError(f"stale workspace staging path: {temporary}")
    shutil.copytree(template, temporary, symlinks=False)
    for path in temporary.rglob("*"):
        if path.is_file() or path.is_dir():
            path.chmod(path.stat().st_mode | 0o200)
    temporary.chmod(temporary.stat().st_mode | 0o700)
    (temporary / marker.name).write_text(json.dumps(expected, sort_keys=True) + "\n",
                                          encoding="utf-8")
    temporary.rename(root)


def _host_wave_allowed(document: dict, host: str, system: str) -> None:
    if system != "zookeeper":
        return
    root = Path(document["state_root"])
    hdfs_ids = [case_id for case_id in document["configs"] if case_id.startswith("HDFS-")]
    if not hdfs_ids or any(checkpoint_state(case_id, root)[0] != "terminal"
                           for case_id in hdfs_ids):
        raise ValueError("ZooKeeper wave requires all configured HDFS cases terminal")


def verify_capacity(document: dict) -> dict:
    state_root = Path(document["state_root"])
    if _inside(state_root, Path("/dev/shm")):
        raise ValueError("core checkpoint must be on persistent storage")
    if not state_root.parent.is_dir():
        raise ValueError("persistent state parent must already exist")
    disk_free = shutil.disk_usage(state_root.parent).free
    shm_free = shutil.disk_usage("/dev/shm").free
    if disk_free < document.get("min_disk_free_bytes", 2 * 2**30):
        raise ValueError("durable disk below launch floor")
    if shm_free < document.get("min_shm_free_bytes", 6 * 2**30):
        raise ValueError("/dev/shm below launch floor")
    return {"disk_free_bytes": disk_free, "shm_free_bytes": shm_free}


def run_lane(document: dict, host: str, system: str,
             selected_cases: list[str], max_run_cases: int,
             *, require_tmpfs: bool = True,
             validate_core: bool = True,
             verify_runtime_files: bool = True) -> dict:
    verify_inputs(document, host, system, require_tmpfs=require_tmpfs,
                  validate_core=validate_core,
                  verify_runtime_files=verify_runtime_files)
    if not selected_cases or len(selected_cases) != len(set(selected_cases)):
        raise ValueError("selected cases must be a nonempty unique list")
    if any(case_id not in document["configs"] or
           not case_id.startswith(system.upper() + "-") for case_id in selected_cases):
        raise ValueError("selected case is absent or owned by another system")
    if max_run_cases < 1 or max_run_cases > len(selected_cases):
        raise ValueError("max_run_cases must be in the selected case range")
    _host_wave_allowed(document, host, system)
    state_root = Path(document["state_root"])
    verify_capacity(document)
    state_root.mkdir(parents=True, exist_ok=True)
    release = Path(document["release_root"])
    with (state_root / (".host-" + host + ".lock")).open("a+") as lease:
        fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        outcomes = []
        runs = 0
        for case_id in selected_cases:
            config = document["configs"][case_id]
            verify_inputs(document, host, system, require_tmpfs=require_tmpfs,
                          validate_core=validate_core,
                          verify_runtime_files=verify_runtime_files)
            case_dir = state_root / case_id
            state, evidence = checkpoint_state(case_id, state_root)
            config_path = release / config
            if state == "terminal" and evidence.get("checkpoint_config_sha256") != sha256(config_path):
                outcomes.append({"case_id": case_id, "state": "blocked_terminal_config_changed",
                                 "evidence": evidence})
                break
            if state == "terminal":
                outcomes.append({"case_id": case_id, "state": "skipped_terminal",
                                 "evidence": evidence})
                continue
            if state.startswith("blocked_") or (state == "resumable"
                    and evidence.get("checkpoint_config_sha256") != sha256(config_path)):
                outcomes.append({"case_id": case_id, "state": "blocked_checkpoint",
                                 "evidence": evidence})
                break
            if state == "fresh" and case_dir.exists() and any(case_dir.iterdir()):
                outcomes.append({"case_id": case_id, "state": "blocked_unrecognized_case_data"})
                break
            if runs >= max_run_cases:
                break
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            prepare_workspace(raw, config_path, case_id)
            if validate_core:
                from Mallory.core.graphchecker_campaign import load_config
                from Mallory.core.graphchecker_fuzzer import _budget
                parsed = load_config(config_path)
                _budget(config_path)
                verify_input_classfiles(parsed)
            started = time.monotonic()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(release)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            command = [sys.executable, "-m", "Mallory.core.graphchecker_fuzzer",
                       "--config", str(config_path), "--out", str(case_dir)]
            case_dir.mkdir(parents=True, exist_ok=True)
            stdout = case_dir / "launcher.stdout.log"
            stderr = case_dir / "launcher.stderr.log"
            with stdout.open("a", encoding="utf-8") as out_stream, \
                    stderr.open("a", encoding="utf-8") as err_stream:
                result = subprocess.run(command, env=env, cwd=release,
                                        stdout=out_stream, stderr=err_stream,
                                        text=True)
            dispatch = {"schema_version": 1, "case_id": case_id,
                        "host": host, "system": system,
                        "returncode": result.returncode,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "checkpoint": str(case_dir / "checkpoint.json"),
                        "summary": str(case_dir / "summary.json"),
                        "stdout": str(stdout), "stderr": str(stderr),
                        "config_sha256": sha256(config_path)}
            previous_path = case_dir / "dispatch.json"
            previous_attempts = []
            if previous_path.exists():
                previous = json.loads(previous_path.read_text(encoding="utf-8"))
                if (not isinstance(previous, dict) or previous.get("case_id") != case_id
                        or previous.get("schema_version") != 1):
                    raise ValueError(f"unrecognized prior dispatch receipt: {previous_path}")
                previous_attempts = previous.get("attempts", [
                    {key: previous[key] for key in ("returncode", "elapsed_seconds")
                     if key in previous}])
                if not isinstance(previous_attempts, list):
                    raise ValueError(f"invalid prior dispatch history: {previous_path}")
            dispatch["attempts"] = [*previous_attempts,
                                    {"returncode": result.returncode,
                                     "elapsed_seconds": dispatch["elapsed_seconds"]}]
            dispatch["total_launcher_elapsed_seconds"] = round(
                sum(attempt.get("elapsed_seconds", 0)
                    for attempt in dispatch["attempts"]), 3)
            temporary = case_dir / ".dispatch.json.tmp"
            temporary.write_text(json.dumps(dispatch, sort_keys=True, indent=2) + "\n",
                                 encoding="utf-8")
            temporary.replace(case_dir / "dispatch.json")
            outcomes.append({"case_id": case_id, "state": "ran",
                             "returncode": result.returncode,
                             "evidence": dispatch})
            runs += 1
            if result.returncode:
                break
        return {"host": host, "system": system, "outcomes": outcomes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--case-ids", nargs="*")
    parser.add_argument("--max-run-cases", type=int, default=1)
    args = parser.parse_args()
    if sha256(args.deployment) != args.expected_sha256:
        raise ValueError("deployment manifest changed")
    document = json.loads(args.deployment.read_text(encoding="utf-8"))
    if args.verify_only:
        result = verify_inputs(document, args.host, args.system)
        result["capacity"] = verify_capacity(document)
    else:
        result = run_lane(document, args.host, args.system,
                          args.case_ids or [], args.max_run_cases)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
