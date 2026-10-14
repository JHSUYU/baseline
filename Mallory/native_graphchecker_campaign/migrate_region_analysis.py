"""Version a REGION_STATE checkpoint for an analysis-only resolver upgrade.

The original JUnit, woven classes, runtime engine, target, and accepted plans
remain byte pinned.  Only host-local work roots and the offline GraphChecker
analyzer may change.  This command never executes a workload JUnit.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import campaign
from .guarded_one_fault import _require_local, _require_pg0_read_only, _sha
from .rebase_local_checkpoint import _evidence, _same_file


def _compatible_config(old: dict, new: dict) -> None:
    left, right = copy.deepcopy(old), copy.deepcopy(new)
    for config in (left, right):
        runner = config.get("runner")
        recording = config.get("recording")
        if not isinstance(runner, dict) or not isinstance(recording, dict):
            raise ValueError("REGION_STATE migration needs runner and recording")
        if runner.get("mode") != "region_state" or (
                recording.get("admission_mode") != "region_state_no_schedule" or
                not recording.get("target_occurrence")):
            raise ValueError("analysis-only migration needs exact REGION_STATE target")
        runner.pop("local_artifact_root", None)
        runner.pop("local_work_root", None)
        recording.pop("analysis_engine_jar", None)
        recording.pop("analysis_engine_sha256", None)
    if left != right:
        raise ValueError("migration changes original workload, target, or runtime inputs")
    for name in ("local_artifact_root", "local_work_root"):
        value = new["runner"].get(name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"local successor needs explicit {name}")
    if any(name in old["recording"] for name in (
            "analysis_engine_jar", "analysis_engine_sha256")) and (
            set(name for name in ("analysis_engine_jar", "analysis_engine_sha256")
                if name in old["recording"]) !=
            {"analysis_engine_jar", "analysis_engine_sha256"}):
        raise ValueError("old analysis engine pin is incomplete")
    if set(name for name in ("analysis_engine_jar", "analysis_engine_sha256")
           if name in new["recording"]) != (
            {"analysis_engine_jar", "analysis_engine_sha256"}):
        raise ValueError("successor needs an exact analysis JAR path and SHA")


def _preview_admission(old_admission: dict, old_config: dict,
                       new_config: dict) -> tuple[dict, dict]:
    old_fp = old_admission.get("recording_fingerprint")
    if (old_admission.get("schema_version") != campaign.SCHEMA or
            not isinstance(old_fp, dict) or
            not isinstance(old_admission.get("origin"), dict)):
        raise ValueError("frozen recording admission is malformed")
    if old_fp.get("admission_mode") != "region_state_no_schedule":
        raise ValueError("frozen recording admission is not task-free")
    if "resolver_protocol" in old_fp:
        raise ValueError("frozen predecessor already has a resolver protocol pin")
    old_jar = old_config["recording"].get("analysis_engine_jar")
    old_sha = old_config["recording"].get("analysis_engine_sha256")
    if old_jar is None:
        if "analysis_engine_jar" in old_fp or "analysis_engine_sha256" in old_fp:
            raise ValueError("frozen analysis fingerprint disagrees with config")
        old_sha = old_fp.get("engine_jar_sha256")
    elif (old_fp.get("analysis_engine_jar") != str(Path(old_jar).resolve(strict=True)) or
          old_fp.get("analysis_engine_sha256") != old_sha or
          _sha(Path(old_jar).resolve(strict=True)) != old_sha):
        raise ValueError("frozen analysis JAR pin changed")
    if (not isinstance(old_sha, str) or
            old_fp.get("engine_jar_sha256") != _sha(campaign.JAR)):
        raise ValueError("frozen runtime GraphChecker engine changed")
    new_jar = Path(new_config["recording"]["analysis_engine_jar"]).resolve(strict=True)
    new_sha = new_config["recording"]["analysis_engine_sha256"]
    if _sha(new_jar) != new_sha or new_sha == old_sha:
        raise ValueError("schema 2 analysis JAR must differ and match its SHA pin")
    weave = campaign._load(Path(new_config["native_weave_config"]).resolve(strict=True))
    protocol = campaign._require_exact_resolver_protocol(
        new_config, Path(weave["java"]))
    capabilities = protocol.get("capabilities") if isinstance(protocol, dict) else None
    if (not isinstance(capabilities, dict) or
            protocol.get("analysis_engine_jar_sha256") != new_sha or
            capabilities.get("schemaVersion") != 1 or
            capabilities.get("kind") != "MALLORY_TARGET_RESOLVER_CAPABILITIES" or
            capabilities.get("exactRequestedOccurrenceReceiptSchemaVersion") != 2 or
            capabilities.get("exactSelectionPolicy") !=
            "EXACT_REQUESTED_OCCURRENCE_THEN_EARLIEST_EVENT"):
        raise ValueError("schema 2 resolver capability proof is absent")
    fp = copy.deepcopy(old_fp)
    fp.update(resolver_protocol=protocol,
              analysis_engine_jar=str(new_jar),
              analysis_engine_sha256=new_sha)
    preview = copy.deepcopy(old_admission)
    preview["recording_fingerprint"] = fp
    return preview, protocol


def _migrate_locked(args: argparse.Namespace) -> dict:
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
    new_config_path = args.local_config.resolve(strict=True)
    old_config, new_config = (campaign._load(path) for path in (
        old_config_path, new_config_path))
    campaign._validate_config(new_config)
    _compatible_config(old_config, new_config)
    campaign._validate_local_work_root(new_config, local_root)
    campaign._validate_local_artifact_root(new_config, local_root)
    old_checkpoint = old_root / "checkpoint.json"
    old_admission = old_root / "recording-admission.json"
    local_checkpoint = local_root / "checkpoint.json"
    local_admission = local_root / "recording-admission.json"
    if (_sha(old_checkpoint) != args.source_checkpoint_sha256 or
            _sha(old_admission) != args.source_admission_sha256):
        raise ValueError("frozen checkpoint/admission SHA pin changed")
    source = campaign._load(old_checkpoint)
    old_config_sha, new_config_sha = _sha(old_config_path), _sha(new_config_path)
    if (source.get("schema_version") != campaign.SCHEMA or
            source.get("config_sha256") != old_config_sha or
            source.get("budget") != old_config["budget"] or
            source.get("case_id") != old_config["case_id"] or
            source.get("terminal") is not False or
            source.get("origin") != campaign._load(old_admission).get("origin")):
        raise ValueError("frozen checkpoint and admission disagree")
    evidence = _evidence(old_root, local_root, source)
    preview, protocol = _preview_admission(
        campaign._load(old_admission), old_config, new_config)
    preview_sha = hashlib.sha256((json.dumps(
        preview, sort_keys=True, indent=2) + "\n").encode()).hexdigest()
    if _sha(local_admission) not in (args.source_admission_sha256, preview_sha):
        raise ValueError("local recording admission is neither frozen nor migrated")
    # Verify the complete current admission fingerprint in disposable scratch.
    # A dry-run changes no byte in the local checkpoint or its admission.
    with tempfile.TemporaryDirectory(prefix=".analysis-migration-",
                                     dir=local_root.parent) as scratch:
        campaign._atomic(Path(scratch) / "recording-admission.json", preview)
        admitted = campaign._admit(new_config, Path(scratch))
    if (admitted["origin"] != source["origin"] or
            admitted["zero_vm_sha256"] != source["zero_vm_sha256"] or
            admitted["runner_classpath_artifacts"] !=
            source["runner_classpath_artifacts"] or
            _sha(Path(admitted["weave_config"]["output_classes"]) /
                 "native-original-weave-receipt.json") !=
            source["weave_receipt_sha256"]):
        raise ValueError("original JUnit, weave, or runtime admission changed")
    rebased = copy.deepcopy(source)
    rebased["config_sha256"] = new_config_sha
    checkpoint_sha = hashlib.sha256((json.dumps(
        rebased, sort_keys=True, indent=2) + "\n").encode()).hexdigest()
    receipt_path = local_root / "checkpoint-analysis-migration.json"
    receipt = {"schema_version": 1, "kind": "region_state_analysis_only_migration",
               "source_root": str(old_root), "local_root": str(local_root),
               "source_config_sha256": old_config_sha,
               "local_config_sha256": new_config_sha,
               "source_checkpoint_sha256": args.source_checkpoint_sha256,
               "source_admission_sha256": args.source_admission_sha256,
               "rebased_checkpoint_sha256": checkpoint_sha,
               "migrated_admission_sha256": preview_sha,
               "runtime_engine_sha256": _sha(campaign.JAR),
               "campaign_source_sha256": _sha(Path(campaign.__file__)),
               "migrator_source_sha256": _sha(Path(__file__)),
               "analysis_engine_sha256": new_config["recording"][
                   "analysis_engine_sha256"],
               "resolver_protocol": protocol, **evidence}
    if _sha(local_checkpoint) not in (args.source_checkpoint_sha256, checkpoint_sha):
        raise ValueError("local checkpoint is neither frozen nor migrated")
    if receipt_path.exists():
        if (campaign._load(receipt_path) != receipt or
                _sha(local_checkpoint) != checkpoint_sha or
                _sha(local_admission) != preview_sha):
            raise ValueError("analysis migration receipt or outputs changed")
        return receipt
    if (_sha(old_checkpoint) != args.source_checkpoint_sha256 or
            _sha(old_admission) != args.source_admission_sha256):
        raise ValueError("frozen checkpoint/admission changed during verification")
    if _evidence(old_root, local_root, source) != evidence:
        raise ValueError("accepted trial evidence changed during verification")
    if getattr(args, "dry_run", False):
        return {**receipt, "dry_run": True}
    # Both intermediate orders fail closed in run_campaign; a retry finishes
    # the exact pins after a crash without rerunning any accepted fault plan.
    campaign._atomic(local_checkpoint, rebased)
    campaign._atomic(local_admission, preview)
    campaign._atomic(receipt_path, receipt)
    if (_sha(old_checkpoint) != args.source_checkpoint_sha256 or
            _sha(old_admission) != args.source_admission_sha256):
        raise ValueError("frozen checkpoint/admission changed during migration")
    return receipt


def migrate(args: argparse.Namespace) -> dict:
    """Require the same local lock as the native campaign, including dry-run."""
    lock_path = args.local_root / ".campaign.lock"
    if not lock_path.is_file():
        raise ValueError("local campaign lock must be staged before migration")
    with lock_path.open("r+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as failure:
            raise RuntimeError("local campaign is owned by another worker") from failure
        return _migrate_locked(args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pg0", "source-root", "local-root", "frozen-alias",
                 "source-config", "local-config"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-checkpoint-sha256", required=True)
    parser.add_argument("--source-admission-sha256", required=True)
    parser.add_argument("--dry-run", action="store_true")
    print(json.dumps(migrate(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
