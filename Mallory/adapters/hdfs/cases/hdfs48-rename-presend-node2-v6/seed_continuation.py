#!/usr/bin/env python3
"""Verify sealed v5 evidence and derive a resumable v6 checkpoint offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from strict_policy import BASE, HERE, campaign, install_policy, qualifies, trial_path

ARCHIVE = BASE / "data/mallory/evidence_archives/HDFS-48-rename-presend-full-v5.tar.gz"
RECEIPT = BASE / "data/mallory/evidence_archives/HDFS-48-rename-presend-full-v5.receipt.json"
MEMBERS = BASE / "data/mallory/evidence_archives/HDFS-48-rename-presend-full-v5.members.json"
CONFIG = HERE / "HDFS-48-node2-full-v6.json"
PREFIX = "HDFS-48-rename-presend-full-v5/"
PIN = {"archive": "78e935277aa479bb0f85879b4f35c3764b7318b8bf9584f523860321e839abab",
       "receipt": "9c1316fbd336fb053bb91ab12a81bc56dc966e497ede43ef8b1680efe0c57828",
       "members": "c943455555ba94e7218406067863f71aa61040cfbf5a598768d3a87d1020c1a5",
       "v5_result": "3cdefc7b5e41ff49f670318b0d61e7c2435e5ea90162375ed5b80e3ed770b089",
       "v5_checkpoint": "3124d7e51520cd359691d1e40ab248dd2a847d6e2835992f8d66dd2272d52cc7",
       "v5_strict": "f51538765b61ae6db538a7175864217ae71f9f8f58a7a4fbae14eb8ceddca1e2"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise ValueError(f"sealed evidence changed: {path}")


def read_archive_trials(destination: Path) -> dict:
    for name, digest in ((ARCHIVE, PIN["archive"]), (RECEIPT, PIN["receipt"]),
                         (MEMBERS, PIN["members"])):
        require(name, digest)
    receipt = json.loads(RECEIPT.read_text())
    members = json.loads(MEMBERS.read_text())["files"]
    if (receipt.get("archive_sha256") != PIN["archive"] or
            receipt.get("manifest_sha256") != PIN["members"] or
            receipt.get("member_count") != 24 or
            receipt.get("result_sha256") != PIN["v5_result"] or
            receipt.get("checkpoint_sha256") != PIN["v5_checkpoint"] or
            receipt.get("strict_audit_sha256") != PIN["v5_strict"] or
            receipt.get("strict_injected_trials") != 1 or
            receipt.get("strict_target_trials") != 1 or
            receipt.get("exact_exception_trials") != 0):
        raise ValueError("v5 seal is not the verified one-fault terminal")
    with tarfile.open(ARCHIVE, "r:gz") as source:
        files = {member.name: member for member in source if member.isfile()}
        expected = {PREFIX + name for name in members}
        if set(files) != expected:
            raise ValueError("archive member set changed")
        for relative, expected_hash in members.items():
            stream = source.extractfile(files[PREFIX + relative])
            if stream is None:
                raise ValueError(f"missing archive member: {relative}")
            data = stream.read()
            if hashlib.sha256(data).hexdigest() != expected_hash:
                raise ValueError(f"archive member SHA mismatch: {relative}")
            if relative.startswith("trials/r0000/") or relative.startswith("trials/r0001/"):
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            elif relative in ("config.json", "result.json", "checkpoint.json",
                              "v5-strict-audit.json", "offline-causal-audit.json"):
                target = destination / "provenance" / "v5" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    summary = json.loads((destination / "provenance/v5/result.json").read_text())
    checkpoint = json.loads((destination / "provenance/v5/checkpoint.json").read_text())
    strict = json.loads((destination / "provenance/v5/v5-strict-audit.json").read_text())
    core = json.loads((destination / "provenance/v5/offline-causal-audit.json").read_text())
    if (summary.get("status") != "budget_exhausted" or
            summary.get("fault_trials_completed") != 1 or
            checkpoint.get("completed_trials") != [0, 1] or checkpoint.get("queue") != [] or
            strict.get("strict_gate_passed") is not True or
            core.get("report_gate_passed") is not True):
        raise ValueError("v5 terminal/audit claims differ from seal")
    return members


def derive(output: Path, *, source_override: Path | None = None) -> dict:
    if output.exists():
        raise ValueError(f"v6 output exists; inspect before resume: {output}")
    cfg = json.loads(CONFIG.read_text())
    validation = dict(cfg)
    if source_override is not None:
        validation["cwd"] = str(source_override)
    campaign.validate_config(validation)
    campaign.verify_validated_recovery_sites(cfg)
    temporary = output.with_name(output.name + ".seed-partial")
    if temporary.exists():
        raise ValueError(f"stale seed directory: {temporary}")
    temporary.mkdir(parents=True)
    try:
        members = read_archive_trials(temporary)
        state = campaign._fresh_state(cfg)
        state["out"] = str(temporary.resolve())
        state["calibration_only"] = False
        install_policy()
        healthy = json.loads((temporary / "trials/r0000/result.json").read_text())
        faulted = json.loads((temporary / "trials/r0001/result.json").read_text())
        for number in (0, 1):
            source_result = temporary / f"trials/r{number:04d}/result.json"
            original_result = temporary / f"provenance/v5/trials/r{number:04d}/result.json"
            original_result.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_result, original_result)
        path = trial_path(temporary, faulted, cfg["target"])
        if not qualifies(faulted, path):
            raise ValueError(f"sealed v5 fault trial is not v6 strict valid: {path}")
        path["trace_receipt"]["path"] = "trials/r0001/events.jsonl.gz"
        campaign._apply_result(state, cfg, healthy, None)
        old_sig = campaign.sequence_signature(faulted["plan"])
        prior = [item for item in state["queue"] if item["signature"] == old_sig]
        if len(prior) != 1 or len(state["queue"]) != 1:
            raise ValueError("v6 fresh-seed queue does not reproduce v5 first plan")
        state["queue"].remove(prior[0])
        state["next_trial"] = 2
        campaign._apply_result(state, cfg, faulted, prior[0])
        queued = state["queue"]
        if (state["status"] != "running" or state["completed_trials"] != [0, 1] or
                len(queued) != 1 or len(queued[0]["faults"]) != 2 or
                [f["point"].get("door_ordinal") for f in queued[0]["faults"]] != [1, 2] or
                queued[0]["faults"][0] != faulted["plan"][0]):
            raise ValueError("no exact v5 ordinal-2 continuation candidate")
        state["out"] = str(output.resolve())
        campaign.atomic_json(temporary / "config.json", cfg)
        campaign.atomic_json(temporary / "checkpoint.json", state)
        campaign._write_summary(temporary, state, cfg)
        proof = {"schema_version": 1, "case_id": "HDFS-48", "source_kind": "sealed_v5_reuse",
                 "v5_receipt_sha256": PIN["receipt"], "v5_archive_sha256": PIN["archive"],
                 "v5_member_count": len(members),
                 "v5_r0000_result_sha256": members["trials/r0000/result.json"],
                 "v5_r0001_result_sha256": members["trials/r0001/result.json"],
                 "v5_r0001_strict_path": path,
                 "v6_config_sha256": sha(CONFIG), "v6_checkpoint_sha256": sha(temporary / "checkpoint.json"),
                 "v6_reused_trials": [0, 1], "next_trial": 2,
                 "next_fault_ordinals": [1, 2], "next_signature": queued[0]["signature"],
                 "jvms_started_by_seed": 0, "go": False}
        campaign.atomic_json(temporary / "seed-provenance.json", proof)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(output)
        return proof
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-override", type=Path,
                        help="offline validation only; recorded config remains pinned")
    args = parser.parse_args()
    print(json.dumps(derive(args.out, source_override=args.source_override), sort_keys=True))
