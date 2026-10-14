"""Shared ZooKeeper original-GraphChecker preparation command.

The profile contains immutable classpaths and build inputs, never a target
branch, I/O door, fault site, or test selector. Those come from the inventory
request and original GraphChecker static/runtime receipts. A native protocol
gate must be accepted before this command can launch a heavy stage.
"""

from __future__ import annotations

import json
import hashlib
import gzip
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from Mallory.instrumentation.graphchecker_port import native_original_weave as weave
from Mallory.native_graphchecker_campaign import campaign as native
from .preparation import _atomic, _digest, _object, _sha

PROFILE_MODE = "original_graphchecker_zookeeper_profile"
GATE_MODE = "original_graphchecker_zookeeper_protocol_gate"
SITE = re.compile(r"^<([^:]+): (.+)>#u([0-9]+)$")
METHOD = re.compile(r"^([^ ]+) ([^(]+)\(([^)]*)\)$")
PRIMITIVE = {"void": "V", "boolean": "Z", "byte": "B", "char": "C",
             "short": "S", "int": "I", "long": "J", "float": "F",
             "double": "D"}
SESSION_FILES = (
    "manifest.json", "activations.jsonl", "decisions.jsonl",
    "exports.jsonl", "attaches.jsonl", "writes.jsonl", "reads.jsonl",
    "roots.jsonl", "targets.jsonl", "gaps.jsonl",
    "expressions.jsonl", "schedule.jsonl",
)
REQUIRED_CLASSES = {
    "scope_planner_classpath": (
        "edu.uva.liftlab.mallory.scope.ScopePlanner",
        "edu.uva.liftlab.graphchecker.GraphCheckerMain",
        "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
        "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
        "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
    ),
    "runner_classpath": (
        "edu.uva.liftlab.graphchecker.runtime.NativeRecordingJUnitMethodRunner",
        "edu.uva.liftlab.graphchecker.runtime.NativeJUnitMethodRunner",
    ),
    "post_weave_classpath": (
        "edu.uva.liftlab.mallory.nativecampaign.NativeZooKeeperCombinedPostWeave",
        "edu.uva.liftlab.graphchecker.causynth.NativeZooKeeperProtocolWeaveMain",
        "edu.uva.liftlab.mallory.nativebinding.NativeZooKeeperActorWeave",
        "soot.G",
    ),
}


def _valid_wire_ports(ports: object) -> bool:
    """A proof may cover any observed wire family, including client traffic."""
    return (isinstance(ports, list) and bool(ports) and
            all(isinstance(port, str) and port.strip() == port and port
                for port in ports) and len(ports) == len(set(ports)))


def _reusable_gate_claims(gate: dict) -> bool:
    """The seed proves transport capability; each case proves its own target.

    Target reach and a unique executable closure task are checked later by
    ``prepare`` on the requested unchanged JUnit. They cannot be inherited
    from the JUnit that established this protocol gate.
    """
    return (gate.get("mode") == GATE_MODE and gate.get("accepted") is True and
            (gate.get("typed_wire_send_receive") is True or
             gate.get("typed_quorum_send_receive") is True) and
            gate.get("junitPassed") is True and
            gate.get("blockingGaps") == 0 and
            _valid_wire_ports(gate.get("typedWirePorts")))


def _closed_trace_manifest(manifest: dict) -> bool:
    return (manifest.get("kind") == "STREAMING_RUNTIME_TRACE" and
            (manifest.get("status") == "CLOSED" or
             manifest.get("closed") is True))


def _paths(values: object, label: str) -> list[Path]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} requires nonempty pinned paths")
    paths = [Path(value) for value in values]
    if any(not path.is_absolute() or not path.exists() or path.is_symlink()
           for path in paths):
        raise ValueError(f"{label} has an absent or mutable path")
    return paths


def _unique_class(classpath: list[Path], class_name: str) -> dict:
    relative = class_name.replace(".", "/") + ".class"
    matches = []
    for path in classpath:
        data = None
        if path.is_dir():
            candidate = path / relative
            if candidate.is_file() and not candidate.is_symlink():
                data = candidate.read_bytes()
        elif path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if relative in archive.namelist():
                    data = archive.read(relative)
        if data is not None:
            matches.append({"class": class_name, "classpath_entry": str(path),
                            "class_sha256": hashlib.sha256(data).hexdigest()})
    if len(matches) != 1:
        raise ValueError(f"ZooKeeper preflight class must resolve once: {class_name}")
    return matches[0]


def preflight_execution_classes(profile: dict) -> dict:
    """Check the Java entry points before an expensive static/weave pass."""
    for name in ("runner_source", "post_weave_source"):
        if not profile.get(name):
            raise ValueError(f"ZooKeeper preflight requires pinned {name}")
    engine = weave.verify_engine()
    class_rows = []
    for key, names in REQUIRED_CLASSES.items():
        classpath = _paths(profile.get(key), key)
        if key == "post_weave_classpath":
            # The protocol postweave uses Soot. The original source-built
            # engine's verified dependency classpath is part of this JVM.
            classpath = [Path(native.JAR), *map(Path,
                native.DEPENDENCIES.read_text(encoding="utf-8").strip().split(
                    os.pathsep)), *classpath]
        class_rows.extend(_unique_class(classpath, name) for name in names)
    return {"schema_version": 1,
            "mode": "original_graphchecker_zookeeper_class_preflight",
            "engine_jar_sha256": _sha(native.JAR),
            "engine_source_tree_sha256": engine["source_tree_sha256"],
            "sources": {name: {"path": profile[name],
                               "sha256": _sha(Path(profile[name]))}
                        for name in ("runner_source", "post_weave_source")},
            "classes": class_rows}


def preflight_static_sidecars(original: Path, scope_out: Path) -> dict:
    """Fail before weaving if the original Soot sidecars are incomplete."""
    files = {
        "candidate_graph": original / "candidate_dataflow_edges.jsonl.gz",
        "static_scope_map": original / "static_scope_map.jsonl",
        "region_skeletons": original / "region_skeletons.jsonl.gz",
        "weave_manifest": scope_out / "weave_manifest.json",
    }
    pins = {}
    for label, path in files.items():
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise ValueError(f"ZooKeeper static sidecar missing: {label}")
        if path.suffix == ".gz":
            try:
                with gzip.open(path, "rb") as stream:
                    first = stream.readline()
                if not first:
                    raise ValueError("empty gzip")
            except (OSError, EOFError, ValueError) as exc:
                raise ValueError(f"ZooKeeper static sidecar invalid: {label}") from exc
        elif label == "weave_manifest":
            manifest = _object(path)
            if not isinstance(manifest.get("targets"), list):
                raise ValueError("ZooKeeper static sidecar invalid: weave_manifest")
        pins[label] = {"path": str(path), "sha256": _sha(path)}
    return {"schema_version": 1,
            "mode": "original_graphchecker_zookeeper_static_preflight",
            "sidecars": pins}


def _verify_generic_runner(profile: dict) -> None:
    source_name = profile.get("runner_source")
    if not source_name:
        return
    source = Path(source_name)
    canonical = (Path(__file__).resolve().parents[1] /
                 "native_graphchecker_fixture/NativeJUnitMethodRunner.java")
    if (not source.is_absolute() or not source.is_file() or
            source.is_symlink() or _sha(source) != _sha(canonical)):
        raise ValueError("ZooKeeper generic JUnit runner source changed")
    relative = "edu/uva/liftlab/graphchecker/runtime/NativeJUnitMethodRunner.class"
    matches = []
    for path in _paths(profile.get("runner_classpath"), "runner_classpath"):
        if path.is_dir() and (path / relative).is_file():
            matches.append(path)
        elif path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if relative in archive.namelist():
                    matches.append(path)
    if len(matches) != 1:
        raise ValueError("ZooKeeper generic JUnit runner must resolve once")


def _verify_postweave(profile: dict) -> None:
    source_name = profile.get("post_weave_source")
    if not source_name:
        return
    source = Path(source_name)
    canonical = Path(__file__).resolve().with_name(
        "NativeZooKeeperCombinedPostWeave.java")
    if (not source.is_absolute() or not source.is_file() or
            source.is_symlink() or _sha(source) != _sha(canonical)):
        raise ValueError("ZooKeeper combined postweave source changed")
    relative = "edu/uva/liftlab/mallory/nativecampaign/NativeZooKeeperCombinedPostWeave.class"
    matches = []
    for path in _paths(profile.get("post_weave_classpath"),
                       "post_weave_classpath"):
        if path.is_dir() and (path / relative).is_file():
            matches.append(path)
        elif path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if relative in archive.namelist():
                    matches.append(path)
    if len(matches) != 1:
        raise ValueError("ZooKeeper combined postweave must resolve once")


def _verify_closed_session(gate: dict) -> None:
    """Admit a session only with a pinned original SessionReader verdict.

    The original SessionManifest does not state closure.  Its row files must
    be read by SessionReader; the protocol gate pins that verifier's source,
    build, receipt, and every byte of the session read by it.
    """
    session = Path(gate.get("session_dir_path", ""))
    manifest = Path(gate.get("session_manifest_path", ""))
    if (not session.is_absolute() or not session.is_dir() or
            session.is_symlink() or manifest != session / "manifest.json" or
            any(not (session / name).is_file() or
                (session / name).is_symlink() for name in SESSION_FILES) or
            any(path.is_symlink() for path in session.rglob("*")) or
            weave.file_tree_digest(session) != gate.get("session_tree_sha256")):
        raise ValueError("ZooKeeper gate original session tree changed")
    for name in ("session_reader_receipt", "session_reader_verifier_source"):
        path = Path(gate.get(f"{name}_path", ""))
        if (not path.is_absolute() or not path.is_file() or path.is_symlink() or
                _sha(path) != gate.get(f"{name}_sha256")):
            raise ValueError(f"ZooKeeper SessionReader proof changed: {name}")
    # A pinned arbitrary Java file is not evidence that the original
    # SessionReader and exact SEND/RECV endpoints were checked.
    verifier_source = Path(gate["session_reader_verifier_source_path"])
    if _sha(verifier_source) != _sha(Path(__file__).with_name(
            "NativeZooKeeperSessionVerifier.java")):
        raise ValueError("ZooKeeper SessionReader verifier source differs")
    artifact = Path(gate.get("session_reader_verifier_artifact_path", ""))
    if (not artifact.is_absolute() or not artifact.exists() or
            artifact.is_symlink() or
            (_sha(artifact) if artifact.is_file() else
             weave.file_tree_digest(artifact)) != gate.get(
                "session_reader_verifier_artifact_sha256")):
        raise ValueError("ZooKeeper SessionReader verifier build changed")
    receipt = _object(Path(gate["session_reader_receipt_path"]))
    wire_sites = gate.get("schedule_wire_sites")
    if (not isinstance(wire_sites, str) or not wire_sites or
            any(not site.strip() for site in wire_sites.split(",")) or
            len(set(wire_sites.split(","))) != len(wire_sites.split(","))):
        raise ValueError("ZooKeeper gate lacks exact typed wire sites")
    if (receipt.get("mode") != "original_session_reader_complete" or
            receipt.get("session_reader_incomplete") != "" or
            receipt.get("session_role") != "SEED" or
            receipt.get("schedule_wire_sites") != wire_sites or
            not isinstance(receipt.get("schedule_wire_pairs"), int) or
            isinstance(receipt.get("schedule_wire_pairs"), bool) or
            receipt["schedule_wire_pairs"] <= 0 or
            receipt.get("schedule_pairing_gaps") != 0 or
            receipt.get("gap_rows") != 0 or
            receipt.get("session_dir_path") != str(session) or
            receipt.get("session_tree_sha256") != gate["session_tree_sha256"] or
            receipt.get("session_manifest_sha256") != gate[
                "session_manifest_sha256"] or
            receipt.get("engine_jar_sha256") != gate["engine_jar_sha256"]):
        raise ValueError("ZooKeeper gate original SessionReader did not close")
    manifest_row = _object(manifest)
    if (manifest_row.get("kind") != "SESSION_MANIFEST" or
            manifest_row.get("schemaVersion") != 2 or
            manifest_row.get("sessionId") != session.name or
            manifest_row.get("role") != "SEED" or
            receipt.get("session_id") != session.name):
        raise ValueError("ZooKeeper gate original SessionManifest is invalid")


def _rerun_session_reader(gate: dict, java: Path) -> None:
    """Recheck a gated session with the source-built original reader now."""
    artifact = Path(gate["session_reader_verifier_artifact_path"])
    classpath = os.pathsep.join((str(artifact.resolve(strict=True)),
                                 _original_cp([])))
    with tempfile.TemporaryDirectory(prefix="mallory-session-gate-") as tmp:
        fresh_path = Path(tmp) / "session-reader.json"
        command = [str(java.resolve(strict=True)),
                   f"-Dcausynth.engine.jar={native.JAR.resolve(strict=True)}",
                   f"-Dcausynth.typed.wire.sites={gate['schedule_wire_sites']}",
                   "-cp", classpath,
                   "edu.uva.liftlab.graphchecker.runtime.NativeZooKeeperSessionVerifier",
                   gate["session_dir_path"], str(fresh_path)]
        result = subprocess.run(command, capture_output=True, timeout=30)
        if result.returncode or not fresh_path.is_file():
            raise ValueError("ZooKeeper original SessionReader verifier failed")
        fresh = _object(fresh_path)
        pinned = _object(Path(gate["session_reader_receipt_path"]))
        if fresh != pinned:
            raise ValueError("ZooKeeper original SessionReader receipt changed")


def _profile(request: dict, profile_file: Path) -> dict:
    profile = _object(profile_file)
    if (profile.get("schema_version") != 1 or
            profile.get("mode") != PROFILE_MODE or
            request.get("system") != "zookeeper" or
            request.get("system_version") != profile.get("system_version") or
            not isinstance(profile.get("analysis"), dict) or
            any(key in profile["analysis"] for key in
                ("target", "check_line", "doors", "io_points", "fault_sites"))):
        raise ValueError("ZooKeeper profile is not a shared native adapter")
    for key in ("analysis_classpath", "scope_planner_classpath",
                "runtime_classpath", "runner_classpath", "post_weave_classpath"):
        _paths(profile.get(key), key)
    for key in ("source_root", "source_classes", "communication_mapping",
                "java", "protocol_gate"):
        path = Path(profile.get(key, ""))
        if not path.is_absolute() or not path.exists() or path.is_symlink():
            raise ValueError(f"ZooKeeper {key} is absent or mutable")
    if (not isinstance(profile.get("budget"), dict) or
            not isinstance(profile.get("timeout_seconds"), int) or
            profile["timeout_seconds"] <= 0 or
            not isinstance(profile.get("max_jobs"), int) or
            profile["max_jobs"] <= 0):
        raise ValueError("ZooKeeper profile lacks bounded campaign settings")
    runner_args = profile.get("runner_jvm_args", [])
    if (not isinstance(runner_args, list) or
            not all(isinstance(arg, str) and arg.startswith("-D")
                    for arg in runner_args) or
            any(arg.startswith(("-Djava.io.tmpdir=", "-Dbuild.test.dir="))
                for arg in runner_args)):
        raise ValueError("ZooKeeper runner args must preserve fresh trial directories")
    _verify_generic_runner(profile)
    _verify_postweave(profile)
    source = Path(profile["source_root"])
    target = request["target"]
    source_file = (source / target["source_path"]).resolve(strict=True)
    if (not source_file.is_relative_to(source.resolve(strict=True)) or
            _sha(source_file) != target.get("source_sha256")):
        raise ValueError("ZooKeeper original target source changed")
    junit = request["original_junit"]
    test_file = (source / junit["source_path"]).resolve(strict=True)
    if (not test_file.is_relative_to(source.resolve(strict=True)) or
            f"{junit['method']}(" not in test_file.read_text(encoding="utf-8")):
        raise ValueError("ZooKeeper original cluster JUnit source is absent")
    gate = _object(Path(profile["protocol_gate"]))
    source_classes = Path(profile["source_classes"])
    mapping = Path(profile["communication_mapping"])
    def verified_file(name: str, sha_name: str) -> None:
        path = Path(gate.get(name, ""))
        if (not path.is_absolute() or not path.is_file() or path.is_symlink() or
                _sha(path) != gate.get(sha_name)):
            raise ValueError(f"ZooKeeper protocol gate input changed: {name}")

    if (not _reusable_gate_claims(gate) or
            gate.get("engine_jar_sha256") != _sha(native.JAR) or
            gate.get("source_tree_sha256") != weave.file_tree_digest(source) or
            gate.get("source_classes_sha256") != weave.class_tree_digest(
                source_classes) or
            gate.get("communication_mapping_sha256") != _sha(mapping)):
        raise ValueError("ZooKeeper native quorum/actor protocol gate pending")
    verified_file("static_map_path", "static_map_sha256")
    verified_file("session_manifest_path", "session_manifest_sha256")
    verified_file("healthy_stdout_path", "healthy_stdout_sha256")
    verified_file("healthy_trace_manifest_path", "healthy_trace_manifest_sha256")
    healthy_stdout = Path(gate["healthy_stdout_path"]).read_text(
        encoding="utf-8", errors="replace")
    if (not any(marker in healthy_stdout for marker in
                ("NATIVE_RECORDING_JUNIT_RESULT passed=1 failed=0",
                 "NATIVE_ZK_SESSION_JUNIT_RESULT passed=1 failed=0")) or
            not _closed_trace_manifest(_object(Path(
                gate["healthy_trace_manifest_path"])))):
        raise ValueError("ZooKeeper protocol seed JUnit or trace is not closed")
    postweave = Path(gate.get("postweave_class_tree_path", ""))
    if (not postweave.is_absolute() or not postweave.is_dir() or
            weave.class_tree_digest(postweave) != gate.get(
                "postweave_class_tree_sha256")):
        raise ValueError("ZooKeeper gate postweave class tree changed")
    adapter_build = Path(gate.get("adapter_build_path", ""))
    if (not adapter_build.is_absolute() or not adapter_build.exists() or
            adapter_build.is_symlink() or
            (_sha(adapter_build) if adapter_build.is_file() else
             weave.file_tree_digest(adapter_build)) != gate.get(
                "adapter_build_sha256")):
        raise ValueError("ZooKeeper gate adapter build changed")
    _verify_closed_session(gate)
    _rerun_session_reader(gate, Path(profile["java"]))
    return profile


def _target(request: dict) -> tuple[str, str, int]:
    target = request["target"]
    match = SITE.fullmatch(target["site_id"])
    function = target["function"]
    if not match or not isinstance(function, str):
        raise ValueError("inventory target is not an exact original Soot throw")
    clazz = match.group(1)
    method = function.split("(", 1)[0].rsplit(".", 1)[-1]
    if not function.startswith(clazz + ".") or not method:
        raise ValueError("inventory target method differs from exact site")
    # The inventory source line names the compiled THROW itself. A legacy
    # runtime mapping may point at a later token of a multiline statement.
    line = target["source_line"]
    if not isinstance(line, int) or line <= 0:
        raise ValueError("inventory throw line is invalid")
    return clazz, method, line


def _jvm_type(name: str) -> str:
    dimensions = 0
    while name.endswith("[]"):
        dimensions += 1
        name = name[:-2]
    if name not in PRIMITIVE and not re.fullmatch(r"[\w.$]+", name):
        raise ValueError("inventory method has an invalid Java type")
    if name == "void" and dimensions:
        raise ValueError("void arrays are invalid")
    value = PRIMITIVE.get(name, "L" + name.replace(".", "/") + ";")
    return "[" * dimensions + value


def _inventory_descriptor(site_id: str) -> tuple[str, str, str]:
    site = SITE.fullmatch(site_id)
    if not site:
        raise ValueError("inventory target lacks a Soot unit identity")
    method = METHOD.fullmatch(site.group(2))
    if not method:
        raise ValueError("inventory target method signature is invalid")
    parameters = [] if not method.group(3) else method.group(3).split(",")
    descriptor = "(" + "".join(_jvm_type(name.strip()) for name in parameters)
    descriptor += ")" + _jvm_type(method.group(1))
    return site.group(1), method.group(2), descriptor


def resolve_original_target(request: dict, report: dict, manifest: dict,
                            source_classes: Path) -> dict:
    """Bind an inventory throw to one unit in the original compiled class.

    Older inventory unit numbers may refer to a class with manual hooks. The
    original Soot scan chooses the executed class's unit, then this check
    requires its exact method descriptor, source throw line, and exception.
    """
    target = request["target"]
    clazz, method, descriptor = _inventory_descriptor(target["site_id"])
    if _target(request) != (clazz, method, target["source_line"]):
        raise ValueError("inventory method and source identity differ")
    class_file = source_classes / (clazz.replace(".", "/") + ".class")
    if not class_file.is_file():
        raise ValueError("original target class is absent")
    candidates = [row for row in manifest.get("targets", [])
                  if row.get("clazz") == clazz and
                  row.get("method") == method and
                  row.get("descriptor") == descriptor and
                  row.get("kind") == "THROW" and
                  row.get("line") == target["source_line"] and
                  row.get("exceptionClass") == target["target_exception"]]
    if len(candidates) != 1 or candidates[0].get("siteId") != report.get(
            "throwSiteId"):
        raise ValueError("original Soot did not select one matching target throw")
    guards = [row for row in manifest.get("targets", [])
              if row.get("clazz") == clazz and
              row.get("method") == method and
              row.get("descriptor") == descriptor and
              row.get("kind") == "BRANCH" and
              row.get("siteId") == report.get("targetSiteId")]
    if len(guards) != 1 or not isinstance(guards[0].get("line"), int) or (
            guards[0]["line"] > target["source_line"]):
        raise ValueError("original Soot did not select one controlling guard")
    return {
        "inventory_throw_site_id": target["site_id"],
        "inventory_compiled_throw_site": target.get("compiled_throw_site"),
        "original_throw_site_id": candidates[0]["siteId"],
        "original_guard_site_id": guards[0]["siteId"],
        "original_guard_source_line": guards[0]["line"],
        "original_throw_source_line": candidates[0]["line"],
        "method_descriptor": descriptor,
        "exception_class": target["target_exception"],
        "original_class_sha256": _sha(class_file),
    }


def _cp(paths: list[Path]) -> str:
    return os.pathsep.join(str(path.resolve(strict=True)) for path in paths)


def _run(stage: str, argv: list[str], output: Path, timeout: int,
         env: dict[str, str] | None = None) -> None:
    (output / "commands").mkdir(exist_ok=True)
    _atomic(output / "commands" / f"{stage}.json", {"argv": argv})
    with (output / "commands" / f"{stage}.stdout").open("wb") as stdout, (
            output / "commands" / f"{stage}.stderr").open("wb") as stderr:
        result = subprocess.run(argv, cwd=output, env=env,
                                stdout=stdout, stderr=stderr, timeout=timeout)
    if result.returncode:
        raise ValueError(f"original GraphChecker {stage} failed: {result.returncode}")


def select_target_task(plan_file: Path, occurrence: dict) -> dict:
    """Select an admitted original scheduler task for the resolved guard."""
    candidates = []
    for line in plan_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        branch = row.get("targetBranch") or {}
        if (row.get("goalKind") == "TARGET_REACH_CLOSURE" and
                row.get("occurrenceId") == occurrence["selectedOccurrenceAddress"] and
                branch.get("siteId") == occurrence["checkSiteId"] and
                row.get("admission", {}).get("state") == "EXECUTABLE" and
                isinstance(branch.get("occurrence"), int) and
                branch["occurrence"] >= 0 and
                isinstance(row.get("taskId"), str)):
            candidates.append(row)
    if len(candidates) != 1:
        raise ValueError("original scheduler did not yield one exact target task")
    return candidates[0]


def _original_cp(extra: list[Path]) -> str:
    dependencies = native.DEPENDENCIES.read_text(encoding="utf-8").strip()
    return os.pathsep.join((str(native.JAR.resolve(strict=True)), dependencies,
                            _cp(extra)))


def prepare(request_file: Path, output: Path, profile_file: Path) -> dict:
    request = _object(request_file)
    profile = _profile(request, profile_file)
    class_preflight = preflight_execution_classes(profile)
    if output.exists() and any(output.iterdir()):
        raise ValueError("native adapter output must start empty")
    output.mkdir(parents=True, exist_ok=True)
    _atomic(output / "class-preflight.json", class_preflight)
    clazz, method, line = _target(request)
    source_classes = Path(profile["source_classes"]).resolve(strict=True)
    process_classes_sha = weave.class_tree_digest(source_classes)
    java = str(Path(profile["java"]).resolve(strict=True))
    map_file = str(Path(profile["communication_mapping"]).resolve(strict=True))
    analysis_cp = _paths(profile["analysis_classpath"], "analysis_classpath")
    extra = _paths(profile["runtime_classpath"], "runtime_classpath")
    scope_cp = _paths(profile["scope_planner_classpath"], "scope_planner_classpath")
    if native.JAR.resolve(strict=True) not in scope_cp:
        raise ValueError("static planner did not load the pinned source-built engine")
    original = output / "original"
    analysis = dict(profile["analysis"])
    analysis.update(process_dirs=[str(source_classes)],
                    classpath=[str(path.resolve(strict=True)) for path in analysis_cp],
                    original_graphchecker_seed=True,
                    original_engine_output_dir=str(original))
    scope_input = output / "scope-input.json"
    _atomic(scope_input, {"case_id": request["case_id"],
                          "target": {"class": clazz, "method": method,
                                     "line": line, "kind": "THROW",
                                     "exception": request["target"]["target_exception"]},
                          "analysis": analysis})
    scope_out = output / "scope"
    _run("static", [java, f"-Dcausynth.communication.mappings={map_file}",
                    "-Xmx4g", "-cp", _cp(scope_cp),
                    "edu.uva.liftlab.mallory.scope.ScopePlanner",
                    str(scope_input), str(scope_out)], output, 1800)
    report = _object(scope_out / "analysis.json")
    if (report.get("analysisKind") != "original_graphchecker_seed_backward" or
            report.get("sootDependencyClasspathSha256") != hashlib.sha256(
                _cp(analysis_cp).encode("utf-8")).hexdigest() or
            weave.class_tree_digest(source_classes) != process_classes_sha):
        raise ValueError("Soot scope did not resolve the inventory throw")
    identity = resolve_original_target(request, report,
                                       _object(scope_out / "weave_manifest.json"),
                                       source_classes)
    graph = original / "candidate_dataflow_edges.jsonl.gz"
    scope = original / "static_scope_map.jsonl"
    skeletons = original / "region_skeletons.jsonl.gz"
    sidecar_preflight = preflight_static_sidecars(original, scope_out)
    _atomic(output / "static-sidecar-preflight.json", sidecar_preflight)
    _atomic(output / "static-scope-receipt.json", {
        "schema_version": 1, "mode": "original_graphchecker_static_scope",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "target_identity": identity,
        "class_preflight_path": str(output / "class-preflight.json"),
        "class_preflight_sha256": _sha(output / "class-preflight.json"),
        "static_sidecar_preflight_path": str(
            output / "static-sidecar-preflight.json"),
        "static_sidecar_preflight_sha256": _sha(
            output / "static-sidecar-preflight.json"),
        "analysis_kind": report["analysisKind"],
        "analysis_path": str(scope_out / "analysis.json"),
        "analysis_sha256": _sha(scope_out / "analysis.json"),
        "scope_input_path": str(scope_input),
        "scope_input_sha256": _sha(scope_input),
        "engine_jar_sha256": _sha(native.JAR),
        "process_classes_path": str(source_classes),
        "process_classes_sha256": process_classes_sha,
        "ordered_analysis_classpath_sha256": hashlib.sha256(
            _cp(analysis_cp).encode("utf-8")).hexdigest(),
        "candidate_graph_sha256": _sha(graph),
        "static_scope_map_sha256": _sha(scope),
        "region_skeletons_sha256": _sha(skeletons)})
    recorded_classes = output / "recording-classes"
    # The original REGION_STATE pass writes its static-input digest beside
    # woven classes before Soot creates the output tree.
    recorded_classes.mkdir()
    static_artifacts = {str(path): _sha(path)
                        for path in (graph, scope, skeletons)}
    _run("region-state-weave", [
        java, f"-Dcausynth.communication.mappings={map_file}",
        "-Dcausynth.trace.mode=region-state",
        f"-Dcausynth.region.skeletons={skeletons}",
        f"-Dcausynth.output.dir={original}",
        "-cp", _original_cp(extra),
        "edu.uva.liftlab.graphchecker.GraphCheckerMain", "-i",
        str(source_classes), "-x", _cp(extra), "-o", str(recorded_classes)],
        output, 1800)
    if any(_sha(Path(path)) != digest
           for path, digest in static_artifacts.items()):
        raise ValueError("recording weave changed its static GraphChecker inputs")
    if weave.class_tree_digest(source_classes) != process_classes_sha:
        raise ValueError("recording weave preimage changed since static Soot analysis")
    post = _paths(profile["post_weave_classpath"], "post_weave_classpath")
    _run("recording-postweave", [java, "-cp", _original_cp(post),
        "edu.uva.liftlab.mallory.nativecampaign.NativeZooKeeperCombinedPostWeave",
        str(recorded_classes), _cp(extra)], output, 600)
    _atomic(output / "recording-weave-receipt.json", {
        "schema_version": 1, "mode": "original_graphchecker_region_state_weave",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "engine_jar_sha256": _sha(native.JAR),
        "input_classes": str(source_classes),
        "input_classes_sha256": weave.class_tree_digest(source_classes),
        "output_classes": str(recorded_classes),
        "output_classes_sha256": weave.class_tree_digest(recorded_classes)})
    trace = output / "healthy-trace"
    junit = request["original_junit"]
    runner_cp = _paths(profile["runner_classpath"], "runner_classpath")
    run_root = output / "healthy-junit"
    (run_root / "tmp").mkdir(parents=True)
    (run_root / "data").mkdir()
    env = os.environ.copy()
    env.update(CAUSYNTH_TRACE_OUTPUT_DIR=str(trace),
               CAUSYNTH_STATIC_SCOPE_MAP=str(scope))
    _run("healthy-junit", [java, "-Xmx3g",
        f"-Djava.io.tmpdir={run_root / 'tmp'}",
        f"-Dbuild.test.dir={run_root / 'data'}",
        "-Dcausynth.trace.mode=region-state",
        f"-Dcausynth.trace.test={junit['selector']}",
        "-cp", _original_cp([recorded_classes, *runner_cp]),
        "edu.uva.liftlab.graphchecker.runtime.NativeRecordingJUnitMethodRunner",
        junit["class"], junit["method"]], output,
        profile["timeout_seconds"], env)
    stdout = (output / "commands/healthy-junit.stdout").read_text(
        encoding="utf-8", errors="replace")
    manifest = _object(trace / "streaming_trace_manifest.json")
    if ("NATIVE_RECORDING_JUNIT_RESULT passed=1 failed=0" not in stdout or
            not _closed_trace_manifest(manifest)):
        raise ValueError("unchanged original JUnit or healthy recording did not close")
    occurrence_file = output / "target-occurrence.json"
    _run("target-occurrence", [java, "-cp", _original_cp([]),
        "edu.uva.liftlab.graphchecker.runtime.MalloryTargetOccurrenceResolver",
        "--trace-dir", str(trace), "--test", junit["selector"],
        "--candidate-graph", str(graph), "--static-scope-map", str(scope),
        "--region-skeletons", str(skeletons),
        "--output", str(occurrence_file)], output, 300)
    occurrence = _object(occurrence_file)
    if (occurrence.get("kind") != "MALLORY_OBSERVED_TARGET_OCCURRENCE" or
            occurrence.get("reachedEventCount", 0) < 1):
        raise ValueError("original runtime found no observed target check")
    recorded = output / "recorded-plan"
    scheduled = output / "scheduled-plan"
    target_arg = f"target={graph},{scope},{skeletons},{recorded}"
    selector = occurrence["selectedOccurrenceAddress"]
    _run("original-recorder", [java, "-cp", _original_cp([]),
        "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
        "--trace-dir", str(trace), "--test", junit["selector"],
        "--target", target_arg, "--target-occurrence", selector], output, 300)
    _run("original-scheduler", [java, "-cp", _original_cp([]),
        "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
        "--region-plan", str(recorded / "concolic_region_plan.jsonl"),
        "--candidate-graph", str(graph), "--static-scope-map", str(scope),
        "--output-dir", str(scheduled), "--max-jobs", str(profile["max_jobs"]),
        "--target-occurrence", selector], output, 300)
    plan = scheduled / "execution_task_plan.jsonl"
    task = select_target_task(plan, occurrence)
    branch = task["targetBranch"]
    anchor = f"{branch['siteId']}#{branch['occurrence']}"
    weave_file = output / "native-weave.json"
    _atomic(weave_file, {
        "java": java, "input_classes": str(source_classes),
        "output_classes": str(output / "concolic-classes"),
        "task_plan": str(plan), "task_id": task["taskId"],
        "region_skeletons": str(recorded / "region_skeletons.jsonl"),
        "dependency_classpath": _cp(extra),
        "native_fault_manifest": str(scope_out / "weave_manifest.json"),
        "post_weave": {"classpath": _original_cp(post),
            "main_class":
                "edu.uva.liftlab.mallory.nativecampaign.NativeZooKeeperCombinedPostWeave",
            "args": ["{woven_classes}", _cp(extra)]},
        "timeout_seconds": 1800})
    weave.run(weave_file)
    native_weave_receipt = _object(
        output / "concolic-classes/native-original-weave-receipt.json")
    if native_weave_receipt.get("input_classes_sha256") != process_classes_sha:
        raise ValueError("concolic weave preimage differs from static Soot analysis")
    config = {
        "case_id": request["case_id"], "target_site": anchor,
        "target_throw": {"siteId": identity["original_throw_site_id"],
                         "exceptionClass": request["target"]["target_exception"]},
        "native_weave_config": str(weave_file),
        "recording": {"trace_dir": str(trace), "test_id": junit["selector"],
                      "target_name": "target", "candidate_graph": str(graph),
                      "static_scope_map": str(scope),
                      "region_skeletons": str(skeletons),
                      "target_occurrence": selector,
                      "max_jobs": profile["max_jobs"]},
        "junit": {"class": junit["class"], "method": junit["method"]},
        "runner": {"zero_vm_java": java,
                   "main_class":
                       "edu.uva.liftlab.graphchecker.runtime.NativeJUnitMethodRunner",
                   "classpath": [str(path) for path in runner_cp],
                   "jvm_args": ["-Djava.io.tmpdir={trial_workdir}",
                                "-Dbuild.test.dir={trial_workdir}",
                                *profile.get("runner_jvm_args", [])]},
        "budget": profile["budget"],
        "timeout_seconds": profile["timeout_seconds"]}
    native._validate_config(config)
    _atomic(output / "case.json", config)
    proof = {
        "schema_version": 1, "mode": "original_graphchecker_native_adapter",
        "case_id": request["case_id"], "request_sha256": _digest(request),
        "target_identity": identity,
        "original_cluster_junit_verified": True,
        "class_preflight_path": str(output / "class-preflight.json"),
        "class_preflight_sha256": _sha(output / "class-preflight.json"),
        "static_sidecar_preflight_path": str(
            output / "static-sidecar-preflight.json"),
        "static_sidecar_preflight_sha256": _sha(
            output / "static-sidecar-preflight.json"),
        "scope_generated_by_original_graphchecker": True,
        "recording_closed": True,
        "junit": {"class": junit["class"], "method": junit["method"]},
        "source_evidence_paths": [str(Path(profile["source_root"]) /
                                      request["target"]["source_path"]),
                                  str(Path(profile["source_root"]) /
                                      junit["source_path"])],
        "static_scope_receipt_path": str(output / "static-scope-receipt.json"),
        "recording_weave_receipt_path": str(output / "recording-weave-receipt.json"),
        "target_occurrence_receipt_path": str(occurrence_file),
        "target_occurrence_receipt_sha256": _sha(occurrence_file),
        "protocol_gate_path": profile["protocol_gate"],
        "protocol_gate_sha256": _sha(Path(profile["protocol_gate"]))}
    _atomic(output / "adapter-proof.json", proof)
    return proof


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python -m Mallory.native_graphchecker_dispatch."
                         "zookeeper_native_adapter PROFILE REQUEST OUTPUT")
    print(json.dumps(prepare(Path(sys.argv[2]), Path(sys.argv[3]),
                             Path(sys.argv[1])), sort_keys=True))


if __name__ == "__main__":
    main()
