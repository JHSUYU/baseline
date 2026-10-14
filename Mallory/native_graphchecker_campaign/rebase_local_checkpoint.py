"""Rebase only the config SHA of an exact native checkpoint to local work roots.

The frozen source remains read-only and every accepted trial stays byte-pinned.
This is a no-JVM import step, not a fault-sequence mutation or a new seed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from . import campaign
from .guarded_one_fault import _require_local, _require_pg0_read_only, _sha


EVIDENCE = ("result.json", "iteration-native/fault-plan.json",
            "iteration-native/fault-events.jsonl", "native-summary.json",
            "schedule-lineage.json")


def _same_config_except_local_roots(old: dict, new: dict) -> None:
    left, right = copy.deepcopy(old), copy.deepcopy(new)
    for config in (left, right):
        runner = config.get("runner")
        if not isinstance(runner, dict):
            raise ValueError("native runner is missing")
        runner.pop("local_artifact_root", None)
        runner.pop("local_work_root", None)
    if left != right:
        raise ValueError("config changes more than local runner roots")
    for name in ("local_artifact_root", "local_work_root"):
        value = new["runner"].get(name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"local config needs explicit {name}")


def _same_file(old: Path, local: Path, *, required: bool) -> str | None:
    if old.is_file() != local.is_file():
        raise ValueError(f"local evidence differs in presence: {local}")
    if not old.is_file():
        if required:
            raise ValueError(f"required accepted evidence is absent: {old}")
        return None
    old_sha = _sha(old)
    if _sha(local) != old_sha:
        raise ValueError(f"accepted evidence SHA differs: {local}")
    return old_sha


def _evidence(old_root: Path, local_root: Path, state: dict) -> dict:
    trials = state.get("trials")
    count = state.get("completed_fault_trials")
    seen = state.get("seen_plan_keys")
    if (not isinstance(trials, list) or not isinstance(count, int) or
            isinstance(count, bool) or count < 0 or len(trials) != count or
            not isinstance(seen, list) or len(set(seen)) != len(seen)):
        raise ValueError("frozen checkpoint trial/plan index is malformed")
    if not isinstance(state.get("healthy"), dict) or state["healthy"].get(
            "result") != "trials/r0000/result.json":
        raise ValueError("frozen healthy result identity changed")
    healthy_sha = _same_file(old_root / state["healthy"]["result"],
                             local_root / state["healthy"]["result"], required=True)
    healthy = campaign._load(old_root / state["healthy"]["result"])
    if (healthy.get("case_id") != state.get("case_id") or
            healthy.get("status") != "healthy_seed" or healthy.get("faults") != []):
        raise ValueError("frozen healthy receipt is inconsistent")
    _same_file(old_root / "trials/r0000/native-summary.json",
               local_root / "trials/r0000/native-summary.json", required=True)
    names, keys = set(), set()
    digest = hashlib.sha256()
    for record in trials:
        name = record.get("name") if isinstance(record, dict) else None
        if (not isinstance(name, str) or not name.startswith("r") or
                not name[1:].isdigit() or name == "r0000" or name in names or
                record.get("result") != f"trials/{name}/result.json"):
            raise ValueError("accepted trial path/name is malformed")
        names.add(name)
        old_trial, local_trial = old_root / "trials" / name, local_root / "trials" / name
        for relative in EVIDENCE:
            sha = _same_file(old_trial / relative, local_trial / relative,
                             required=relative in EVIDENCE[:3])
            if sha is not None:
                digest.update(f"{name}/{relative}\0{sha}\n".encode())
        result = campaign._load(old_trial / "result.json")
        plan = campaign._load(old_trial / "iteration-native/fault-plan.json")
        if (result.get("case_id") != state.get("case_id") or
                result.get("status") != record.get("status") or
                result.get("strict_injection") != record.get("strict_injection") or
                result.get("target_exception_triggered") != record.get(
                    "target_exception_triggered") or
                result.get("faults") != plan.get("faults") or
                not isinstance(result.get("faults"), list) or
                not result["faults"]):
            raise ValueError(f"accepted result/plan disagrees: {name}")
        if result.get("fault_events_sha256") != _sha(
                old_trial / "iteration-native/fault-events.jsonl"):
            raise ValueError(f"accepted fault event SHA differs: {name}")
        key = campaign._plan_key(result["faults"])
        if key not in seen or key in keys:
            raise ValueError(f"accepted plan key is missing/duplicate: {name}")
        keys.add(key)
    active = state.get("active")
    if active is not None:
        if (not isinstance(active, dict) or
                not isinstance(active.get("key"), str) or not active["key"] or
                not isinstance(active.get("index"), int) or
                isinstance(active["index"], bool) or active["index"] <= 0 or
                not isinstance(active.get("faults"), list) or
                not active["faults"] or
                campaign._plan_key(active["faults"]) != active["key"] or
                active["key"] not in seen or active["key"] in keys or
                active.get("name") != f"r{active.get('index'):04d}" or
                active.get("index") != state.get("next_trial_index", 0) - 1):
            raise ValueError("frozen active fault plan identity changed")
        # A selected trial may be interrupted; its incomplete artifacts are
        # moved aside by the native engine after its original process is dead.
        if (old_root / "trials" / active["name"] / "result.json").is_file():
            _same_file(old_root / "trials" / active["name"] / "result.json",
                       local_root / "trials" / active["name"] / "result.json",
                       required=True)
    return {"completed_fault_trials": count,
            "accepted_plan_keys_sha256": hashlib.sha256(
                "\n".join(sorted(keys)).encode()).hexdigest(),
            "accepted_evidence_sha256": digest.hexdigest(),
            "healthy_result_sha256": healthy_sha,
            "active_key": active["key"] if active else None,
            "active_index": active["index"] if active else None}


def rebase(args: argparse.Namespace) -> dict:
    pg0 = args.pg0.resolve(strict=True)
    _require_pg0_read_only(pg0)
    old_root = args.source_root.resolve(strict=True)
    local_root = _require_local(args.local_root, pg0, "local campaign output")
    if not old_root.is_relative_to(pg0) or old_root == local_root:
        raise ValueError("frozen checkpoint must be a distinct PG0 input")
    alias = Path(os.path.abspath(args.frozen_alias))
    if (not alias.is_relative_to(local_root) or
            (alias.stat().st_dev, alias.stat().st_ino) !=
            (old_root.stat().st_dev, old_root.stat().st_ino) or
            not os.statvfs(alias).f_flag & os.ST_RDONLY):
        raise ValueError("frozen alias is not an exact read-only source bind")
    old_config_path = args.source_config.resolve(strict=True)
    local_config_path = args.local_config.resolve(strict=True)
    old_config, local_config = (campaign._load(path) for path in
                                (old_config_path, local_config_path))
    campaign._validate_config(local_config)
    _same_config_except_local_roots(old_config, local_config)
    campaign._validate_local_work_root(local_config, local_root)
    campaign._validate_local_artifact_root(local_config, local_root)
    old_config_sha, local_config_sha = _sha(old_config_path), _sha(local_config_path)
    old_checkpoint = old_root / "checkpoint.json"
    local_checkpoint = local_root / "checkpoint.json"
    old_admission = old_root / "recording-admission.json"
    local_admission = local_root / "recording-admission.json"
    if (_sha(old_checkpoint) != args.source_checkpoint_sha256 or
            _sha(old_admission) != args.source_admission_sha256 or
            _same_file(old_admission, local_admission, required=True) !=
            args.source_admission_sha256):
        raise ValueError("frozen checkpoint/admission SHA pin changed")
    source = campaign._load(old_checkpoint)
    if (source.get("config_sha256") != old_config_sha or
            source.get("budget") != old_config["budget"] or
            source.get("case_id") != old_config["case_id"] or
            source.get("terminal") is not False):
        raise ValueError("frozen checkpoint does not match source config")
    evidence = _evidence(old_root, local_root, source)
    # _admit only hashes frozen recording/weave/runner inputs when the copied
    # admission is present; it does not start a JUnit or select a fault.
    admitted = campaign._admit(local_config, local_root)
    if (admitted["origin"] != source["origin"] or
            admitted["zero_vm_sha256"] != source["zero_vm_sha256"] or
            admitted["runner_classpath_artifacts"] !=
            source["runner_classpath_artifacts"] or
            _sha(Path(admitted["weave_config"]["output_classes"]) /
                 "native-original-weave-receipt.json") !=
            source["weave_receipt_sha256"]):
        raise ValueError("frozen engine/JUnit/weave inputs changed")
    rebased = copy.deepcopy(source)
    rebased["config_sha256"] = local_config_sha
    expected = local_root / "checkpoint-rebase.json"
    receipt = {"schema_version": 1, "source_root": str(old_root),
               "local_root": str(local_root), "source_config_sha256": old_config_sha,
               "local_config_sha256": local_config_sha,
               "source_checkpoint_sha256": args.source_checkpoint_sha256,
               "source_admission_sha256": args.source_admission_sha256,
               "rebased_checkpoint_sha256": hashlib.sha256(
                   (json.dumps(rebased, sort_keys=True, indent=2) + "\n").encode()
               ).hexdigest(), **evidence}
    if expected.exists():
        if campaign._load(expected) != receipt:
            raise ValueError("local checkpoint rebase receipt changed")
        if _sha(local_checkpoint) != receipt["rebased_checkpoint_sha256"]:
            raise ValueError("rebased checkpoint changed after import")
        return receipt
    if _sha(local_checkpoint) not in (args.source_checkpoint_sha256,
                                      receipt["rebased_checkpoint_sha256"]):
        raise ValueError("local checkpoint is not an exact frozen copy")
    if getattr(args, "dry_run", False):
        return {**receipt, "dry_run": True}
    campaign._atomic(local_checkpoint, rebased)
    if _sha(local_checkpoint) != receipt["rebased_checkpoint_sha256"]:
        raise ValueError("rebased checkpoint write digest differs")
    campaign._atomic(expected, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pg0", "source-root", "local-root", "frozen-alias",
                 "source-config", "local-config"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-checkpoint-sha256", required=True)
    parser.add_argument("--source-admission-sha256", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="verify every input and emit a preview without writing")
    print(json.dumps(rebase(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
