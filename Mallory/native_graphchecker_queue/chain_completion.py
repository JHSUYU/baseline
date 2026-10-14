"""Audit a sequence of bounded native campaigns as one checklist experiment.

This is a read-only verifier.  A bounded successor's ``complete_trial_budget``
status does not by itself complete the checklist budget.  Each segment and its
predecessor link is pinned by SHA-256, and the exact target throw is recomputed
from the durable fault event stream.  Raw archives are checked through the
same verifier used by the native queue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import _checkpoint_trial_refs
from .raw_archive import verify_trial_evidence


SELECTOR = ("siteId", "node", "actorEpochOrdinal", "ordinal",
            "exceptionClass")
IDENTITY = ("siteId", "node", "actorEpochOrdinal", "occurrenceId",
            "ordinal", "exceptionClass")
TERMINAL = {"complete_trial_budget", "complete_time_budget", "complete_queue"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _pinned(ref: dict[str, str], label: str) -> Path:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError(f"{label} must pin an absolute path and SHA-256")
    path = Path(ref["path"])
    if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
            sha256(path) != ref["sha256"]):
        raise ValueError(f"{label} changed")
    return path


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _plan_key(faults: list[dict[str, Any]]) -> str:
    stable = [{name: fault[name] for name in SELECTOR} for fault in faults]
    return hashlib.sha256(json.dumps(stable, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    previous: dict[tuple[str, int], int] = {}
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            actor = (row.get("node"), row.get("actorEpochOrdinal"))
            seq = row.get("seq")
            if (not isinstance(actor[0], str) or not actor[0] or
                    not isinstance(actor[1], int) or isinstance(actor[1], bool) or
                    actor[1] < 0 or not isinstance(seq, int) or
                    isinstance(seq, bool) or seq <= previous.get(actor, 0)):
                raise ValueError(f"invalid native fault event {path}:{number}")
            previous[actor] = seq
            rows.append(row)
    if not rows:
        raise ValueError(f"empty native fault event stream: {path}")
    return rows


def _strict(faults: list[dict[str, Any]], rows: list[dict[str, Any]]) -> bool:
    applied = [row for row in rows if row.get("kind") == "FAULT_APPLIED"]
    if not faults or len(applied) != len(faults):
        return False
    doors = [row for row in rows if row.get("kind") == "FAULT_DOOR"]
    for planned, actual in zip(faults, applied):
        if tuple(actual.get(name) for name in SELECTOR) != tuple(
                planned.get(name) for name in SELECTOR):
            return False
        if not any(door["seq"] < actual["seq"] and
                   tuple(door.get(name) for name in IDENTITY) == tuple(
                       actual.get(name) for name in IDENTITY)
                   for door in doors):
            return False
    return True


def _exact_throw(rows: list[dict[str, Any]], target_site: str,
                 target_throw: dict[str, str]
                 ) -> tuple[list[dict[str, Any]], bool, str, dict[str, Any] | None]:
    checks = [row for row in rows if row.get("kind") == "TARGET_CHECK" and
              row.get("siteId") == target_site]
    applied = [row for row in rows if row.get("kind") == "FAULT_APPLIED"]
    last = applied[-1] if applied else None
    throws = []
    temporal = None
    for row in rows:
        if (row.get("kind") != "TARGET_THROW" or
                row.get("siteId") != target_throw["siteId"] or
                row.get("exceptionClass") != target_throw["exceptionClass"]):
            continue
        matching = [check for check in checks if
                    (check.get("occurrenceId"), check.get("node"),
                     check.get("actorEpochOrdinal")) ==
                    (row.get("occurrenceId"), row.get("node"),
                     row.get("actorEpochOrdinal")) and check["seq"] < row["seq"]]
        if not matching:
            continue
        throws.append(row)
        if last is not None:
            for check in matching:
                if ((last.get("occurrenceId"), last.get("node"),
                     last.get("actorEpochOrdinal")) ==
                    (check.get("occurrenceId"), check.get("node"),
                     check.get("actorEpochOrdinal")) and last["seq"] < check["seq"]):
                    temporal = {"faultSeq": last["seq"], "checkSeq": check["seq"],
                                "throwSeq": row["seq"],
                                "targetOccurrenceId": row["occurrenceId"]}
                    break
    if last is None:
        return throws, False, "no_applied_fault", None
    return (throws, temporal is not None,
            "same_occurrence_before_check" if temporal else
            "cross_occurrence_order_unproved" if throws else
            "no_exact_target_throw", temporal)


def _archive_evidence(root: Path, refs: list[tuple[dict, Path]], pin: dict[str, str],
                      case_id: str) -> str:
    receipt = _pinned(pin, "raw archive evidence")
    trial_hashes: dict[str, str] = {}
    raw_targets: dict[str, str] = {}
    for _, result_path in refs:
        trial = result_path.parent
        for relative in ("result.json", "native-summary.json",
                         "iteration-native/fault-events.jsonl"):
            path = trial / relative
            if path.is_file():
                trial_hashes[str(path.absolute())] = sha256(path)
        graph = trial / "original-graph/summary.json"
        if graph.parent.is_symlink():
            manifest = _load(trial / "local-artifacts.json")
            digest = manifest.get("selected_sha256", {}).get(
                "original-graph/summary.json")
            if not isinstance(digest, str):
                raise ValueError(f"missing archived graph hash: {trial}")
            trial_hashes[str(graph.absolute())] = digest
            raw_targets[str(graph.absolute())] = str(
                graph.parent.readlink() / graph.name)
        elif graph.is_file():
            trial_hashes[str(graph.absolute())] = sha256(graph)
    binding = {"raw_archive_evidence": pin}
    if not verify_trial_evidence(binding, case_id, trial_hashes, raw_targets):
        raise ValueError(f"raw archive fails exact trial evidence: {receipt}")
    return sha256(receipt)


def _frozen_audit(segment: dict[str, Any], expected: dict[str, int]) -> str | None:
    """Bind a prior full graph inspection to this exact terminal segment."""
    pin = segment.get("frozen_audit")
    if pin is None:
        return None
    receipt_path = _pinned(pin, "frozen full graph audit")
    receipt = _load(receipt_path)
    method = receipt.get("method")
    if method == "exact_frozen_python_full_native_inspect_case":
        row = receipt.get("row")
        if not isinstance(row, dict) or row.get("case_id") != expected["case_id"]:
            raise ValueError("frozen inspector case identity changed")
        fingerprint = receipt.get("fingerprint")
        if (not isinstance(fingerprint, dict) or
                fingerprint.get("config_sha256") != segment["config"]["sha256"] or
                fingerprint.get("checkpoint_sha256") != segment["checkpoint"]["sha256"] or
                fingerprint.get("summary_sha256") != segment["summary"]["sha256"] or
                fingerprint.get("native_root") != str(Path(
                    segment["checkpoint"]["path"]).parent)):
            raise ValueError("frozen inspector checkpoint identity changed")
        # The canonical queue receipt also pins source, engine and trial tree.
        if (not receipt.get("source_tar_sha256") or
                not receipt.get("engine_jar_sha256") or
                not receipt.get("trial_evidence_sha256")):
            raise ValueError("frozen inspector lacks source or trial pins")
    elif method == "read_only_full_native_inspect_case_with_frozen_graph_and_generic_closure_fix":
        if (receipt.get("case_id") != expected["case_id"] or
                receipt.get("frozen_config") != segment["config"] or
                receipt.get("frozen_checkpoint") != segment["checkpoint"] or
                receipt.get("frozen_summary") != segment["summary"]):
            raise ValueError("full graph replay gate input changed")
        row = receipt.get("inspection_result")
    else:
        raise ValueError("unrecognized frozen full graph audit method")
    if (not isinstance(row, dict) or
            row.get("native_tested_complete") is not True or
            row.get("fault_trials") != expected["fault_trials"] or
            row.get("strict_fault_trials") != expected["strict_fault_trials"] or
            row.get("strict_target_retained_fault_trials") != expected[
                "strict_target_retained_fault_trials"] or
            row.get("strict_in_target_closure_trials") != expected[
                "strict_in_target_closure_trials"] or
            row.get("target_throw_trials") != expected["target_throw_trials"] or
            row.get("elapsed_seconds") != expected["elapsed_seconds"]):
        raise ValueError("frozen full graph audit disagrees with durable events")
    return pin["sha256"]


def inspect_chain(manifest_path: Path) -> dict[str, Any]:
    """Return a pinned partial or terminal receipt; never run a JUnit."""
    manifest_path = manifest_path.resolve(strict=True)
    manifest = _load(manifest_path)
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported chain manifest")
    case_id = manifest.get("case_id")
    budget = manifest.get("budget")
    segments = manifest.get("segments")
    if (not isinstance(case_id, str) or not case_id or
            not isinstance(budget, dict) or
            not isinstance(budget.get("fault_trials"), int) or
            budget["fault_trials"] <= 0 or
            not isinstance(budget.get("seconds"), (int, float)) or
            budget["seconds"] <= 0 or
            not isinstance(segments, list) or not segments):
        raise ValueError("invalid chain identity or budget")
    authority_pin = manifest.get("formal_budget_authority")
    authority_sha = None
    if authority_pin is not None:
        authority_path = _pinned(authority_pin, "formal per-case budget authority")
        authority = _load(authority_path)
        if authority.get("case_id") != case_id or authority.get("budget") != budget:
            raise ValueError("formal per-case budget authority disagrees")
        authority_sha = authority_pin["sha256"]
    expected_junit = expected_target = None
    prior = None
    prior_keys: set[str] = set()
    all_keys: set[str] = set()
    checked = strict = retained = closure = throws = 0
    elapsed = 0.0
    audited_segments = []
    for number, segment in enumerate(segments):
        before = (checked, strict, retained, closure, throws)
        config_path = _pinned(segment["config"], f"segment {number} config")
        checkpoint_path = _pinned(segment["checkpoint"],
                                  f"segment {number} checkpoint")
        root = checkpoint_path.parent
        if checkpoint_path.name != "checkpoint.json" or root.is_symlink():
            raise ValueError("native segment root changed")
        config = _load(config_path)
        checkpoint = _load(checkpoint_path)
        if (config.get("case_id") != case_id or
                checkpoint.get("case_id") != case_id or
                checkpoint.get("config_sha256") != segment["config"]["sha256"] or
                checkpoint.get("completed_fault_trials") != len(
                    checkpoint.get("trials", [])) or
                config.get("runner", {}).get("mode") != "region_state"):
            raise ValueError(f"segment {number} native identity changed")
        junit = config.get("junit")
        target = (config.get("target_site"), config.get("target_throw"))
        if expected_junit is None:
            expected_junit, expected_target = junit, target
        elif junit != expected_junit or target != expected_target:
            raise ValueError("successor changed original JUnit or exact target")
        if prior is None:
            if config.get("predecessor_campaign") is not None:
                raise ValueError("first chain segment has an omitted predecessor")
        else:
            pred = config.get("predecessor_campaign")
            for label in ("config", "checkpoint", "summary"):
                if (not isinstance(pred, dict) or
                        pred.get(label) != str(prior[label]["path"]) or
                        pred.get(label + "_sha256") != prior[label]["sha256"]):
                    raise ValueError("successor predecessor pin changed")
            if not checkpoint.get("predecessor_import"):
                raise ValueError("successor omitted predecessor import")
        terminal = checkpoint.get("terminal") is True
        if number < len(segments) - 1 and not terminal:
            raise ValueError("a nonterminal segment cannot have a successor")
        if terminal:
            summary_path = _pinned(segment["summary"],
                                   f"segment {number} summary")
            if summary_path != root / "summary.json":
                raise ValueError("native summary path changed")
            summary = _load(summary_path)
            if (checkpoint.get("status") not in TERMINAL or
                    summary.get("completed_fault_trials") != checkpoint[
                        "completed_fault_trials"] or
                    summary.get("elapsed_seconds") != checkpoint.get(
                        "elapsed_seconds") or checkpoint.get("active") is not None):
                raise ValueError("terminal native summary changed")
        elif segment.get("summary") is not None:
            raise ValueError("nonterminal segment claims a summary")
        refs = _checkpoint_trial_refs(root, checkpoint)
        healthy_path = refs[0][1]
        healthy = _load(healthy_path)
        result_hashes = {"r0000": sha256(healthy_path)}
        if (healthy.get("status") != "healthy_seed" or
                healthy.get("junit_passed") is not True or
                healthy.get("native_target_retained") is not True or
                healthy.get("target_exception_triggered") is not False):
            raise ValueError("segment healthy seed is invalid")
        local_keys: set[str] = set()
        segment_elapsed = healthy.get("elapsed_seconds")
        if not isinstance(segment_elapsed, (int, float)) or segment_elapsed < 0:
            raise ValueError("healthy elapsed time is invalid")
        for record, result_path in refs[1:]:
            name = record["name"]
            trial = result_path.parent
            result = _load(result_path)
            result_hashes[name] = sha256(result_path)
            faults = result.get("faults")
            if (result.get("case_id") != case_id or not isinstance(faults, list) or
                    not faults or len(faults) > budget.get("max_faults_per_trial", 10)):
                raise ValueError("fault plan is invalid")
            if (not isinstance(result.get("elapsed_seconds"), (int, float)) or
                    result["elapsed_seconds"] < 0 or
                    record.get("elapsed_seconds") != result["elapsed_seconds"] or
                    record.get("strict_injection") is not result.get("strict_injection") or
                    record.get("native_target_retained") is not result.get(
                        "native_target_retained") or
                    record.get("target_exception_triggered") is not result.get(
                        "target_exception_triggered")):
                raise ValueError("native trial timing or checkpoint row changed")
            segment_elapsed += result["elapsed_seconds"]
            key = _plan_key(faults)
            if key in prior_keys:
                raise ValueError("successor replayed a prior exact fault plan")
            if key in local_keys:
                raise ValueError("segment replayed an exact fault plan")
            local_keys.add(key)
            events_path = trial / "iteration-native/fault-events.jsonl"
            if sha256(events_path) != result.get("fault_events_sha256"):
                raise ValueError("durable fault events changed")
            events = _rows(events_path)
            is_strict = _strict(faults, events)
            if is_strict is not result.get("strict_injection"):
                raise ValueError("strict injection disagrees with fault events")
            if is_strict and result.get("native_target_retained") is True:
                exact, admitted, reason, evidence = _exact_throw(
                    events, config["target_site"], config["target_throw"])
                if (result.get("target_throw_rows") != exact or
                        result.get("target_exception_triggered") is not bool(exact) or
                        result.get("target_temporal_admitted") is not admitted or
                        result.get("target_temporal_reason") != reason or
                        result.get("target_temporal_evidence") != evidence):
                    raise ValueError("exact target exception oracle changed")
            elif result.get("target_exception_triggered") is not False:
                raise ValueError("unretained or nonstrict throw claimed as bug")
            checked += 1
            strict += is_strict
            retained += bool(is_strict and result.get("native_target_retained"))
            closure += bool(is_strict and result.get("native_target_retained") and
                            result.get("fault_in_target_closure"))
            throws += bool(is_strict and result.get("native_target_retained") and
                           result.get("target_exception_triggered"))
        if abs(round(segment_elapsed, 3) - checkpoint.get("elapsed_seconds", -1)) > 0.001:
            raise ValueError("native campaign elapsed time differs from trial sum")
        if segment.get("raw_archive_evidence") is not None:
            archive_sha = _archive_evidence(
                root, refs, segment["raw_archive_evidence"], case_id)
        else:
            archive_sha = None
            for _, result_path in refs:
                trial = result_path.parent
                result = _load(result_path)
                graph = trial / "original-graph/summary.json"
                if result.get("native_target_retained") and not graph.is_file():
                    raise ValueError("neither live graph nor pinned raw archive exists")
        audit_sha = (_frozen_audit(segment, {
            "case_id": case_id,
            "fault_trials": checked - before[0],
            "strict_fault_trials": strict - before[1],
            "strict_target_retained_fault_trials": retained - before[2],
            "strict_in_target_closure_trials": closure - before[3],
            "target_throw_trials": throws - before[4],
            "elapsed_seconds": checkpoint.get("elapsed_seconds")})
                     if terminal else None)
        audited_segments.append({"root": str(root),
                                 "config_sha256": segment["config"]["sha256"],
                                 "checkpoint_sha256": segment["checkpoint"]["sha256"],
                                 "summary_sha256": segment.get("summary", {}).get(
                                     "sha256"), "terminal": terminal,
                                 "completed_fault_trials": len(checkpoint["trials"]),
                                 "distinct_plan_keys": len(local_keys),
                                 "trial_result_sha256": result_hashes,
                                 "raw_archive_evidence_sha256": archive_sha,
                                 "frozen_full_graph_audit_sha256": audit_sha})
        elapsed += checkpoint.get("elapsed_seconds", 0.0)
        prior_keys.update(local_keys)
        all_keys.update(local_keys)
        prior = {"config": segment["config"],
                 "checkpoint": segment["checkpoint"],
                 "summary": segment.get("summary")}
    budget_reached = (checked >= budget["fault_trials"] or
                      elapsed >= budget["seconds"])
    complete = bool(authority_sha and budget_reached and all(
        item["terminal"] and item["frozen_full_graph_audit_sha256"]
        for item in audited_segments))
    return {"schema_version": 1, "method": "exact_native_successor_chain_audit",
            "case_id": case_id, "manifest_path": str(manifest_path),
            "manifest_sha256": sha256(manifest_path),
            "verifier_sha256": sha256(Path(__file__)),
            "budget": budget, "status": "complete" if complete else "partial",
            "formal_budget_authority_sha256": authority_sha,
            "native_tested_complete": complete,
            "completed_fault_trials": checked, "strict_fault_trials": strict,
            "strict_target_retained_fault_trials": retained,
            "strict_in_target_closure_trials": closure,
            "exact_target_throw_trials": throws,
            "distinct_fault_plan_keys": len(all_keys),
            "elapsed_seconds": round(elapsed, 3),
            "segments": audited_segments}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = inspect_chain(args.manifest)
    content = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise ValueError("chain receipt already exists")
        args.output.write_text(content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
