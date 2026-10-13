"""Build and load the coarse Soot selection used by the CrashFuzz scheduler."""

from __future__ import annotations

import hashlib
import json
import os
import fcntl
import subprocess
import tempfile
from pathlib import Path
from typing import Any


TOOL = Path(__file__).resolve().parents[1] / "static-selection"
MAIN = "edu.uva.liftlab.crashfuzz.staticselection.CoarseSelector"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def _artifact_identity(path: str) -> dict[str, Any]:
    source = Path(path).resolve(strict=True)
    if source.is_dir():
        files = sorted((item for item in source.rglob("*.class") if item.is_file()),
                       key=lambda item: str(item.relative_to(source)))
        return {"path": str(source), "classes": [
            [str(item.relative_to(source)), item.stat().st_size, item.stat().st_mtime_ns]
            for item in files]}
    stat = source.stat()
    return {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _build_tool() -> tuple[Path, str]:
    classes = TOOL / "target" / "classes"
    dependencies = TOOL / "target" / "runtime-classpath.txt"
    source = TOOL / "src" / "main" / "java"
    TOOL.joinpath("target").mkdir(parents=True, exist_ok=True)
    with TOOL.joinpath("target", ".build.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        compiled = classes / "edu/uva/liftlab/crashfuzz/staticselection/CoarseSelector.class"
        stale = (not dependencies.is_file() or not compiled.is_file() or
                 any(item.stat().st_mtime_ns > compiled.stat().st_mtime_ns
                     for item in source.rglob("*.java")))
        if stale:
            subprocess.run(["mvn", "-q", "test", "package", "dependency:build-classpath",
                            "-Dmdep.outputFile=target/runtime-classpath.txt"],
                           cwd=TOOL, check=True)
    return classes, dependencies.read_text().strip()


def _validate_selection(result: dict[str, Any], target_method: str) -> None:
    if (result.get("analysis_kind") != "crashfuzz_coarse_soot_selection" or
            result.get("schema_version") != 1 or
            result.get("target_method") != target_method):
        raise ValueError("Soot selection does not match the exact target method")
    for key in ("coverage_methods", "io_methods"):
        methods = result.get(key)
        if (not isinstance(methods, list) or
                any(not isinstance(method, str) or not method.startswith("<")
                    for method in methods)):
            raise ValueError(f"invalid Soot selection {key}")
    if target_method not in result["coverage_methods"]:
        raise ValueError("Soot selection omits the target method")
    if not set(result["io_methods"]).issubset(result["coverage_methods"]):
        raise ValueError("Soot I/O methods must be inside the coverage range")
    io_calls = result.get("io_calls")
    if (not isinstance(io_calls, list) or
            any(not isinstance(row, dict) or
                row.get("method") not in result["io_methods"] or
                not isinstance(row.get("site_id"), str) or
                not row["site_id"].startswith(row["method"] + "#u")
                for row in io_calls)):
        raise ValueError("Soot selection has invalid I/O callsites")
    throw_sites = result.get("target_throw_sites")
    if throw_sites is not None:
        branch_ids = {row.get("site_id") for row in result.get("branches", [])
                      if isinstance(row, dict)}
        if (not isinstance(throw_sites, list) or
                any(not isinstance(row, dict) or
                    row.get("method") != target_method or
                    not isinstance(row.get("soot_site_id"), str) or
                    not row["soot_site_id"].startswith(target_method + "#u") or
                    not isinstance(row.get("line"), int) or
                    isinstance(row.get("line"), bool) or
                    row["line"] < 1 or
                    not isinstance(row.get("thrown_type"), str) or
                    not row["thrown_type"] or
                    not isinstance(row.get("controlled_by"), list) or
                    any(not isinstance(branch, str)
                        for branch in row["controlled_by"]) or
                    not set(row["controlled_by"]).issubset(branch_ids)
                    for row in throw_sites)):
            raise ValueError("Soot selection has invalid target throw sites")


def prepare(config: dict[str, Any], case_dir: Path) -> dict[str, Any] | None:
    """Return a reproducible selection, generating it when analysis is configured.

    The input and output live with the campaign, so a resumed run can use its
    exact prior selection. A changed analysis or compiled artifact changes the
    input digest and requires a new campaign checkpoint.
    """
    spec = config.get("static_selection")
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError("static_selection must be an object")
    target = config["target"]["method"]
    if "artifact" in spec:
        if "analysis" in spec:
            raise ValueError("static_selection accepts artifact or analysis, not both")
        artifact = Path(spec["artifact"]).resolve(strict=True)
        result = json.loads(artifact.read_text())
        _validate_selection(result, target)
        result["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        result["artifact_path"] = str(artifact)
        return result
    analysis = spec.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("static_selection needs artifact or analysis object")
    if ("post_call_rpc_enabled" in analysis and
            not isinstance(analysis["post_call_rpc_enabled"], bool)):
        raise ValueError("static_selection.analysis.post_call_rpc_enabled must be boolean")
    process_dirs = analysis.get("process_dirs")
    if not isinstance(process_dirs, list) or not process_dirs:
        raise ValueError("static_selection.analysis.process_dirs is required")
    classpath = analysis.get("classpath", [])
    if not isinstance(classpath, list):
        raise ValueError("static_selection.analysis.classpath must be a list")
    for field in ("max_caller_depth", "max_callee_depth", "max_jump_depth",
                  "max_methods"):
        if field in analysis and (not isinstance(analysis[field], int) or
                                  isinstance(analysis[field], bool)):
            raise ValueError(f"static_selection.analysis.{field} must be an integer")
    mappings = analysis.get("rpc_mapping_files", [])
    if not isinstance(mappings, list) or any(not isinstance(path, str)
                                              for path in mappings):
        raise ValueError("static_selection.analysis.rpc_mapping_files must be a list")
    normalized = {**analysis,
                  "process_dirs": [str(Path(value).resolve(strict=True))
                                   for value in process_dirs],
                  "classpath": [str(Path(value).resolve(strict=True))
                                for value in classpath],
                  "rpc_mapping_files": [str(Path(value).resolve(strict=True))
                                        for value in mappings]}
    input_data = {"schema_version": 1, "target_method": target,
                  "analysis": normalized}
    source_identity = [_artifact_identity(value) for value in
                       normalized["process_dirs"] + normalized["classpath"] +
                       normalized["rpc_mapping_files"]]
    selector_source = _artifact_identity(str(TOOL / "src" / "main" / "java" /
                                             "edu" / "uva" / "liftlab" / "crashfuzz" /
                                             "staticselection" / "CoarseSelector.java"))
    input_digest = _digest({"input": input_data, "artifacts": source_identity,
                            "selector_source": selector_source})
    artifact = case_dir / "soot-selection.json"
    if artifact.is_file():
        cached = json.loads(artifact.read_text())
        if cached.get("input_digest") == input_digest:
            _validate_selection(cached, target)
            if "target_throw_sites" not in cached:
                raise ValueError("current Soot selection omits target throw sites")
            if len(cached["coverage_methods"]) > normalized.get("max_methods", 400):
                raise ValueError("cached Soot selection exceeds its method budget")
            cached["artifact_path"] = str(artifact)
            return cached
    classes, dependencies = _build_tool()
    case_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="soot-selection-", dir=case_dir) as temporary:
        input_path = Path(temporary) / "input.json"
        output_path = Path(temporary) / "output.json"
        input_path.write_text(json.dumps(input_data, indent=2) + "\n")
        subprocess.run(["java", "-cp", os.pathsep.join([str(classes), dependencies]),
                        MAIN, str(input_path), str(output_path)], check=True)
        result = json.loads(output_path.read_text())
    _validate_selection(result, target)
    if "target_throw_sites" not in result:
        raise ValueError("generated Soot selection omits target throw sites")
    if normalized.get("post_call_rpc_enabled", False):
        result["post_call_rpc_enabled"] = True
    if len(result["coverage_methods"]) > normalized.get("max_methods", 400):
        raise ValueError("Soot selection exceeds its method budget")
    result["input_digest"] = input_digest
    result["source_artifacts"] = source_identity
    result["artifact_path"] = str(artifact)
    temporary_artifact = artifact.with_name(artifact.name + f".tmp.{os.getpid()}")
    temporary_artifact.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_artifact, artifact)
    return result
