#!/usr/bin/env python3
"""Import a terminal, SHA-sealed SOLR-37 actor-aware continuation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data/mallory"
RAW = DATA / "solr37_target_actor_full_v6_node0/SOLR-37/full"
PREFIX = "SOLR-37-target-actor-full-node0-v6"
ARCHIVE = DATA / "evidence_archives" / f"{PREFIX}.tar.gz"
MANIFEST = DATA / "evidence_archives" / f"{PREFIX}.members.json"
SEAL = DATA / "evidence_archives" / f"{PREFIX}.receipt.json"
DEST = DATA / "cases/SOLR-37"
PACKAGE = BASE / "Mallory/adapters/solr/cases/SOLR-37/target-actor-full-node0-v6"
SEALER = BASE / "Mallory/ops/seal_solr37_target_actor_node0_v6.py"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    if DEST.exists():
        raise RuntimeError("SOLR-37 canonical destination already exists")
    seal, manifest = read(SEAL), read(MANIFEST)
    result, checkpoint = read(RAW / "result.json"), read(RAW / "checkpoint.json")
    quality, depth = read(RAW / "terminal-quality.json"), read(RAW / "fault-depth-review.json")
    if not (
        result.get("case_id") == checkpoint.get("case_id") == quality.get("case_id") ==
        depth.get("case_id") == seal.get("case_id") == "SOLR-37"
        and result.get("status") == checkpoint.get("status") == quality.get("status")
        == seal.get("status") in {"budget_exhausted", "queue_exhausted"}
        and checkpoint.get("running") is None
        and quality.get("campaign_completion_credited") is True
        and quality.get("fault_trials_completed") == result.get("fault_trials_completed")
        and quality.get("strict_injected_trials") == result.get("strict_injected_trials")
        and quality.get("strict_target_trials") == result.get("strict_target_trials")
        and result.get("exact_exception_trials") == 0
        and quality.get("exact_target_exception_trials") == []
        and quality.get("raw_exact_target_throw_events") == []
        and quality.get("new_bug") is False
        and result.get("new_bug") is not True
        and quality.get("imported_valid_parent_trials") == [0, 1, 2]
        and quality.get("excluded_unmatched_parent_trials") == [3, 4, 5, 6]
        and quality.get("junit_qualified_strict_trials_including_imported") ==
        [1, 2, *quality.get("strict_new_junit_qualified_trials", [])]
        and set(quality.get("strict_new_junit_qualified_trials", [])).isdisjoint(
            quality.get("strict_new_path_valid_junit_invalid_trials", []))
        and set(quality.get("strict_new_valid_trials", [])) ==
        set(quality.get("strict_new_junit_qualified_trials", [])) |
        set(quality.get("strict_new_path_valid_junit_invalid_trials", []))
        and not (set(quality.get("strict_new_valid_trials", [])) &
                 set(quality.get("strict_new_invalid_trials", [])))
        and depth.get("campaign_result_sha256") == seal.get("result_sha256")
        and depth.get("campaign_checkpoint_sha256") == seal.get("checkpoint_sha256")
        and sum(depth.get("depth_distribution", {}).values()) == result.get("fault_trials_completed")
        and seal.get("all_archive_members_verified") is True
        and sha(ARCHIVE) == seal.get("archive_sha256") == manifest.get("archive_sha256")
        and sha(MANIFEST) == seal.get("member_manifest_sha256")
        and seal.get("member_count") == manifest.get("member_count") == len(manifest.get("members", []))
        and seal.get("result_sha256") == sha(RAW / "result.json")
        and seal.get("checkpoint_sha256") == sha(RAW / "checkpoint.json")
        and seal.get("quality_sidecar_sha256") == sha(RAW / "terminal-quality.json")
        and seal.get("depth_review_sha256") == sha(RAW / "fault-depth-review.json")
        and seal.get("config_sha256") == sha(RAW / "config.json")
        and seal.get("sealer_sha256") == sha(SEALER)
        and seal.get("admission_receipt_sha256") == sha(PACKAGE / "admission-full-node0.json")
    ):
        raise RuntimeError("SOLR-37 terminal, quality, archive, or trial partition differs")
    completed = checkpoint.get("completed_trials", [])
    if (completed[:3] != [0, 1, 2]
            or completed[3:] != list(range(7, 7 + len(completed[3:])))
            or len(completed) != result.get("fault_trials_completed") + 1):
        raise RuntimeError("SOLR-37 resumed trial sequence differs")
    member_rows = manifest["members"]
    prefix = "solr37_target_actor_full_v6_node0/SOLR-37/full/"
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        packed = tar.getmembers()
        if [m.name for m in packed] != [r["path"] for r in member_rows]:
            raise RuntimeError("SOLR-37 archive member list differs")
        for item, row in zip(packed, member_rows):
            if not item.isfile() or not item.name.startswith(prefix) or item.size != row["bytes"]:
                raise RuntimeError("SOLR-37 archive member metadata differs")
            stream = tar.extractfile(item)
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != row["sha256"]:
                raise RuntimeError("SOLR-37 archive member SHA differs")
    member_hashes = {r["path"].removeprefix(prefix): r["sha256"] for r in member_rows}
    for name in ("result.json", "config.json", "checkpoint.json", "terminal-quality.json",
                 "fault-depth-review.json"):
        if sha(RAW / name) != member_hashes.get(name):
            raise RuntimeError(f"SOLR-37 local raw differs from archive: {name}")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".solr37-import-", dir=DEST.parent) as tmp:
        root = Path(tmp)
        for name in ("result.json", "config.json", "checkpoint.json", "terminal-quality.json",
                     "fault-depth-review.json"):
            shutil.copyfile(RAW / name, root / name)
        shutil.copyfile(SEAL, root / "terminal-seal.json")
        for number in completed:
            trial = root / "trials" / f"r{number:04d}"
            trial.mkdir(parents=True)
            source = RAW / "trials" / f"r{number:04d}" / "result.json"
            rel = f"trials/r{number:04d}/result.json"
            if sha(source) != member_hashes.get(rel):
                raise RuntimeError(f"SOLR-37 local trial differs from archive: {rel}")
            shutil.copyfile(source, trial / "result.json")
            audit = source.with_name("strict-audit.json")
            if audit.is_file():
                rel = f"trials/r{number:04d}/strict-audit.json"
                if sha(audit) != member_hashes.get(rel):
                    raise RuntimeError(f"SOLR-37 strict audit differs from archive: {rel}")
                shutil.copyfile(audit, trial / "strict-audit.json")
        write(root / "canonical-import-receipt.json", {
            "schema_version": 1, "case_id": "SOLR-37", "status": result["status"],
            "completion_criterion": "natural_terminal_actor_aware_v6_after_sealed_v5_import",
            "result_sha256": sha(root / "result.json"),
            "config_sha256": sha(root / "config.json"),
            "checkpoint_sha256": sha(root / "checkpoint.json"),
            "quality_sha256": sha(root / "terminal-quality.json"),
            "depth_review_sha256": sha(root / "fault-depth-review.json"),
            "archive_sha256": sha(ARCHIVE), "manifest_sha256": sha(MANIFEST),
            "terminal_seal_sha256": sha(SEAL), "sealer_sha256": sha(SEALER),
            "importer_sha256": sha(Path(__file__)),
            "fault_trials_completed": result["fault_trials_completed"],
            "controller_strict_target_trials": result["strict_target_trials"],
            "junit_qualified_strict_trials": quality["junit_qualified_strict_trials_including_imported"],
            "path_valid_junit_invalid_trials": quality["strict_new_path_valid_junit_invalid_trials"],
            "junit_invalid_novelty_credit": quality["junit_invalid_novelty_credit"],
            "exact_target_exception_trials": [], "new_bug": False})
        root.rename(DEST)
    print(json.dumps({"case_id": "SOLR-37", "status": result["status"],
                      "fault_trials_completed": result["fault_trials_completed"],
                      "canonical_result_sha256": sha(DEST / "result.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
