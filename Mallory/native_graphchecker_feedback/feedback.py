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


class NoNativeTargetError(ValueError):
    """A complete native trial has no target at the requested site and actors."""

    def __init__(self, message: str, *, site_target_rows_seen: bool = False) -> None:
        super().__init__(message)
        self.site_target_rows_seen = site_target_rows_seen


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


def _scope_digest(scope: Path) -> str:
    """Pin the map and the neighboring skeleton GraphChecker actually reads."""
    digest = hashlib.sha256()
    digest.update(scope.name.encode("utf-8") + b"\0")
    digest.update(bytes.fromhex(_sha256(scope)))
    for name in ("region_skeletons.jsonl", "region_skeletons.jsonl.gz"):
        sidecar = scope.parent / name
        if sidecar.is_file():
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(bytes.fromhex(_sha256(sidecar)))
            break
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
              target_check_receipts: Path | None = None,
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
    if target_check_receipts is not None and not target_check_receipts.is_file():
        raise FileNotFoundError(target_check_receipts)
    selected_jar = _engine_jar(engine_jar)
    jar_sha = _sha256(selected_jar)
    session_sha = _session_digest(iteration)
    scope_sha = _sha256(static_scope_map) if static_scope_map else ""
    bundle_sha = _scope_digest(static_scope_map) if static_scope_map else ""
    bridge_sha = _sha256(HERE / "NativeFeedbackMain.java")
    receipts_sha = (_sha256(target_check_receipts)
                    if target_check_receipts is not None else "")
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
                   str(raw_output),
                   str(target_check_receipts) if target_check_receipts else "-"]
        subprocess.run(command, check=True, timeout=300,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        value = json.loads(raw_output.read_text(encoding="utf-8"))
    if _sha256(selected_jar) != jar_sha:
        raise ValueError("GraphChecker engine JAR changed during native analysis")
    if _session_digest(iteration) != session_sha:
        raise ValueError("native session changed during analysis")
    if static_scope_map and _scope_digest(static_scope_map) != bundle_sha:
        raise ValueError("static scope map changed during native analysis")
    if target_check_receipts and _sha256(target_check_receipts) != receipts_sha:
        raise ValueError("target check receipts changed during native analysis")
    if value.get("schemaVersion") != 1 or value.get("targetSiteId") != target_site:
        raise ValueError("native session extractor returned a different target")
    if exact_occurrence_id is not None and (
            value.get("targetOccurrenceId") != exact_occurrence_id):
        raise ValueError("native session extractor changed target occurrence")
    value["engineJarSha256"] = jar_sha
    value["nativeSessionSha256"] = session_sha
    value["staticScopeMapSha256"] = scope_sha
    value["staticScopeBundleSha256"] = bundle_sha
    value["bridgeSourceSha256"] = bridge_sha
    value["targetCheckReceiptsSha256"] = receipts_sha
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
                         target_check_receipts: Path | None = None,
                         max_tasks: int = 256,
                         engine_jar: Path | None = None) -> dict[str, Any]:
    """Plan every matching native target separately, then union only feedback.

    Distinct target events retain distinct exact addresses and closures in
    ``perTargetOccurrences``. The union is only a scheduling score; it is not
    an assertion that one occurrence caused another.
    """
    if not target_site:
        raise ValueError("target_site must be a GraphChecker anchorSiteId")
    if max_tasks <= 0:
        raise ValueError("max_tasks must be positive")
    if not static_scope_map.is_file():
        raise FileNotFoundError(static_scope_map)
    if target_check_receipts is not None and not target_check_receipts.is_file():
        raise FileNotFoundError(target_check_receipts)
    if actor_names is not None and (not isinstance(actor_names, set) or
                                    not all(isinstance(name, str) and name
                                            for name in actor_names)):
        raise ValueError("actor_names must contain nonempty node names")
    selected_jar = _engine_jar(engine_jar)
    jar_sha = _sha256(selected_jar)
    session_sha = _session_digest(iteration)
    scope_sha = _sha256(static_scope_map)
    bundle_sha = _scope_digest(static_scope_map)
    bridge_sha = _sha256(HERE / "NativeFeedbackMain.java")
    receipts_sha = (_sha256(target_check_receipts)
                    if target_check_receipts is not None else "")
    classes = build(engine_jar=selected_jar)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-target-set-",
                                     dir=output.parent) as scratch:
        raw_output = Path(scratch) / "summary.json"
        actors_path = Path(scratch) / "actors.json"
        if actor_names is not None:
            actors_path.write_text(json.dumps(sorted(actor_names)), encoding="utf-8")
        command = ["java", "-Xmx4g",
                   f"-Dmallory.native.expectedEngineJar={selected_jar}",
                   "-cp", f"{classes}:{_classpath(selected_jar)}", JAVA_CLASS,
                   "--target-set", str(iteration), str(static_scope_map),
                   target_site, str(max_tasks),
                   str(actors_path) if actor_names is not None else "-",
                   str(raw_output),
                   str(target_check_receipts) if target_check_receipts else "-"]
        subprocess.run(command, check=True, timeout=1800,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        extracted = json.loads(raw_output.read_text(encoding="utf-8"))
    if _sha256(selected_jar) != jar_sha:
        raise ValueError("GraphChecker engine JAR changed during native analysis")
    if _session_digest(iteration) != session_sha:
        raise ValueError("native session changed during analysis")
    if _scope_digest(static_scope_map) != bundle_sha:
        raise ValueError("static scope map changed during native analysis")
    if target_check_receipts and _sha256(target_check_receipts) != receipts_sha:
        raise ValueError("target check receipts changed during native analysis")
    if extracted.get("schemaVersion") != 1 or extracted.get("targetSiteId") != target_site:
        raise ValueError("native target-set extractor returned a different target")
    selected = extracted.get("targets")
    per_target = extracted.get("perTargetOccurrences")
    site_rows_seen = extracted.get("siteTargetRowsSeen")
    unreached_rows = extracted.get("unreachedTargetRows")
    if not isinstance(selected, list) or not isinstance(per_target, list):
        raise ValueError("native target-set extractor returned invalid occurrence lists")
    if not isinstance(site_rows_seen, bool) or not isinstance(unreached_rows, list):
        raise ValueError("native target-set extractor omitted reach evidence")
    if len(selected) != len(per_target) or len({
            item.get("occurrenceId") for item in selected if isinstance(item, dict)
    }) != len(selected):
        raise ValueError("native target-set extractor conflated occurrences")
    if not selected:
        raise NoNativeTargetError("no exact reached target occurrence matches site/actor selection",
                                  site_target_rows_seen=site_rows_seen)
    for item, one in zip(selected, per_target):
        if (not isinstance(item, dict) or not isinstance(one, dict) or
                not isinstance(item.get("occurrenceId"), str) or
                not item["occurrenceId"] or
                not isinstance(item.get("nodeName"), str) or
                one.get("targetOccurrenceId") != item["occurrenceId"] or
                one.get("targetFamily") != item.get("targetFamily") or
                one.get("targetSiteId") != target_site or
                (actor_names is not None and item["nodeName"] not in actor_names)):
            raise ValueError("native target occurrence changed during extraction")
        rows = one.get("targetRows")
        receipts = one.get("targetReachReceipts")
        members = one.get("closureMembers")
        if not isinstance(rows, list) or not isinstance(receipts, list):
            raise ValueError("native target plan lacks target evidence lists")
        native_reached = any(row.get("occurrenceId") == item["occurrenceId"]
                             and row.get("reachedAnchor") is True
                             for row in rows if isinstance(row, dict))
        receipt_reached = any(row.get("occurrenceId") == item["occurrenceId"]
                              and row.get("reachedAnchor") is True
                              for row in receipts if isinstance(row, dict))
        if not native_reached and not receipt_reached:
            raise ValueError("native target plan lacks exact reach evidence")
        if (one.get("targetEvidenceKind") == "external_target_check"
                and (not receipt_reached or native_reached
                     or one.get("symbolicPredicateAvailable") is not False)):
            raise ValueError("external reach must not claim native predicate")
        if (one.get("targetEvidenceKind") == "native_target_row"
                and not native_reached):
            raise ValueError("native target plan lacks reached target row")
        if not isinstance(members, list) or not any(
                row.get("occurrenceId") == item["occurrenceId"]
                for row in members if isinstance(row, dict)):
            raise ValueError("native closure omitted exact target occurrence")
        one["engineJarSha256"] = jar_sha
        one["nativeSessionSha256"] = session_sha
        one["staticScopeMapSha256"] = scope_sha
        one["staticScopeBundleSha256"] = bundle_sha
        one["bridgeSourceSha256"] = bridge_sha
        one["targetCheckReceiptsSha256"] = receipts_sha
        one["maxTasks"] = max_tasks
    for key in ("engineJarSha256", "staticScopeMapSha256",
                "staticScopeBundleSha256", "bridgeSourceSha256",
                "targetCheckReceiptsSha256", "maxTasks", "method",
                "targetSiteId", "nativeSessionSha256"):
        if len({json.dumps(item[key], sort_keys=True) for item in per_target}) != 1:
            raise ValueError(f"native target set has mixed {key}")
    members: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    coverage: set[str] = set()
    rows: list[dict[str, Any]] = []
    reach_receipts: list[dict[str, Any]] = []
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
        reach_receipts.extend(one["targetReachReceipts"])
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
        "targetReachReceipts": reach_receipts,
        "targetEvidenceKinds": sorted({one["targetEvidenceKind"]
                                       for one in per_target}),
        "symbolicPredicateAvailable": all(
            one["symbolicPredicateAvailable"] for one in per_target),
        "unreachedTargetRows": unreached_rows,
        "perTargetOccurrences": per_target,
        "closureMembers": sorted(members.values(), key=lambda row: row["occurrenceId"]),
        "observedEdgesWithinClosure": list(edges.values()),
        "branchCoverage": sorted(coverage),
        "gaps": gaps,
        "truncated": sorted(truncated),
        "engineJarSha256": first["engineJarSha256"],
        "staticScopeMapSha256": first["staticScopeMapSha256"],
        "staticScopeBundleSha256": first["staticScopeBundleSha256"],
        "bridgeSourceSha256": first["bridgeSourceSha256"],
        "targetCheckReceiptsSha256": first["targetCheckReceiptsSha256"],
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

    Every target occurrence must have exact native reach evidence or a validated
    external TARGET_CHECK receipt, and appear in its native closure. Cross-run
    exact IDs may differ; a changed actor/region family or a trial without the
    target is rejected.
    """
    for key in ("schemaVersion", "method", "targetSiteId", "targetSetMode",
                "engineJarSha256", "staticScopeMapSha256",
                "staticScopeBundleSha256", "bridgeSourceSha256",
                "maxTasks"):
        if healthy.get(key) != trial.get(key):
            raise ValueError(f"incompatible native feedback: {key}")
    target_set = healthy.get("targetSetMode") is True
    if target_set:
        if (not isinstance(healthy.get("staticScopeBundleSha256"), str)
                or not healthy["staticScopeBundleSha256"]
                or not isinstance(trial.get("staticScopeBundleSha256"), str)
                or not trial["staticScopeBundleSha256"]):
            raise ValueError("target-set feedback lacks pinned static scope bundle")
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
                if not (any(row.get("occurrenceId") == anchor
                            and row.get("reachedAnchor") is True
                            for row in item.get("targetRows", [])
                            if isinstance(row, dict)) or any(
                        row.get("occurrenceId") == anchor
                        and row.get("reachedAnchor") is True
                        for row in item.get("targetReachReceipts", [])
                        if isinstance(row, dict))) or not any(
                        row.get("occurrenceId") == anchor
                        for row in item.get("closureMembers", [])
                        if isinstance(row, dict)):
                    raise ValueError(f"{label} lacks an exact per-target plan")
    for label, summary in (("healthy", healthy), ("trial", trial)):
        anchors = healthy_anchors if label == "healthy" else trial_anchors
        targets = summary.get("targetRows")
        receipts = summary.get("targetReachReceipts", [])
        if not isinstance(targets, list) or not isinstance(receipts, list) or not all(
                any(isinstance(row, dict) and row.get("occurrenceId") == anchor
                    and row.get("reachedAnchor") is True for row in targets)
                or any(isinstance(row, dict) and row.get("occurrenceId") == anchor
                       and row.get("reachedAnchor") is True for row in receipts)
                for anchor in anchors):
            raise ValueError(f"{label} lacks exact target reach evidence")
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
