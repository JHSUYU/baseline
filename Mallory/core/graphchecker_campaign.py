"""One original-JUnit GraphChecker trial with a strict, native fault receipt.

This is deliberately independent of ``campaign.py``'s older event graph. The
only causal edges and closure identifiers accepted here come from
``TrialGraphMain``. Static Soot may-scope is a separate exploration tier, and
the old Mallory Probe event file is never an injection or target oracle.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .graphchecker_trial import analyze_trial

SCHEMA = 1
CONTROLLER = "MALLORY_GC_FAULT_PLAN"
IDENTITY = ("siteId", "node", "occurrenceId", "ordinal")
DEFAULT_RUNNER = "edu.uva.liftlab.mallory.graphchecker.weave.JUnitTrialMain"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _trace_stream(path: Path):
    """Open archived and legacy plain traces with the same byte semantics."""
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def _trace_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with _trace_stream(path) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _tree_sha256(root: Path) -> str:
    """Pin a fixture directory by names, file bytes and file types."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"trial cwd template contains a symlink: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            digest.update(bytes.fromhex(_sha256(path)))
        else:
            raise ValueError(f"trial cwd template contains a special file: {path}")
    return digest.hexdigest()


def _trial_arg(value: str, trial: Path, workdir: Path) -> str:
    return (value.replace("{trial_dir}", str(trial))
                 .replace("{trial_cwd}", str(workdir)))


def _archive_workdir(workdir: Path, trial: Path) -> dict[str, Any]:
    archive = trial / "workdir.tar.gz"
    temporary = trial / ".workdir.tar.gz.tmp"
    if archive.exists() or temporary.exists():
        raise FileExistsError(f"trial workdir archive already exists: {archive}")
    try:
        with temporary.open("wb") as stream:
            with tarfile.open(fileobj=stream, mode="w:gz") as tar:
                for path in sorted(workdir.rglob("*")):
                    tar.add(path, arcname=path.relative_to(workdir).as_posix(),
                            recursive=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(archive)
        with tarfile.open(archive, mode="r:gz") as tar:
            tar.getmembers()
        return {"path": archive.name, "encoding": "tar+gzip",
                "sha256": _sha256(archive), "bytes": archive.stat().st_size}
    finally:
        temporary.unlink(missing_ok=True)


def _archive_jsonl(path: Path, output: Path) -> dict[str, Any]:
    """Seal one durable gzip artifact before removing its plain source."""
    archived = output / (path.name + ".gz")
    temporary = archived.with_name("." + archived.name + ".tmp")
    if archived.exists() or temporary.exists():
        raise FileExistsError(f"GraphChecker trace archive already exists: {archived}")
    original_digest = hashlib.sha256()
    original_size = 0
    try:
        with path.open("rb") as source, temporary.open("wb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target,
                               mtime=0, compresslevel=6) as compressor:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    original_digest.update(block)
                    original_size += len(block)
                    compressor.write(block)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(archived)
        compressed_digest = _sha256(archived)
        observed_digest, observed_size = _trace_digest(archived)
        if (observed_digest != original_digest.hexdigest() or
                observed_size != original_size):
            raise ValueError(f"GraphChecker archive failed source verification: {archived}")
        path.unlink()
        return {"path": archived.name, "encoding": "gzip",
                "sha256": compressed_digest,
                "bytes": archived.stat().st_size,
                "content_sha256": observed_digest,
                "content_bytes": observed_size}
    finally:
        temporary.unlink(missing_ok=True)


def verify_trial_artifacts(trial: Path, result: dict[str, Any],
                           names: set[str] | None = None) -> None:
    """Fail closed if a completed native trial has lost or changed evidence."""
    if result.get("backend") != "graphchecker_native":
        return
    for filename, field in (("fault-plan.json", "fault_plan_sha256"),
                            ("graphchecker-feedback.json", "feedback_sha256")):
        expected = result.get(field)
        if expected is not None:
            path = trial / filename
            if not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"changed native trial receipt {field}: {path}")
    artifacts = result.get("artifacts")
    if artifacts is None:
        # Read-only compatibility for early pilot trials. New trials always
        # write gzip receipts; a resumed pilot must never be rerun simply
        # because its already completed evidence predates compression.
        legacy = {"raw_trace": ("graphchecker-raw.jsonl", "raw_trace_sha256"),
                  "window_trace": ("graphchecker-trace.jsonl", "trace_sha256"),
                  "graph": ("graphchecker-graph.jsonl", "graph_sha256")}
        for name, (filename, field) in legacy.items():
            if names is not None and name not in names:
                continue
            expected = result.get(field)
            if expected is None and result.get("status") == "invalid_graphchecker_trace":
                continue
            path = trial / filename
            if not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"changed legacy {name} evidence: {path}")
        return
    if not isinstance(artifacts, dict) or (
            "raw_trace" not in artifacts and result.get("raw_trace_sha256") is not None):
        raise ValueError(f"native trial has no archived raw trace receipt: {trial}")
    if result.get("status") != "invalid_graphchecker_trace" and not (
            {"raw_trace", "window_trace", "graph"} <= artifacts.keys()):
        raise ValueError(f"completed native trial lacks trace or graph archive: {trial}")
    if names is not None and not names.issubset(artifacts):
        raise ValueError(f"native trial lacks required trace archives {names}: {trial}")
    for name, receipt in artifacts.items():
        if names is not None and name not in names:
            continue
        if not isinstance(receipt, dict) or receipt.get("encoding") != "gzip":
            raise ValueError(f"invalid {name} archive receipt: {trial}")
        relative = receipt.get("path")
        if not isinstance(relative, str) or Path(relative).name != relative or (
                not relative.endswith(".jsonl.gz")):
            raise ValueError(f"invalid {name} archive path: {trial}")
        archive = trial / relative
        if (not archive.is_file() or archive.stat().st_size != receipt.get("bytes") or
                _sha256(archive) != receipt.get("sha256")):
            raise ValueError(f"changed {name} compressed evidence: {archive}")
        digest, size = _trace_digest(archive)
        if digest != receipt.get("content_sha256") or size != receipt.get("content_bytes"):
            raise ValueError(f"changed {name} source evidence: {archive}")
        result_field = {"raw_trace": "raw_trace_sha256",
                        "window_trace": "trace_sha256",
                        "graph": "graph_sha256"}.get(name)
        if result_field and result.get(result_field) != digest:
            raise ValueError(f"{name} archive disagrees with result receipt: {trial}")
    workdir = result.get("workdir_artifact")
    if workdir is not None:
        if (not isinstance(workdir, dict) or
                workdir.get("path") != "workdir.tar.gz" or
                workdir.get("encoding") != "tar+gzip"):
            raise ValueError(f"invalid trial workdir receipt: {trial}")
        path = trial / "workdir.tar.gz"
        if (not path.is_file() or path.stat().st_size != workdir.get("bytes") or
                _sha256(path) != workdir.get("sha256")):
            raise ValueError(f"changed trial workdir evidence: {path}")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _process_start_ticks(pid: int) -> str | None:
    try:
        # /proc/<pid>/stat field 22; the second field may contain spaces.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return fields[19]
    except (OSError, IndexError):
        return None


def _path(value: Any, base: Path, name: str, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} needs a nonempty path")
    path = (base / value).resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise FileNotFoundError(f"{name} missing: {path}")
    return path


def _paths(value: Any, base: Path, name: str) -> list[Path]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} needs a nonempty path list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{name} needs nonempty paths")
        path = (base / item).resolve()
        if not (path.is_file() or path.is_dir()):
            raise FileNotFoundError(f"{name} missing: {path}")
        result.append(path)
    return result


def _classpath_sha256(entries: list[Any]) -> str:
    return hashlib.sha256(os.pathsep.join(map(str, entries)).encode("utf-8")).hexdigest()


def _exact_classpath(value: Any) -> list[str]:
    """Keep Soot's exact path spelling and order, including symlinks."""
    if not isinstance(value, list) or not value:
        raise ValueError("soot_dependency_classpath needs the ordered analysis.classpath list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("Soot dependency classpath needs absolute path entries")
        for part in item.split(os.pathsep):
            path = Path(part)
            if not part or not path.is_absolute():
                raise ValueError("Soot dependency classpath needs absolute path entries")
            if not path.exists():
                raise FileNotFoundError(f"Soot dependency classpath entry missing: {path}")
        result.append(item)
    return result


def _runtime_classpath(config: dict[str, Any]) -> list[Path | str]:
    if config["explicit_soot_dependency_classpath"]:
        # Match the planner's process_dirs before its ordered dependency CP.
        # The generic weaver/runner jars are appended only after application
        # and test dependencies, so they cannot silently shadow source types.
        return [*config["original_class_dirs"],
                *config["soot_dependency_classpath"],
                *config["test_classpath"], *config["tool_classpath"]]
    return [*config["tool_classpath"], *config["original_class_dirs"],
            *config["test_classpath"]]


def _runner_class_sha256(class_name: str, classpath: list[Path | str]) -> str:
    """Pin the first runner class found in effective classpath order."""
    resource = class_name.replace(".", "/") + ".class"
    for item in classpath:
        entry = Path(item)
        if entry.is_dir():
            candidate = entry / resource
            if candidate.is_file():
                return hashlib.sha256(candidate.read_bytes()).hexdigest()
        elif zipfile.is_zipfile(entry):
            with zipfile.ZipFile(entry) as archive:
                try:
                    return hashlib.sha256(archive.read(resource)).hexdigest()
                except KeyError:
                    continue
    raise FileNotFoundError(f"runner class absent from effective classpath: {class_name}")


def _java_feature_version(java: str) -> int:
    completed = subprocess.run([java, "-version"], capture_output=True,
                               text=True, timeout=15, check=True)
    version = re.search(r'\bversion\s+"([^"]+)"',
                        completed.stderr + completed.stdout)
    if version is None:
        raise ValueError(f"cannot determine configured Java version: {java}")
    numbers = re.findall(r"\d+", version.group(1))
    if not numbers:
        raise ValueError(f"invalid configured Java version: {java}")
    feature = int(numbers[1] if numbers[0] == "1" and len(numbers) > 1
                  else numbers[0])
    if feature < 8:
        raise ValueError(f"GraphChecker requires Java 8 or newer: {java}")
    return feature


def _class_major(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(8)
    if len(header) != 8 or header[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError(f"not a Java class file: {path}")
    return int.from_bytes(header[6:8], "big")


def _check_woven_major(path: Path, feature: int,
                       original_major: int | None = None) -> int:
    actual = _class_major(path)
    maximum = feature + 44
    if actual > maximum:
        raise ValueError(f"woven class major {actual} exceeds Java {feature} max "
                         f"{maximum}: {path}")
    if original_major is not None and original_major <= 52 and actual > original_major:
        raise ValueError(f"woven class major {actual} exceeds Java 8-or-earlier "
                         f"source major {original_major}: {path}")
    return actual


def _runner(raw: Any, junit: dict[str, Any]) -> dict[str, Any]:
    if raw is None:
        args = [junit["class"], junit["method"]]
        if "parameter_index" in junit:
            args.append(str(junit["parameter_index"]))
        return {"main_class": DEFAULT_RUNNER, "args": args, "jvm_args": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("main_class"), str):
        raise ValueError("runner needs a Java main_class")
    main_class = raw["main_class"]
    if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+", main_class):
        raise ValueError("runner main_class is not a Java binary name")
    args = raw.get("args")
    jvm_args = raw.get("jvm_args", [])
    if not isinstance(args, list) or not args or not all(
            isinstance(item, str) and item for item in args):
        raise ValueError("runner args need a nonempty argv array")
    if not isinstance(jvm_args, list) or not all(
            isinstance(item, str) and item for item in jvm_args):
        raise ValueError("runner jvm_args need an argv array")
    if any("-javaagent:" in item for item in jvm_args):
        raise ValueError("runner cannot attach a second Java instrumentation agent")
    substitutions = {"{class}": junit["class"], "{method}": junit["method"]}
    substitutions["{trial_dir}"] = "{trial_dir}"
    substitutions["{trial_cwd}"] = "{trial_cwd}"
    if "parameter_index" in junit:
        substitutions["{parameter_index}"] = str(junit["parameter_index"])
    resolved = []
    for item in args:
        if item.startswith("{") and item.endswith("}"):
            if item not in substitutions:
                raise ValueError(f"unknown runner placeholder: {item}")
            resolved.append(substitutions[item])
        else:
            resolved.append(item)
    return {"main_class": main_class, "args": resolved, "jvm_args": jvm_args}


def _post_weave(raw: Any) -> dict[str, Any] | None:
    """Validate an optional system-wide bytecode adapter after Soot weaving."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("post_weave needs a Java main_class and argv")
    main_class = raw.get("main_class")
    if not isinstance(main_class, str) or not re.fullmatch(
            r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+", main_class):
        raise ValueError("post_weave main_class is not a Java binary name")
    args = raw.get("args")
    jvm_args = raw.get("jvm_args", [])
    if not isinstance(args, list) or not args or not all(
            isinstance(item, str) and item for item in args):
        raise ValueError("post_weave args need a nonempty argv array")
    if "{final_woven}" not in args or "{generic_woven}" not in args:
        raise ValueError("post_weave must name generic and final woven directories")
    allowed = {"{generic_woven}", "{final_woven}", "{classpath}"}
    if any(item.startswith("{") and item.endswith("}") and item not in allowed
           for item in args):
        raise ValueError("post_weave has an unknown placeholder")
    if not isinstance(jvm_args, list) or not all(
            isinstance(item, str) and item for item in jvm_args):
        raise ValueError("post_weave jvm_args need an argv array")
    if any("-javaagent:" in item for item in jvm_args):
        raise ValueError("post_weave cannot attach a Java instrumentation agent")
    return {"main_class": main_class, "args": args, "jvm_args": jvm_args}


def _manifest_target(manifest: dict[str, Any], target: dict[str, Any]) -> list[dict[str, Any]]:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise ValueError("weave manifest has no target sites")
    throw = [row for row in targets if isinstance(row, dict)
             and row.get("siteId") == target["throw_site_id"]
             and row.get("kind") == "THROW"]
    if len(throw) != 1 or throw[0].get("exceptionClass") != target["exception_class"]:
        raise ValueError("exact target throw site/type is absent or ambiguous in weave manifest")
    selected = [throw[0]]
    for check in _configured_check_sites(target):
        rows = [row for row in targets if isinstance(row, dict)
                and row.get("siteId") == check
                and row.get("kind") in {"BRANCH", "SWITCH"}]
        if len(rows) != 1:
            raise ValueError("exact target branch is absent or ambiguous in weave manifest")
        selected.extend(rows)
    return selected


def _configured_check_sites(target: dict[str, Any]) -> list[str]:
    sites = target.get("check_site_ids", target.get("all_check_site_ids"))
    primary = target.get("check_site_id")
    if sites is None:
        return [primary] if primary else []
    if (not isinstance(sites, list) or not sites or
            any(not isinstance(site, str) or not site for site in sites) or
            len(set(sites)) != len(sites)):
        raise ValueError("target check_site_ids needs unique nonempty site IDs")
    if primary is not None:
        if primary not in sites:
            raise ValueError("target check_site_id is absent from check_site_ids")
        return [primary, *(site for site in sites if site != primary)]
    return sites


def load_config(path: Path) -> dict[str, Any]:
    """Resolve and validate the immutable inputs of a prepared trial.

    A fresh directory is mandatory for each trial. No command string or shell
    interpolation is accepted; JUnit's class and method are passed as argv.
    """
    raw = _json(path)
    base = path.resolve().parent
    if raw.get("schema_version") != SCHEMA:
        raise ValueError("unsupported GraphChecker campaign config schema")
    if not isinstance(raw.get("case_id"), str) or not raw["case_id"]:
        raise ValueError("case_id must be a nonempty string")
    junit = raw.get("junit")
    target = raw.get("target")
    if not isinstance(junit, dict) or not all(
            isinstance(junit.get(key), str) and junit[key]
            for key in ("class", "method")):
        raise ValueError("junit needs original class and method")
    if "parameter_index" in junit and (not isinstance(junit["parameter_index"], int)
                                       or junit["parameter_index"] < 0):
        raise ValueError("parameter_index must be a nonnegative integer")
    if not isinstance(target, dict) or not all(
            isinstance(target.get(key), str) and target[key]
            for key in ("throw_site_id", "exception_class")):
        raise ValueError("target needs exact throw_site_id and exception_class")
    if target.get("check_site_id") is not None and (
            not isinstance(target["check_site_id"], str) or
            not target["check_site_id"]):
        raise ValueError("check_site_id must be a nonempty string")
    _configured_check_sites(target)
    timeout = raw.get("timeout_seconds", 600)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    manifest_path = _path(raw.get("weave_manifest"), base, "weave_manifest")
    manifest = _json(manifest_path)
    if manifest.get("faultController", "NONE") not in {"NONE", CONTROLLER}:
        raise ValueError("legacy MALLORY_PROBE cannot be used as a GraphChecker fault receipt")
    target_site_rows = _manifest_target(manifest, target)
    _door_types(manifest)
    static_map = _path(raw.get("static_scope_map"), base, "static_scope_map")
    if "original_class_dirs" in raw:
        originals = _paths(raw["original_class_dirs"], base, "original_class_dirs")
        if not all(path.is_dir() for path in originals):
            raise ValueError("original_class_dirs must contain only directories")
    else:
        originals = [_path(raw.get("original_classes"), base, "original_classes",
                           directory=True)]
    tool_cp = _paths(raw.get("tool_classpath"), base, "tool_classpath")
    test_cp = _paths(raw.get("test_classpath"), base, "test_classpath")
    explicit_soot_cp = "soot_dependency_classpath" in raw
    soot_cp = (_exact_classpath(raw["soot_dependency_classpath"])
               if explicit_soot_cp else
               [*tool_cp, *originals, *test_cp])
    soot_cp_sha256 = _classpath_sha256(soot_cp)
    declared_soot_cp_sha256 = manifest.get("sootDependencyClasspathSha256")
    if explicit_soot_cp and (not isinstance(declared_soot_cp_sha256, str) or
                             declared_soot_cp_sha256 != soot_cp_sha256):
        raise ValueError("ordered Soot dependency classpath differs from static "
                         "weave manifest; supply analysis.classpath as "
                         "soot_dependency_classpath without reordering")
    runtime_cp = ([*originals, *soot_cp, *test_cp, *tool_cp]
                  if explicit_soot_cp else [*tool_cp, *originals, *test_cp])
    graph_jar = _path(raw.get("graph_jar"), base, "graph_jar")
    cwd = _path(raw.get("cwd"), base, "cwd", directory=True)
    java = raw.get("java", "java")
    if not isinstance(java, str) or not java or os.path.sep in java and not Path(java).is_file():
        raise ValueError("java must be an executable name or existing path")
    java_feature = _java_feature_version(java)
    runner = _runner(raw.get("runner"), junit)
    _runner_class_sha256(runner["main_class"], runtime_cp)
    post_weave = _post_weave(raw.get("post_weave"))
    if post_weave is not None:
        _runner_class_sha256(post_weave["main_class"], runtime_cp)
    trial_cwd_template = (_path(raw["trial_cwd_template"], base,
                                "trial_cwd_template", directory=True)
                          if "trial_cwd_template" in raw else None)
    template_sha256 = (_tree_sha256(trial_cwd_template)
                       if trial_cwd_template is not None else None)
    return {"schema_version": SCHEMA, "config_sha256": _sha256(path),
            "case_id": raw.get("case_id"),
            "junit": junit, "target": target,
            "target_site_rows": target_site_rows, "timeout_seconds": timeout,
            "weave_manifest": manifest_path, "static_scope_map": static_map,
            "original_class_dirs": originals, "tool_classpath": tool_cp,
            "test_classpath": test_cp, "graph_jar": graph_jar,
            "soot_dependency_classpath": soot_cp,
            "soot_dependency_classpath_sha256": soot_cp_sha256,
            "explicit_soot_dependency_classpath": explicit_soot_cp,
            "cwd": cwd, "java": java, "java_feature_version": java_feature,
            "runner": runner,
            "post_weave": post_weave,
            "trial_cwd_template": trial_cwd_template,
            "trial_cwd_template_sha256": template_sha256}


def prepare(config: dict[str, Any], output: Path) -> Path:
    """Weave selected original classes once, with native GraphChecker faults.

    The static manifest is copied and its controller switched generically;
    selected class hashes in the receipt pin the bytecode used by later trials.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    manifest = _json(config["weave_manifest"])
    _manifest_target(manifest, config["target"])
    manifest["faultController"] = CONTROLLER
    selected_classes = sorted({row["clazz"] for group in
                               ("regions", "targets", "coverage", "frames", "doors")
                               for row in manifest.get(group, [])
                               if isinstance(row, dict) and isinstance(row.get("clazz"), str)})
    if not selected_classes:
        raise ValueError("weave manifest selected no classes")
    original_hashes = {}
    original_majors = {}
    stage = output / "selected-original"
    for clazz in selected_classes:
        relative = Path(clazz.replace(".", "/") + ".class")
        path = next((directory / relative for directory in config["original_class_dirs"]
                     if (directory / relative).is_file()), None)
        if path is None:
            raise FileNotFoundError(f"selected class absent from original_class_dirs: {clazz}")
        original_hashes[clazz] = {"path": str(path), "sha256": _sha256(path)}
        original_majors[clazz] = _class_major(path)
        if original_majors[clazz] > config["java_feature_version"] + 44:
            raise ValueError(f"original class major {original_majors[clazz]} exceeds "
                             f"configured Java {config['java_feature_version']}: {path}")
        copy = stage / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copy)
    effective_manifest = output / "weave-manifest.json"
    _write_json(effective_manifest, manifest)
    woven = output / "woven"
    dependency_cp = os.pathsep.join(map(str, config["soot_dependency_classpath"]))
    launch_cp = os.pathsep.join(map(str, [*config["tool_classpath"],
                                           *config["soot_dependency_classpath"],
                                           *config["original_class_dirs"],
                                           *config["test_classpath"]]))
    argv = [config["java"], "-cp", launch_cp,
            "edu.uva.liftlab.mallory.graphchecker.weave.WeaveMain",
            str(effective_manifest), str(stage), str(woven), dependency_cp]
    with (output / "weave.stdout.log").open("wb") as stdout, (
            output / "weave.stderr.log").open("wb") as stderr:
        subprocess.run(argv, cwd=config["cwd"], check=True, timeout=1800,
                       stdout=stdout, stderr=stderr)
    woven_hashes = {}
    woven_majors = {}
    for clazz in selected_classes:
        path = woven / (clazz.replace(".", "/") + ".class")
        if not path.is_file():
            raise ValueError(f"weave omitted selected class: {clazz}")
        woven_hashes[clazz] = _sha256(path)
        woven_majors[clazz] = _check_woven_major(
            path, config["java_feature_version"], original_majors[clazz])
    post = config["post_weave"]
    post_hashes: dict[str, str] = {}
    post_argv: list[str] | None = None
    post_main_sha256: str | None = None
    if post is not None:
        final = output / "woven-post"
        post_cp = os.pathsep.join(map(str, [woven, *_runtime_classpath(config)]))
        substitutions = {"{generic_woven}": str(woven),
                         "{final_woven}": str(final),
                         "{classpath}": post_cp}
        post_argv = [config["java"], *post["jvm_args"], "-cp", post_cp,
                     post["main_class"],
                     *(substitutions.get(item, item) for item in post["args"])]
        post_main_sha256 = _runner_class_sha256(
            post["main_class"], _runtime_classpath(config))
        with (output / "post-weave.stdout.log").open("wb") as stdout, (
                output / "post-weave.stderr.log").open("wb") as stderr:
            subprocess.run(post_argv, cwd=config["cwd"], check=True,
                           timeout=1800, stdout=stdout, stderr=stderr)
        if not final.is_dir():
            raise ValueError("post_weave did not create final woven directory")
        post_hashes = {path.relative_to(final).as_posix(): _sha256(path)
                       for path in sorted(final.rglob("*.class"))}
        if not post_hashes:
            raise ValueError("post_weave did not emit any class")
        for path in sorted(final.rglob("*.class")):
            clazz = path.relative_to(final).as_posix()[:-6].replace("/", ".")
            _check_woven_major(path, config["java_feature_version"],
                               original_majors.get(clazz))
    _write_json(output / "weave-receipt.json", {
        "schema_version": SCHEMA, "controller": CONTROLLER,
        "config_sha256": config["config_sha256"],
        "source_manifest_sha256": _sha256(config["weave_manifest"]),
        "effective_manifest_sha256": _sha256(effective_manifest),
        "static_scope_map_sha256": _sha256(config["static_scope_map"]),
        "graph_jar_sha256": _sha256(config["graph_jar"]),
        "soot_dependency_classpath_sha256": config["soot_dependency_classpath_sha256"],
        "soot_dependency_classpath": list(map(str, config["soot_dependency_classpath"])),
        "runtime_classpath": list(map(str, _runtime_classpath(config))),
        "java_feature_version": config["java_feature_version"],
        "runner_class_sha256": _runner_class_sha256(
            config["runner"]["main_class"], _runtime_classpath(config)),
        "junit_class_sha256": _runner_class_sha256(
            config["junit"]["class"], _runtime_classpath(config)),
        "original_class_sha256": original_hashes,
        "original_class_major": original_majors,
        "woven_class_sha256": woven_hashes,
        "woven_class_major": woven_majors, "weave_argv": argv,
        "post_weave_main_sha256": post_main_sha256,
        "post_woven_class_sha256": post_hashes,
        "post_weave_argv": post_argv,
        "trial_cwd_template_sha256": config["trial_cwd_template_sha256"]})
    return output


def _verify_prepared(config: dict[str, Any], prepared: Path) -> list[Path]:
    receipt = _json(prepared / "weave-receipt.json")
    if (receipt.get("controller") != CONTROLLER or
            receipt.get("config_sha256") != config["config_sha256"] or
            receipt.get("source_manifest_sha256") != _sha256(config["weave_manifest"]) or
            receipt.get("static_scope_map_sha256") != _sha256(config["static_scope_map"]) or
            receipt.get("graph_jar_sha256") != _sha256(config["graph_jar"]) or
            receipt.get("soot_dependency_classpath_sha256",
                        config["soot_dependency_classpath_sha256"]) !=
            config["soot_dependency_classpath_sha256"] or
            (receipt.get("soot_dependency_classpath") is not None and
             receipt["soot_dependency_classpath"] !=
             list(map(str, config["soot_dependency_classpath"]))) or
            (receipt.get("runtime_classpath") is not None and
             receipt["runtime_classpath"] !=
             list(map(str, _runtime_classpath(config)))) or
            receipt.get("java_feature_version", config["java_feature_version"]) !=
            config["java_feature_version"] or
            receipt.get("runner_class_sha256") != _runner_class_sha256(
                config["runner"]["main_class"], _runtime_classpath(config)) or
            receipt.get("junit_class_sha256") != _runner_class_sha256(
                config["junit"]["class"], _runtime_classpath(config)) or
            receipt.get("effective_manifest_sha256") != _sha256(
                prepared / "weave-manifest.json") or
            receipt.get("trial_cwd_template_sha256") != config["trial_cwd_template_sha256"] or
            (config["trial_cwd_template"] is not None and
             _tree_sha256(config["trial_cwd_template"]) !=
             config["trial_cwd_template_sha256"])):
        raise ValueError("prepared weave inputs changed")
    for clazz, source in receipt.get("original_class_sha256", {}).items():
        path = Path(source["path"])
        if (not any(path.is_relative_to(directory) for directory in
                    config["original_class_dirs"]) or
                _sha256(path) != source["sha256"]):
            raise ValueError(f"original selected class changed: {clazz}")
        major = _class_major(path)
        if (major > config["java_feature_version"] + 44 or
                (receipt.get("original_class_major") and
                 receipt["original_class_major"].get(clazz) != major)):
            raise ValueError(f"original class major incompatible or changed: {path}")
    for clazz, expected in receipt.get("woven_class_sha256", {}).items():
        path = prepared / "woven" / (clazz.replace(".", "/") + ".class")
        if _sha256(path) != expected:
            raise ValueError(f"prepared woven class changed: {clazz}")
        original = receipt["original_class_sha256"].get(clazz)
        original_major = _class_major(Path(original["path"])) if original else None
        major = _check_woven_major(path, config["java_feature_version"], original_major)
        if (receipt.get("woven_class_major") and
                receipt["woven_class_major"].get(clazz) != major):
            raise ValueError(f"prepared woven class major changed: {clazz}")
    post = config["post_weave"]
    post_hashes = receipt.get("post_woven_class_sha256")
    if post is None:
        if receipt.get("post_weave_main_sha256") is not None or post_hashes:
            raise ValueError("unexpected post-weave classes in prepared receipt")
        return [prepared / "woven"]
    if not isinstance(post_hashes, dict) or not post_hashes or (
            receipt.get("post_weave_main_sha256") != _runner_class_sha256(
                post["main_class"], _runtime_classpath(config))):
        raise ValueError("post-weave adapter or receipt changed")
    final = prepared / "woven-post"
    found = {path.relative_to(final).as_posix(): _sha256(path)
             for path in sorted(final.rglob("*.class"))}
    if found != post_hashes:
        raise ValueError("post-weave classes changed")
    for path in sorted(final.rglob("*.class")):
        clazz = path.relative_to(final).as_posix()[:-6].replace("/", ".")
        original = receipt["original_class_sha256"].get(clazz)
        original_major = _class_major(Path(original["path"])) if original else None
        _check_woven_major(path, config["java_feature_version"], original_major)
    return [final, prepared / "woven"]


def _door_types(manifest: dict[str, Any]) -> dict[str, str]:
    types: dict[str, str] = {}
    for door in manifest.get("doors", []):
        if not isinstance(door, dict) or not isinstance(door.get("siteId"), str):
            raise ValueError("weave manifest has an invalid fault door")
        site = door["siteId"]
        fault_type = door.get("exceptionClass")
        if not site or not isinstance(fault_type, str) or not fault_type:
            raise ValueError(f"fault door {site!r} has no typed exception class")
        if site in types and types[site] != fault_type:
            raise ValueError(f"fault door {site!r} has conflicting exception classes")
        types[site] = fault_type
    return types


def validate_plan(plan: dict[str, Any],
                  door_types: dict[str, str] | None = None) -> list[dict[str, Any]]:
    faults = plan.get("faults")
    if not isinstance(faults, list):
        raise ValueError("native fault plan needs a faults array")
    for index, fault in enumerate(faults):
        if not isinstance(fault, dict) or not all(
                isinstance(fault.get(key), str) and fault[key]
                for key in (*IDENTITY[:3], "exceptionClass")):
            raise ValueError(f"fault {index} lacks exact site/node/occurrence/type")
        if not isinstance(fault.get("ordinal"), int) or isinstance(
                fault["ordinal"], bool) or fault["ordinal"] <= 0:
            raise ValueError(f"fault {index} needs positive ordinal")
        if "replayOccurrenceId" in fault and (not isinstance(
                fault["replayOccurrenceId"], str) or not fault["replayOccurrenceId"]):
            raise ValueError(f"fault {index} needs a nonempty replay occurrence ID")
        if door_types is not None and door_types.get(fault["siteId"]) != fault["exceptionClass"]:
            raise ValueError(f"fault {index} does not match a typed selected door")
    return faults


def load_trace(path: Path, *, max_bytes: int = 256 * 1024 * 1024) -> list[dict[str, Any]]:
    """Read only the JUnit window; preserve the raw file separately.

    Embedded-cluster threads can emit after teardown until process exit.
    Those rows are real raw evidence but cannot influence this trial's graph.
    """
    if not path.is_file():
        raise ValueError(f"GraphChecker trace missing: {path}")
    rows: list[dict[str, Any]] = []
    prior = 0
    consumed = 0
    with _trace_stream(path) as stream:
        for number, line in enumerate(stream, 1):
            consumed += len(line)
            if consumed > max_bytes:
                raise ValueError(f"GraphChecker trace over {max_bytes} decoded bytes: {path}")
            if not line.endswith(b"\n"):
                raise ValueError(f"incomplete GraphChecker row {number}: {path}")
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("kind"), str):
                raise ValueError(f"invalid GraphChecker row {number}: {path}")
            seq = row.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= prior:
                raise ValueError(f"nonmonotone GraphChecker seq at row {number}: {path}")
            prior = seq
            rows.append(row)
    kinds = [row["kind"] for row in rows]
    if (kinds.count("WINDOW_OPEN") != 1 or kinds.count("WINDOW_CLOSE") != 1 or
            kinds.index("WINDOW_OPEN") >= kinds.index("WINDOW_CLOSE")):
        raise ValueError("GraphChecker trace lacks one complete JUnit window")
    return rows[kinds.index("WINDOW_OPEN"):kinds.index("WINDOW_CLOSE") + 1]


def scan_window_trace(path: Path, output: Path | None = None, *,
                      selected_kinds: set[str] | None = None,
                      max_bytes: int = 4 * 1024 * 1024 * 1024
                      ) -> tuple[list[dict[str, Any]], int]:
    """Validate and stream one JUnit window, retaining only oracle/door rows.

    Full HDFS traces may exceed a gigabyte. The graph still receives every
    window row, while Python retains only the rows used for fault selection
    and the exact target oracle. Raw bytes are copied unchanged into output.
    """
    selected = selected_kinds if selected_kinds is not None else {
        "FAULT_DOOR", "FAULT_APPLIED", "TARGET_CHECK", "TARGET_THROW"}
    rows: list[dict[str, Any]] = []
    previous = 0
    opened = False
    closed = False
    count = 0
    consumed = 0
    if not path.is_file():
        raise ValueError(f"GraphChecker trace missing: {path}")
    with _trace_stream(path) as source, (
            output.open("wb") if output is not None else open(os.devnull, "wb")) as target:
        for number, line in enumerate(source, 1):
            consumed += len(line)
            if consumed > max_bytes:
                raise ValueError(f"GraphChecker trace over {max_bytes} decoded bytes: {path}")
            if not line.endswith(b"\n"):
                raise ValueError(f"incomplete GraphChecker row {number}: {path}")
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("kind"), str):
                raise ValueError(f"invalid GraphChecker row {number}: {path}")
            seq = row.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= previous:
                raise ValueError(f"nonmonotone GraphChecker seq at row {number}: {path}")
            previous = seq
            kind = row["kind"]
            if kind == "WINDOW_OPEN":
                if opened:
                    raise ValueError(f"multiple GraphChecker windows: {path}")
                opened = True
            if opened and not closed:
                target.write(line)
                count += 1
                if kind in selected:
                    rows.append(row)
            if kind == "WINDOW_CLOSE":
                if not opened or closed:
                    raise ValueError(f"GraphChecker window closes without an open: {path}")
                closed = True
    if not opened or not closed:
        raise ValueError(f"GraphChecker trace lacks one complete JUnit window: {path}")
    return rows, count


def _identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("siteId"), row.get("node"), row.get("occurrenceId"),
            row.get("doorOrdinal"))


def _plan_identity(fault: dict[str, Any]) -> tuple[Any, ...]:
    return (fault["siteId"], fault["node"], fault["occurrenceId"],
            fault["ordinal"])


def _planned_fault_matches(fault: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Replay selector may differ from the exact occurrence in this trial.

    The exact occurrence remains on the applied row for graph ancestry and
    must also appear on a preceding FAULT_DOOR row in the same trial.
    """
    if fault.get("replayOccurrenceId"):
        return (actual.get("siteId") == fault["siteId"] and
                actual.get("node") == fault["node"] and
                actual.get("replayOccurrenceId") == fault["replayOccurrenceId"] and
                actual.get("doorOrdinal") == fault["ordinal"] and
                bool(actual.get("occurrenceId")))
    return _identity(actual) == _plan_identity(fault)


def summarize_evidence(rows: list[dict[str, Any]], graph: dict[str, Any],
                       target: dict[str, Any], faults: list[dict[str, Any]],
                       door_types: dict[str, str] | None = None) -> dict[str, Any]:
    """Return strict runtime identity, exact target oracle, and door tiers."""
    check_sites = _configured_check_sites(target)
    if graph.get("schemaVersion") != SCHEMA or graph.get("targetSite") != (
            check_sites[0] if check_sites else target["throw_site_id"]):
        raise ValueError("GraphChecker feedback does not match selected target")
    if len(check_sites) > 1 and graph.get("configuredTargetSites") != check_sites:
        raise ValueError("GraphChecker feedback omitted target guard configuration")
    closure = set(graph.get("closureOccurrenceIds", []))
    cutoffs = graph.get("closureOccurrenceCutoffs", {})
    if not isinstance(cutoffs, dict):
        raise ValueError("GraphChecker closure cutoff map is invalid")
    if target.get("check_site_id") and graph.get("staticScopeTargetFound") is not True:
        raise ValueError("static may-scope does not contain the selected target")
    may_sites = set(graph.get("staticMayObservedDoorSiteIds", []))
    doors = [row for row in rows if row["kind"] == "FAULT_DOOR"
             and all(row.get(key) for key in ("siteId", "node", "occurrenceId"))
             and isinstance(row.get("doorOrdinal"), int)
             and row["doorOrdinal"] > 0]
    applied = [row for row in rows if row["kind"] == "FAULT_APPLIED"]
    strict = bool(faults) and len(applied) == len(faults)
    matched: list[dict[str, Any]] = []
    previous_seq = -1
    for fault, actual in zip(faults, applied):
        source = next((door for door in doors if _identity(door) == _identity(actual)
                       and door["seq"] < actual["seq"]), None)
        if (not _planned_fault_matches(fault, actual) or
                (fault.get("replayOccurrenceId") and source is not None and
                 source.get("replayOccurrenceId") != actual.get("replayOccurrenceId")) or
                actual.get("exceptionClass") != fault["exceptionClass"] or
                actual["seq"] <= previous_seq or source is None):
            strict = False
            break
        matched.append(actual)
        previous_seq = actual["seq"]
    if len(matched) != len(faults):
        strict = False
    last_fault_seq = applied[-1]["seq"] if strict and applied else None
    checks = [row for row in rows if row["kind"] == "TARGET_CHECK"
              and row.get("siteId") in check_sites and row.get("occurrenceId")
              and row.get("node")] if check_sites else []
    throws = [row for row in rows if row["kind"] == "TARGET_THROW"
              and row.get("siteId") == target["throw_site_id"]
              and row.get("exceptionClass") == target["exception_class"]
              and row.get("occurrenceId") and row.get("node")]
    exact = []
    for thrown in throws:
        if last_fault_seq is None or thrown["seq"] <= last_fault_seq:
            continue
        exact.append(thrown)
    check_preceded_throws = [thrown for thrown in exact if any(
        check["seq"] < thrown["seq"] and
        check["occurrenceId"] == thrown["occurrenceId"] and
        check["node"] == thrown["node"] for check in checks)]
    throw_closures = graph.get("targetThrowClosures", [])
    if not isinstance(throw_closures, list):
        raise ValueError("GraphChecker target throw closure list is invalid")
    causal_throw_seqs = []
    for thrown in exact:
        for anchored in throw_closures:
            if not isinstance(anchored, dict) or any(
                    anchored.get(key) != thrown.get(key) for key in (
                        "seq", "siteId", "exceptionClass", "node", "occurrenceId")):
                continue
            throw_cutoffs = anchored.get("closureOccurrenceCutoffs")
            if not isinstance(throw_cutoffs, dict):
                raise ValueError("GraphChecker target throw cutoff map is invalid")
            fault_cutoff = throw_cutoffs.get(applied[-1]["occurrenceId"])
            if strict and isinstance(fault_cutoff, int) and applied[-1]["seq"] < fault_cutoff:
                causal_throw_seqs.append(thrown["seq"])
            break
    target_reached = bool(graph.get("targetReached") and (checks or throws))
    post_fault_target = bool(last_fault_seq is not None and any(
        row["seq"] > last_fault_seq for row in (*checks, *throws)))
    fault_occurrences_in_closure = [
        actual["occurrenceId"] for actual in applied if
        actual.get("occurrenceId") in closure and
        isinstance(cutoffs.get(actual["occurrenceId"]), int) and
        actual["seq"] < cutoffs[actual["occurrenceId"]]]
    injection_specific_target = bool(
        strict and target_reached and applied and
        applied[-1]["occurrenceId"] in closure and
        isinstance(cutoffs.get(applied[-1]["occurrenceId"]), int) and
        applied[-1]["seq"] < cutoffs[applied[-1]["occurrenceId"]])
    eligible = []
    for door in doors:
        cutoff = cutoffs.get(door["occurrenceId"])
        if door["occurrenceId"] in closure and isinstance(cutoff, int) and door["seq"] <= cutoff:
            tier = "observed_closure"
        elif door["occurrenceId"] in closure and isinstance(cutoff, int):
            tier = "after_target"
        elif door["siteId"] in may_sites:
            tier = "static_may_observed"
        elif door["siteId"] in (door_types or {}):
            # Instrumented and observed in this JUnit run, but the static
            # selection alone cannot establish an observed causal edge.
            tier = "selected_scope_observed"
        else:
            tier = "outside_closure"
        eligible.append({"siteId": door["siteId"], "node": door["node"],
                         "occurrenceId": door["occurrenceId"],
                         **({"replayOccurrenceId": door["replayOccurrenceId"]}
                            if door.get("replayOccurrenceId") else {}),
                         "ordinal": door["doorOrdinal"], "seq": door["seq"],
                         "tier": tier,
                         "exceptionClass": (door_types or {}).get(door["siteId"])})
    return {"strict_injection": strict, "applied_faults": len(applied),
            "actual_fault_occurrence_ids": [row["occurrenceId"] for row in matched]
            if strict else [],
            "planned_faults": len(faults), "last_fault_seq": last_fault_seq,
            "target_reached": target_reached,
            "post_fault_target_reached": post_fault_target,
            "fault_occurrences_in_target_closure": fault_occurrences_in_closure,
            "all_fault_occurrences_in_target_closure": bool(
                strict and len(fault_occurrences_in_closure) == len(applied)),
            "injection_specific_target_reached": injection_specific_target,
            "injection_specific_target_throw": bool(causal_throw_seqs),
            "target_throw_seen": bool(throws),
            "target_exception_triggered": bool(faults and strict and exact),
            "target_throw_seqs_after_fault": [row["seq"] for row in exact],
            "target_throw_seqs_in_fault_closure": causal_throw_seqs,
            "target_throw_rows_after_fault": exact,
            "target_throw_seqs_on_closure_occurrence": [row["seq"] for row in exact
                                                        if row["occurrenceId"] in closure],
            "target_throw_seqs_after_check": [row["seq"] for row in check_preceded_throws],
            "target_check_outcomes": sorted({row.get("outcome", "") for row in checks}),
            "configured_check_sites": check_sites,
            "observed_check_sites": sorted({row["siteId"] for row in checks}),
            "missing_check_sites_in_trial": sorted(set(check_sites) - {
                row["siteId"] for row in checks}),
            "eligible_doors": eligible,
            "causal_closure_occurrences": sorted(closure),
            "causal_closure_cutoffs": cutoffs,
            "causal_closure_edges": graph.get("closureEdgeIds", []),
            "closure_coverage_sites": graph.get("closureCoverageSiteIds", []),
            "static_may_observed_door_sites": sorted(may_sites),
            "selected_scope_observed_door_sites": sorted({
                door["siteId"] for door in eligible
                if door["tier"] == "selected_scope_observed"}),
            "graph_gaps": graph.get("gaps", {})}


def _trial_verdict(evidence: dict[str, Any], faults: list[dict[str, Any]],
                   prior_throw_count: int | None) -> tuple[str, bool]:
    """Keep an exact post-fault throw distinct from injection-specific evidence."""
    triggered = bool(evidence["target_exception_triggered"])
    specific = bool(evidence["injection_specific_target_reached"])
    throw_specific = bool(evidence.get("injection_specific_target_throw"))
    differential = bool(throw_specific and triggered and prior_throw_count is not None and
                        len(evidence["target_throw_rows_after_fault"]) > prior_throw_count)
    if differential:
        return "candidate", True
    if triggered and not throw_specific:
        return "needs_causal_review", False
    if triggered:
        return ("needs_differential_review" if prior_throw_count is not None
                else "needs_baseline_review"), False
    if specific:
        return "checked", False
    if faults and not evidence["strict_injection"]:
        return "unmatched", False
    if faults and evidence.get("post_fault_target_reached"):
        return "unrelated_target", False
    return ("lost_target" if faults else "healthy_seed"), False


def run_trial(config: dict[str, Any], prepared: Path, trial: Path,
              plan: dict[str, Any], prior_trace: Path | None = None) -> dict[str, Any]:
    """Execute one fresh JVM and write a self-contained, replayable receipt."""
    woven = _verify_prepared(config, prepared)
    door_types = _door_types(_json(prepared / "weave-manifest.json"))
    faults = validate_plan(plan, door_types)
    prior_throw_count = None
    prior_digest = None
    prior_archive_digest = None
    if prior_trace is not None:
        prior_result = prior_trace.parent / "result.json"
        if prior_trace.suffix == ".gz" and prior_result.is_file():
            verify_trial_artifacts(prior_trace.parent, _json(prior_result),
                                   {"window_trace"})
        prior_rows, _ = scan_window_trace(prior_trace,
                                          selected_kinds={"TARGET_THROW"})
        prior_throw_count = sum(
            row.get("kind") == "TARGET_THROW" and
            row.get("siteId") == config["target"]["throw_site_id"] and
            row.get("exceptionClass") == config["target"]["exception_class"] and
            bool(row.get("occurrenceId")) for row in prior_rows)
        prior_digest, _ = _trace_digest(prior_trace)
        prior_archive_digest = _sha256(prior_trace) if prior_trace.suffix == ".gz" else None
    trial.mkdir(parents=True, exist_ok=False)
    native_plan = trial / "fault-plan.json"
    _write_json(native_plan, {"faults": faults})
    scratch_root = Path("/dev/shm") if Path("/dev/shm").is_dir() else None
    scratch = Path(tempfile.mkdtemp(prefix="mallory-gc-trial-", dir=scratch_root))
    raw_trace = scratch / "graphchecker-raw.jsonl"
    trace = scratch / "graphchecker-trace.jsonl"
    workdir = scratch / "workdir"
    template = config["trial_cwd_template"]
    if template is None:
        workdir.mkdir()
    else:
        if _tree_sha256(template) != config["trial_cwd_template_sha256"]:
            raise ValueError("trial cwd template changed after config load")
        shutil.copytree(template, workdir)
        for copied in workdir.rglob("*"):
            copied.chmod(copied.stat().st_mode | 0o200)
        workdir.chmod(workdir.stat().st_mode | 0o200)
    env = os.environ.copy()
    env["MALLORY_GC_TRACE"] = str(raw_trace)
    env["MALLORY_GC_FAULT_PLAN"] = str(native_plan)
    # A legacy agent or Probe plan would provide a second, unrelated fault
    # identity. Explicitly remove these inherited settings from this JVM.
    for name in ("MALLORY_PLAN_FILE", "MALLORY_EVENT_FILE", "MALLORY_SITE_FILE"):
        env.pop(name, None)
    if "-javaagent:" in env.get("JAVA_TOOL_OPTIONS", ""):
        raise ValueError("JAVA_TOOL_OPTIONS contains a legacy Java agent")
    cp = os.pathsep.join(map(str, [*woven, *_runtime_classpath(config)]))
    runner = config["runner"]
    argv = [config["java"], *(_trial_arg(arg, trial, workdir)
                               for arg in runner["jvm_args"]), "-cp", cp,
            runner["main_class"], *(_trial_arg(arg, trial, workdir)
                                    for arg in runner["args"])]
    started = time.time()
    timed_out = False
    with (trial / "stdout.log").open("wb") as stdout, (
            trial / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=workdir, env=env,
                                   stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        _write_json(trial / "process.json", {
            "pid": process.pid, "start_ticks": _process_start_ticks(process.pid),
            "runner_class": runner["main_class"], "junit_class": config["junit"]["class"],
            "scratch_dir": str(scratch), "trial_cwd": str(workdir),
            "trial_cwd_template_sha256": config["trial_cwd_template_sha256"]})
        try:
            return_code = process.wait(timeout=config["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                return_code = process.wait()
    elapsed = round(time.time() - started, 3)
    result: dict[str, Any] = {
        "schema_version": SCHEMA, "case_id": config["case_id"],
        "backend": "graphchecker_native", "command": argv,
        "target_site_rows": config["target_site_rows"],
        "return_code": return_code, "timed_out": timed_out,
        "elapsed_seconds": elapsed, "junit_passed": return_code == 0 and not timed_out,
        "fault_plan": faults, "fault_plan_sha256": _sha256(native_plan),
        "raw_trace_sha256": None,
        "prior_trace_sha256": prior_digest,
        "prior_trace_archive_sha256": prior_archive_digest,
        "prior_seed_target_throw_count": prior_throw_count,
        "static_scope_map_sha256": _sha256(config["static_scope_map"]),
        "weave_receipt_sha256": _sha256(prepared / "weave-receipt.json"),
        "trial_cwd_template_sha256": config["trial_cwd_template_sha256"],
        "target_exception_triggered": False,
        "target_exception_candidate": False}
    try:
        rows, window_count = scan_window_trace(raw_trace, trace)
        check_sites = _configured_check_sites(config["target"])
        anchor = check_sites if len(check_sites) > 1 else (
            check_sites[0] if check_sites else config["target"]["throw_site_id"])
        graph = analyze_trial(scratch, anchor, prior_trace, config["graph_jar"],
                              config["static_scope_map"])
        evidence = summarize_evidence(rows, graph, config["target"], faults,
                                      door_types)
        triggered = evidence["target_exception_triggered"]
        status, candidate = _trial_verdict(evidence, faults, prior_throw_count)
        result.update({"status": status,
                       "graphchecker_feedback": graph, "evidence": evidence,
                       "window_rows": window_count,
                       "trace_sha256": _sha256(trace),
                       "target_exception_triggered": triggered,
                       "target_exception_candidate": candidate,
                       "graph_sha256": _sha256(scratch / "graphchecker-graph.jsonl"),
                       "feedback_sha256": _sha256(scratch / "graphchecker-feedback.json")})
        shutil.copyfile(scratch / "graphchecker-feedback.json",
                        trial / "graphchecker-feedback.json")
    except (ValueError, FileNotFoundError, subprocess.SubprocessError, OSError,
            json.JSONDecodeError) as failure:
        result.update({"status": "invalid_graphchecker_trace",
                       "analysis_error": str(failure)})
    artifacts = {}
    for name, filename in (("raw_trace", "graphchecker-raw.jsonl"),
                           ("window_trace", "graphchecker-trace.jsonl"),
                           ("graph", "graphchecker-graph.jsonl")):
        source = scratch / filename
        if source.is_file():
            artifacts[name] = _archive_jsonl(source, trial)
    result["artifacts"] = artifacts
    result["raw_trace_sha256"] = (artifacts.get("raw_trace") or {}).get("content_sha256")
    if result["target_exception_triggered"]:
        result["workdir_artifact"] = _archive_workdir(workdir, trial)
    shutil.rmtree(scratch)
    _write_json(trial / "result.json", result)
    verify_trial_artifacts(trial, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("prepare", "trial"):
        command = sub.add_parser(mode)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        if mode == "trial":
            command.add_argument("--prepared", type=Path, required=True)
            command.add_argument("--plan", type=Path, required=True)
            command.add_argument("--prior-trace", type=Path)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.mode == "prepare":
        prepare(config, args.out.resolve())
    else:
        result = run_trial(config, args.prepared.resolve(), args.out.resolve(),
                           _json(args.plan), args.prior_trace)
        print(json.dumps({"status": result["status"],
                          "target_exception_candidate": result["target_exception_candidate"],
                          "result": str((args.out / "result.json").resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
