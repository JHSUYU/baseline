"""Opt-in delta feedback from original GraphChecker native session summaries.

The Java extractor uses the source-built original Corpus/ClosurePlanner for
membership. This module compares only recorded facts; it never converts a
static candidate or a missing hook into an observed causal edge.
"""

from __future__ import annotations

import hashlib
import json
import fcntl
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "static_scope_port" / "original_engine"
JAVA_CLASS = "edu.uva.liftlab.mallory.nativefeedback.NativeFeedbackMain"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _session_digest(iteration: Path) -> str:
    sessions = list((iteration / "sessions").glob("*/manifest.json"))
    if len(sessions) != 1:
        raise ValueError("one trial must contain exactly one landed native session")
    directory = sessions[0].parent
    digest = hashlib.sha256()
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _engine_jar(engine_jar: Path | None = None) -> Path:
    jar = (engine_jar or ENGINE / "target" /
           "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar").resolve()
    if not jar.is_file():
        raise FileNotFoundError("build Mallory/static_scope_port/original_engine first")
    return jar


def _classpath(engine_jar: Path | None = None) -> str:
    jar = _engine_jar(engine_jar)
    dependencies = ENGINE / "target" / "native-original-dependencies.txt"
    if not dependencies.is_file():
        raise FileNotFoundError("build Mallory/static_scope_port/original_engine first")
    return f"{jar}:{dependencies.read_text(encoding='utf-8').strip()}"


def build(*, engine_jar: Path | None = None, force: bool = False) -> Path:
    """Compile only this bridge; pinned original sources stay in their module."""
    source = HERE / "NativeFeedbackMain.java"
    digest = _sha256(_engine_jar(engine_jar))
    output = HERE / "target" / f"classes-{digest[:16]}"
    clazz = output / "edu/uva/liftlab/mallory/nativefeedback/NativeFeedbackMain.class"
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / f".build-{digest[:16]}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if force or not clazz.is_file() or clazz.stat().st_mtime < source.stat().st_mtime:
            output.mkdir(parents=True, exist_ok=True)
            subprocess.run(["javac", "-cp", _classpath(engine_jar), "-d", str(output),
                            str(source)], check=True, timeout=120,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output


def summarize(iteration: Path, target_site: str, output: Path, *,
              exact_occurrence_id: str | None = None,
              static_scope_map: Path | None = None,
              max_tasks: int = 256,
              engine_jar: Path | None = None) -> dict[str, Any]:
    """Read one trial session, bind one exact target, and extract native plan.

    ``iteration`` must hold exactly one landed native session. The occurrence
    ID is exact within that run. A fresh distributed run may assign a new ID;
    compare stable target families across runs, or use ``summarize_target_set``
    when the site can occur more than once in a run.
    """
    if not target_site:
        raise ValueError("target_site must be a GraphChecker anchorSiteId")
    if max_tasks <= 0:
        raise ValueError("max_tasks must be positive")
    if static_scope_map is not None and not static_scope_map.is_file():
        raise FileNotFoundError(static_scope_map)
    selected_jar = _engine_jar(engine_jar)
    jar_sha = _sha256(selected_jar)
    session_sha = _session_digest(iteration)
    scope_sha = _sha256(static_scope_map) if static_scope_map else ""
    bridge_sha = _sha256(HERE / "NativeFeedbackMain.java")
    classes = build(engine_jar=selected_jar)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-summary-",
                                     dir=output.parent) as scratch:
        raw_output = Path(scratch) / "summary.json"
        command = ["java", "-Xmx4g",
                   f"-Dmallory.native.expectedEngineJar={selected_jar}",
                   "-cp", f"{classes}:{_classpath(selected_jar)}", JAVA_CLASS,
                   str(iteration), str(static_scope_map) if static_scope_map else "-",
                   target_site, exact_occurrence_id or "-", str(max_tasks),
                   str(raw_output)]
        subprocess.run(command, check=True, timeout=300,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        value = json.loads(raw_output.read_text(encoding="utf-8"))
    if _sha256(selected_jar) != jar_sha:
        raise ValueError("GraphChecker engine JAR changed during native analysis")
    if _session_digest(iteration) != session_sha:
        raise ValueError("native session changed during analysis")
    if static_scope_map and _sha256(static_scope_map) != scope_sha:
        raise ValueError("static scope map changed during native analysis")
    if value.get("schemaVersion") != 1 or value.get("targetSiteId") != target_site:
        raise ValueError("native session extractor returned a different target")
    if exact_occurrence_id is not None and (
            value.get("targetOccurrenceId") != exact_occurrence_id):
        raise ValueError("native session extractor changed target occurrence")
    value["engineJarSha256"] = jar_sha
    value["nativeSessionSha256"] = session_sha
    value["staticScopeMapSha256"] = scope_sha
    value["bridgeSourceSha256"] = bridge_sha
    value["maxTasks"] = max_tasks
    _write_atomic_json(output, value)
    return value


def _write_atomic_json(output: Path, value: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=output.parent,
                                     prefix=".native-feedback-", suffix=".json",
                                     encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def list_native_targets(iteration: Path, target_site: str, *,
                        engine_jar: Path | None = None) -> list[dict[str, Any]]:
    """List exact target occurrences through original SessionReader."""
    selected_jar = _engine_jar(engine_jar)
    jar_sha = _sha256(selected_jar)
    session_sha = _session_digest(iteration)
    classes = build(engine_jar=selected_jar)
    with tempfile.TemporaryDirectory(prefix="mallory-native-targets-") as scratch:
        output = Path(scratch) / "targets.json"
        command = ["java", "-Xmx4g",
                   f"-Dmallory.native.expectedEngineJar={selected_jar}",
                   "-cp", f"{classes}:{_classpath(selected_jar)}", JAVA_CLASS,
                   "--list-targets", str(iteration), target_site, str(output)]
        subprocess.run(command, check=True, timeout=120,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        value = json.loads(output.read_text(encoding="utf-8"))
    if _sha256(selected_jar) != jar_sha or _session_digest(iteration) != session_sha:
        raise ValueError("native engine or session changed during target listing")
    if value.get("schemaVersion") != 1 or value.get("targetSiteId") != target_site:
        raise ValueError("native target listing does not match requested site")
    targets = value.get("targets")
    if not isinstance(targets, list) or not all(
            isinstance(item, dict) and isinstance(item.get("occurrenceId"), str)
            and isinstance(item.get("targetFamily"), str) for item in targets):
        raise ValueError("native target listing is invalid")
    return targets


def summarize_target_set(iteration: Path, target_site: str, output: Path, *,
                         static_scope_map: Path,
                         actor_names: set[str] | None = None,
                         max_tasks: int = 256,
                         engine_jar: Path | None = None) -> dict[str, Any]:
    """Plan every matching native target separately, then union only feedback.

    Distinct target events retain distinct exact addresses and closures in
    ``perTargetOccurrences``. The union is only a scheduling score; it is not
    an assertion that one occurrence caused another.
    """
    if not static_scope_map.is_file():
        raise FileNotFoundError(static_scope_map)
    before = _session_digest(iteration)
    listed = list_native_targets(iteration, target_site, engine_jar=engine_jar)
    selected = [item for item in listed if actor_names is None
                or item["nodeName"] in actor_names]
    if not selected:
        raise ValueError("no native target occurrence matches site/actor selection")
    per_target: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mallory-native-target-set-") as scratch:
        for index, item in enumerate(selected):
            one = summarize(iteration, target_site,
                            Path(scratch) / f"target-{index}.json",
                            exact_occurrence_id=item["occurrenceId"],
                            static_scope_map=static_scope_map,
                            max_tasks=max_tasks, engine_jar=engine_jar)
            if one["targetFamily"] != item["targetFamily"]:
                raise ValueError("native target family changed during extraction")
            per_target.append(one)
    if _session_digest(iteration) != before:
        raise ValueError("native target set changed during analysis")
    for key in ("engineJarSha256", "staticScopeMapSha256", "bridgeSourceSha256",
                "maxTasks", "method", "targetSiteId", "nativeSessionSha256"):
        if len({json.dumps(item[key], sort_keys=True) for item in per_target}) != 1:
            raise ValueError(f"native target set has mixed {key}")
    members: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    coverage: set[str] = set()
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    truncated: set[str] = set()
    for one in per_target:
        for member in one["closureMembers"]:
            members[member["occurrenceId"]] = member
        for edge in one["observedEdgesWithinClosure"]:
            identity = json.dumps(edge, sort_keys=True, separators=(",", ":"))
            edges[identity] = edge
        coverage.update(one["branchCoverage"])
        rows.extend(one["targetRows"])
        gaps.extend(one["gaps"])
        truncated.update(one["truncated"])
    first = per_target[0]
    value: dict[str, Any] = {
        "schemaVersion": 1,
        "method": first["method"],
        "targetSetMode": True,
        "targetSiteId": target_site,
        "targetFamilies": sorted({one["targetFamily"] for one in per_target}),
        "targetRegionIds": sorted({one["targetRegionId"] for one in per_target}),
        "targetOccurrenceIds": sorted(one["targetOccurrenceId"] for one in per_target),
        "targetRows": rows,
        "perTargetOccurrences": per_target,
        "closureMembers": sorted(members.values(), key=lambda row: row["occurrenceId"]),
        "observedEdgesWithinClosure": list(edges.values()),
        "branchCoverage": sorted(coverage),
        "gaps": gaps,
        "truncated": sorted(truncated),
        "engineJarSha256": first["engineJarSha256"],
        "staticScopeMapSha256": first["staticScopeMapSha256"],
        "bridgeSourceSha256": first["bridgeSourceSha256"],
        "nativeSessionSha256": first["nativeSessionSha256"],
        "maxTasks": max_tasks,
    }
    _write_atomic_json(output, value)
    return value


def _families(summary: dict[str, Any], field: str, family: str) -> set[str]:
    rows = summary.get(field)
    if not isinstance(rows, list):
        raise ValueError(f"native summary lacks {field}")
    found: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(family), str):
            raise ValueError(f"native summary has invalid {field}")
        found.add(row[family])
    return found


def _observed_edges(summary: dict[str, Any]) -> set[str]:
    members = summary.get("closureMembers")
    if not isinstance(members, list):
        raise ValueError("native summary lacks closureMembers")
    closure = {row.get("occurrenceId") for row in members
               if isinstance(row, dict)}
    rows = summary.get("observedEdgesWithinClosure")
    if not isinstance(rows, list):
        raise ValueError("native summary lacks observedEdgesWithinClosure")
    families: set[str] = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("type") not in
                {"WIRE", "STATE", "MESSAGE_START"} or
                row.get("producerOccurrenceId") not in closure or
                row.get("consumerOccurrenceId") not in closure or
                not isinstance(row.get("family"), str) or not row["family"] or
                not isinstance(row.get("evidence"), dict)):
            raise ValueError("native summary has invalid observedEdgesWithinClosure")
        families.add(row["family"])
    return families


def delta(healthy: dict[str, Any], trial: dict[str, Any]) -> dict[str, Any]:
    """Compute target-family novelty while preserving each run's exact anchors.

    Every target occurrence must appear in that run's target rows and native
    closure. Cross-run exact IDs may differ; a changed actor/region family or
    a trial without the target is rejected.
    """
    for key in ("schemaVersion", "method", "targetSiteId", "targetSetMode",
                "engineJarSha256", "staticScopeMapSha256", "bridgeSourceSha256",
                "maxTasks"):
        if healthy.get(key) != trial.get(key):
            raise ValueError(f"incompatible native feedback: {key}")
    target_set = healthy.get("targetSetMode") is True
    if target_set:
        if not set(healthy.get("targetRegionIds", [])) & set(
                trial.get("targetRegionIds", [])):
            raise ValueError("fault trial lost every healthy target region")
        healthy_anchors = healthy.get("targetOccurrenceIds")
        trial_anchors = trial.get("targetOccurrenceIds")
    else:
        if (not isinstance(healthy.get("targetFamily"), str)
                or not healthy["targetFamily"]
                or healthy["targetFamily"] != trial.get("targetFamily")):
            raise ValueError("single target actor/region family changed")
        healthy_anchors = [healthy.get("targetOccurrenceId")]
        trial_anchors = [trial.get("targetOccurrenceId")]
    if not isinstance(healthy_anchors, list) or not isinstance(trial_anchors, list):
        raise ValueError("native target anchor list is invalid")
    if not healthy_anchors or not trial_anchors or not all(
            isinstance(anchor, str) and anchor for anchor in
               healthy_anchors + trial_anchors):
        raise ValueError("native target has no exact occurrence identity")
    if target_set:
        for label, summary, anchors in (("healthy", healthy, healthy_anchors),
                                        ("trial", trial, trial_anchors)):
            separate = summary.get("perTargetOccurrences")
            if (not isinstance(separate, list) or len(separate) != len(anchors)
                    or len(set(anchors)) != len(anchors)
                    or not all(isinstance(item, dict) for item in separate)
                    or {item.get("targetOccurrenceId") for item in separate}
                    != set(anchors)
                    or not all(item.get("targetSiteId") == summary["targetSiteId"]
                               and item.get("targetRegionId") in summary["targetRegionIds"]
                               and item.get("targetFamily") in summary["targetFamilies"]
                               for item in separate)):
                raise ValueError(f"{label} conflates distinct target occurrences")
            for item in separate:
                anchor = item["targetOccurrenceId"]
                if not any(row.get("occurrenceId") == anchor
                           for row in item.get("targetRows", [])
                           if isinstance(row, dict)) or not any(
                        row.get("occurrenceId") == anchor
                        for row in item.get("closureMembers", [])
                        if isinstance(row, dict)):
                    raise ValueError(f"{label} lacks an exact per-target plan")
    for label, summary in (("healthy", healthy), ("trial", trial)):
        anchors = healthy_anchors if label == "healthy" else trial_anchors
        targets = summary.get("targetRows")
        if not isinstance(targets, list) or not all(any(
                isinstance(row, dict) and row.get("occurrenceId") == anchor
                for row in targets) for anchor in anchors):
            raise ValueError(f"{label} lacks exact target row")
        members = summary.get("closureMembers")
        if not isinstance(members, list) or not all(any(
                isinstance(row, dict) and row.get("occurrenceId") == anchor
                for row in members) for anchor in anchors):
            raise ValueError(f"{label} native closure omitted exact target")
    nodes = _families(trial, "closureMembers", "family")
    baseline_nodes = _families(healthy, "closureMembers", "family")
    edges = _observed_edges(trial)
    baseline_edges = _observed_edges(healthy)
    coverage = trial.get("branchCoverage")
    baseline_coverage = healthy.get("branchCoverage")
    if not isinstance(coverage, list) or not isinstance(baseline_coverage, list):
        raise ValueError("native branch coverage is absent")
    if not all(isinstance(item, str) for item in coverage + baseline_coverage):
        raise ValueError("native branch coverage has non-string keys")
    new_nodes = sorted(nodes - baseline_nodes)
    new_edges = sorted(edges - baseline_edges)
    new_coverage = sorted(set(coverage) - set(baseline_coverage))
    return {
        "schemaVersion": 1,
        "method": trial["method"],
        "targetSiteId": trial["targetSiteId"],
        "targetSetMode": target_set,
        "healthyTargetOccurrenceIds": healthy_anchors,
        "trialTargetOccurrenceIds": trial_anchors,
        "newClosureNodes": len(new_nodes),
        "newObservedClosureEdges": len(new_edges),
        "newClosureBranchOutcomes": len(new_coverage),
        "newClosureNodeFamilies": new_nodes,
        "newObservedClosureEdgeFamilies": new_edges,
        "newClosureBranchOutcomeIds": new_coverage,
        "trialPlannerGaps": len(trial.get("gaps", [])),
        "trialPlannerTruncated": len(trial.get("truncated", [])),
        "evidence": "original SessionReader + Corpus/ClosurePlanner; "
                    "observed pairs only",
    }
