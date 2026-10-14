"""Create a reusable ZooKeeper native protocol gate from a closed seed.

The seed proves that the pinned protocol hooks exchange paired messages. It
does not supply another case's target, JUnit selector, or fault sites. Those
are checked independently by ``zookeeper_native_adapter.prepare``.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

from Mallory.instrumentation.graphchecker_port import native_original_weave as weave
from Mallory.native_graphchecker_campaign import campaign as native
from . import zookeeper_native_adapter as zk
from .preparation import _atomic, _object, _sha


def _path(value: object, label: str, *, directory: bool | None = None) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an absolute pinned path")
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink() or
            not path.exists() or (directory is True and not path.is_dir()) or
            (directory is False and not path.is_file())):
        raise ValueError(f"{label} must be an existing nonsymlink path")
    return path


def _artifact_digest(path: Path) -> str:
    return _sha(path) if path.is_file() else weave.file_tree_digest(path)


def build(profile_file: Path, seed_file: Path, gate_file: Path) -> dict:
    profile = _object(profile_file)
    seed = _object(seed_file)
    if (profile.get("mode") != zk.PROFILE_MODE or
            profile.get("protocol_gate") != str(gate_file) or
            not gate_file.is_absolute() or gate_file.exists() or
            gate_file.is_symlink() or
            not gate_file.parent.is_dir() or gate_file.parent.is_symlink() or
            not isinstance(profile.get("analysis"), dict) or
            any(key in profile["analysis"] for key in
                ("target", "check_line", "doors", "io_points", "fault_sites"))):
        raise ValueError("gate requires a new target-free shared profile")
    source = _path(profile.get("source_root"), "source_root", directory=True)
    classes = _path(profile.get("source_classes"), "source_classes", directory=True)
    mapping = _path(profile.get("communication_mapping"),
                    "communication_mapping", directory=False)
    java = _path(profile.get("java"), "java", directory=False)
    session = _path(seed.get("session_dir_path"), "session_dir", directory=True)
    stdout = _path(seed.get("healthy_stdout_path"), "healthy_stdout", directory=False)
    trace_manifest = _path(seed.get("healthy_trace_manifest_path"),
                           "healthy_trace_manifest", directory=False)
    static_map = _path(seed.get("static_map_path"), "static_map", directory=False)
    postweave = _path(seed.get("postweave_class_tree_path"),
                      "postweave_classes", directory=True)
    adapter_build = _path(seed.get("adapter_build_path"), "adapter_build")
    if (not any(marker in stdout.read_text(encoding="utf-8", errors="replace")
                for marker in ("NATIVE_RECORDING_JUNIT_RESULT passed=1 failed=0",
                               "NATIVE_ZK_SESSION_JUNIT_RESULT passed=1 failed=0")) or
            not zk._closed_trace_manifest(_object(trace_manifest))):
        raise ValueError("seed JUnit or original runtime trace did not close")
    verifier_source = Path(zk.__file__).with_name(
        "NativeZooKeeperSessionVerifier.java")
    if not native.JAR.is_file() or not native.DEPENDENCIES.is_file():
        raise ValueError("source-built original GraphChecker engine is absent")
    receipt_path = gate_file.with_name(gate_file.stem + "-session-reader.json")
    source_path = gate_file.with_name("NativeZooKeeperSessionVerifier.java")
    verifier_build = gate_file.with_name(gate_file.stem + "-verifier-classes")
    if receipt_path.exists() or source_path.exists() or verifier_build.exists():
        raise ValueError("gate proof outputs already exist")
    compiler = (java.parent.parent.parent / "bin/javac"
                if java.parent.parent.name == "jre" else java.with_name("javac"))
    compiler = _path(str(compiler), "matching javac", directory=False)
    verifier_build.mkdir()
    compile_result = subprocess.run(
        [str(compiler), "-source", "8", "-target", "8", "-cp",
         zk._original_cp([]), "-d", str(verifier_build), str(verifier_source)],
        capture_output=True, timeout=60)
    if (compile_result.returncode or not (verifier_build /
            "edu/uva/liftlab/graphchecker/runtime/"
            "NativeZooKeeperSessionVerifier.class").is_file()):
        shutil.rmtree(verifier_build)
        raise ValueError("source-built SessionReader verifier did not compile")
    command = [str(java), f"-Dcausynth.engine.jar={native.JAR}",
               "-Dcausynth.typed.wire.sites=auto", "-cp",
               os.pathsep.join((str(verifier_build), zk._original_cp([]))),
               "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperSessionVerifier",
               str(session), str(receipt_path)]
    completed = subprocess.run(command, capture_output=True, timeout=30)
    if completed.returncode or not receipt_path.is_file():
        receipt_path.unlink(missing_ok=True)
        raise ValueError("original SessionReader wire verifier failed")
    receipt = _object(receipt_path)
    sites = receipt.get("schedule_wire_sites")
    if (receipt.get("mode") != "original_session_reader_complete" or
            receipt.get("session_reader_incomplete") != "" or
            receipt.get("session_role") != "SEED" or
            receipt.get("gap_rows") != 0 or
            receipt.get("schedule_pairing_gaps") != 0 or
            not isinstance(receipt.get("schedule_wire_pairs"), int) or
            receipt["schedule_wire_pairs"] <= 0 or
            not isinstance(sites, str) or not sites or
            receipt.get("session_tree_sha256") != weave.file_tree_digest(session) or
            receipt.get("engine_jar_sha256") != _sha(native.JAR)):
        receipt_path.unlink(missing_ok=True)
        raise ValueError("original seed does not prove paired ZooKeeper wires")
    shutil.copyfile(verifier_source, source_path)
    gate = {
        "mode": zk.GATE_MODE, "accepted": True,
        "typed_wire_send_receive": True, "typedWirePorts": sites.split(","),
        "schedule_wire_sites": sites, "blockingGaps": 0,
        "junitPassed": True,
        "engine_jar_sha256": _sha(native.JAR),
        "source_tree_sha256": weave.file_tree_digest(source),
        "source_classes_sha256": weave.class_tree_digest(classes),
        "communication_mapping_sha256": _sha(mapping),
        "session_dir_path": str(session),
        "session_tree_sha256": receipt["session_tree_sha256"],
        "session_manifest_path": str(session / "manifest.json"),
        "session_manifest_sha256": _sha(session / "manifest.json"),
        "session_reader_receipt_path": str(receipt_path),
        "session_reader_receipt_sha256": _sha(receipt_path),
        "session_reader_verifier_source_path": str(source_path),
        "session_reader_verifier_source_sha256": _sha(source_path),
        "session_reader_verifier_artifact_path": str(verifier_build),
        "session_reader_verifier_artifact_sha256": _artifact_digest(verifier_build),
        "healthy_stdout_path": str(stdout), "healthy_stdout_sha256": _sha(stdout),
        "healthy_trace_manifest_path": str(trace_manifest),
        "healthy_trace_manifest_sha256": _sha(trace_manifest),
        "static_map_path": str(static_map), "static_map_sha256": _sha(static_map),
        "postweave_class_tree_path": str(postweave),
        "postweave_class_tree_sha256": weave.class_tree_digest(postweave),
        "adapter_build_path": str(adapter_build),
        "adapter_build_sha256": _artifact_digest(adapter_build),
    }
    if not zk._reusable_gate_claims(gate):
        raise ValueError("source-backed gate is not reusable")
    _atomic(gate_file, gate)
    return gate


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python -m Mallory.native_graphchecker_dispatch."
                         "build_zookeeper_protocol_gate PROFILE SEED GATE")
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
