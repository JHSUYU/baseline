"""Join one GraphChecker trace and keep static may-scope separate from edges.

This module consumes MessageDoors rows only. It never treats legacy Mallory
events or static may-relevance as observed causal edges or target evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def runtime_jar() -> Path:
    return (Path(__file__).resolve().parents[1] / "graphchecker-runtime" / "target" /
            "mallory-graphchecker-runtime-1.0-SNAPSHOT-all.jar")


SUMMARY_VERSION = 1
SUMMARY_FIELDS = ("summaryVersion", "targetSites", "nodeFamilies",
                  "edgeFamilies", "coverageSites")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summary_body(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in SUMMARY_FIELDS}


def _summary_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_summary_body(value), sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _valid_summary(value: Any, sites: list[str], trace_sha: str,
                   jar_sha: str) -> bool:
    if not isinstance(value, dict) or value.get("summaryVersion") != SUMMARY_VERSION:
        return False
    if value.get("targetSites") != sites or value.get("priorTraceSha256") != trace_sha or (
            value.get("graphJarSha256") != jar_sha):
        return False
    for key in ("nodeFamilies", "edgeFamilies", "coverageSites"):
        items = value.get(key)
        if (not isinstance(items, list) or any(not isinstance(item, str) or not item
                                                for item in items) or
                len(items) != len(set(items))):
            return False
    return value.get("summarySha256") == _summary_digest(value)


def _healthy_summary(prior_trace: Path, sites: list[str], jar: Path) -> Path:
    """Cache only exact prior-closure novelty facts; retain the original gzip."""
    trace_sha = _sha256(prior_trace)
    jar_sha = _sha256(jar)
    sites_sha = hashlib.sha256(json.dumps(sites, separators=(",", ":"))
                               .encode("utf-8")).hexdigest()
    cached = prior_trace.with_name(prior_trace.name + "." + sites_sha[:16]
                                   + ".summary.json")
    if cached.is_file():
        try:
            value = json.loads(cached.read_text(encoding="utf-8"))
            if _valid_summary(value, sites, trace_sha, jar_sha):
                return cached
        except (ValueError, KeyError, TypeError):
            pass
    target_arg = json.dumps(sites) if len(sites) > 1 else sites[0]
    with tempfile.NamedTemporaryFile(mode="w", prefix=".healthy-summary-",
                                     suffix=".summary.json", dir=prior_trace.parent,
                                     delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        subprocess.run(["java", "-Xmx6g", "-jar", str(jar), "--healthy-summary",
                        str(prior_trace), str(temporary_path), target_arg],
                       check=True, timeout=300, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)
        if _sha256(prior_trace) != trace_sha or _sha256(jar) != jar_sha:
            raise ValueError("healthy trace or graph jar changed during summary creation")
        value = json.loads(temporary_path.read_text(encoding="utf-8"))
        if (value.get("summaryVersion") != SUMMARY_VERSION or
                value.get("targetSites") != sites or
                any(key not in value for key in SUMMARY_FIELDS)):
            raise ValueError("graph builder emitted a mismatched healthy summary")
        value.update({"priorTraceSha256": trace_sha, "graphJarSha256": jar_sha})
        value["summarySha256"] = _summary_digest(value)
        if not _valid_summary(value, sites, trace_sha, jar_sha):
            raise ValueError("graph builder emitted an invalid healthy summary")
        temporary_path.write_text(json.dumps(value, sort_keys=True) + "\n",
                                  encoding="utf-8")
        temporary_path.replace(cached)
        return cached
    finally:
        temporary_path.unlink(missing_ok=True)


def analyze_trial(trial: Path, target_site: str | list[str], prior_trace: Path | None = None,
                  jar: Path | None = None,
                  static_scope_map: Path | None = None) -> dict[str, Any]:
    selected_jar = (jar or runtime_jar()).resolve()
    if not selected_jar.is_file():
        raise FileNotFoundError(f"build Mallory/graphchecker-runtime first: {selected_jar}")
    trace = trial / "graphchecker-trace.jsonl"
    graph = trial / "graphchecker-graph.jsonl"
    feedback = trial / "graphchecker-feedback.json"
    if prior_trace is not None and not prior_trace.is_file():
        raise FileNotFoundError(f"prior GraphChecker trace missing: {prior_trace}")
    if static_scope_map is not None and not static_scope_map.is_file():
        raise FileNotFoundError(f"GraphChecker static scope map missing: {static_scope_map}")
    sites = target_site if isinstance(target_site, list) else [target_site]
    if not sites:
        raise ValueError("GraphChecker analysis needs a target site")
    prior_input = prior_trace
    if prior_trace is not None and prior_trace.suffix == ".gz":
        cached = _healthy_summary(prior_trace, sites, selected_jar)
        prior_input = trial / "prior.summary.json"
        shutil.copyfile(cached, prior_input)
        if _sha256(cached) != _sha256(prior_input):
            raise ValueError("healthy summary changed while copying into trial")
    target_arg = json.dumps(sites) if len(sites) > 1 else sites[0]
    command = ["java", "-Xmx6g", "-jar", str(selected_jar), str(trace), str(graph),
               str(feedback), target_arg]
    if prior_input is not None or static_scope_map is not None:
        command.append(str(prior_input) if prior_input is not None else "-")
    if static_scope_map is not None:
        command.append(str(static_scope_map))
    subprocess.run(command, check=True, timeout=300, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE)
    value = json.loads(feedback.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError(f"invalid GraphChecker trial feedback: {feedback}")
    if value.get("targetSite") != sites[0]:
        raise ValueError(f"GraphChecker feedback target differs from {target_site}: {feedback}")
    if len(sites) > 1 and value.get("configuredTargetSites") != sites:
        raise ValueError(f"GraphChecker feedback omitted target guards: {feedback}")
    return value
