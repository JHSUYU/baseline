"""Reconstruct the sealed v2 queue, drop invalid r0004 credit, and seed v3."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V2 = HERE.parent / "fault-bootstrap-node0-v2"
SOURCE = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v2"
OUT = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v3"
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
sys.path.insert(0, str(RELEASE))
sys.path.insert(0, str(V2))
from Mallory.core import campaign  # noqa: E402
from Mallory.core.feedback import digest  # noqa: E402
from Mallory.core.scheduler import sequence_signature  # noqa: E402
import seed_selector as seed  # noqa: E402

_spec = importlib.util.spec_from_file_location("solr15_v2_runner", V2 / "run_campaign.py")
assert _spec is not None and _spec.loader is not None
v2_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v2_runner)


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def verify_source() -> dict:
    receipt = read(HERE / "source-receipt.json")
    require(receipt.get("case_id") == "SOLR-15" and
            receipt.get("source_output") == str(SOURCE) and
            receipt.get("v2_manifest_sha256") == sha(V2 / "sha-manifest.json"),
            "wrong v2 continuation source")
    for name, expected in receipt["files"].items():
        path = SOURCE / name
        require(path.is_file() and sha(path) == expected, "v2 evidence changed: " + name)
    require(read(SOURCE / "config.json") == read(V2 / "config-full-node0.json"),
            "v2 runtime config differs from sealed package")
    return receipt


def _sanitized_invalid(result: dict) -> dict:
    result = copy.deepcopy(result)
    feedback = result["feedback"]
    require(len(result["plan"]) == 3 and
            result.get("resource_attestation", {}).get("valid") is False and
            feedback.get("all_faults_effective") is False,
            "r0004 is not the recorded invalid depth-three plan")
    feedback.update(coverage_ids=[], closure_coverage_ids=[], closure_edges=[],
                    doors=[], target_reached=False, target_check_reached=False,
                    target_threw=False, target_exception_candidate=False,
                    target_check_actors=[], target_instances=[], target_closures=[],
                    all_faults_effective=False, status="dropped_invalid_depth_three")
    return result


def _replay(config: dict, *, sanitize_last: bool) -> tuple[dict, list[dict]]:
    picks = []
    with tempfile.TemporaryDirectory(prefix="solr15-v3-replay-") as scratch:
        state = campaign._fresh_state(config)
        state["out"] = scratch
        state["calibration_only"] = False
        for trial_id in range(5):
            result = copy.deepcopy(read(SOURCE / "trials" /
                                        f"r{trial_id:04d}" / "result.json"))
            if trial_id == 0:
                item = None
            elif trial_id in (1, 2):
                item = v2_runner._picked(state["queue"], trial_id,
                                         trial_id - 1, config)
            else:
                item = campaign.pick_next(state["queue"], trial_id,
                                          trial_id - 1, config)
            if item is not None:
                require(item["faults"] == result["plan"],
                        f"replay selected a different r{trial_id:04d} plan")
                picks.append({"trial_id": trial_id,
                              "signature": sequence_signature(item["faults"]),
                              "selection_reason": item["selection_reason"]})
            if trial_id == 4 and sanitize_last:
                result = _sanitized_invalid(result)
            state["next_trial"] = trial_id + 1
            (Path(scratch) / "trials" / f"r{trial_id:04d}").mkdir(parents=True)
            campaign._apply_result(state, config, result, item)
        return state, picks


def _source_door(item: dict) -> dict:
    queued_at = item.get("queued_at")
    require(isinstance(queued_at, int) and queued_at >= 2,
            "untraceable queue parent")
    point = item["faults"][-1]["point"]
    candidates = [row for row in seed.events(SOURCE / "trials" /
                  f"r{queued_at:04d}") if row.get("type") == "DOOR_OBSERVED" and
                  all(row.get(key) == point.get(key) for key in
                      ("site", "node", "epoch", "door_ordinal"))]
    require(len(candidates) == 1, "queue point lacks a unique source door")
    return candidates[0]


def qualify_candidate(item: dict) -> dict:
    item = copy.deepcopy(item)
    require(len(item["faults"]) == 3 and
            [fault.get("expected_door") for fault in item["faults"][:2]] ==
            ["second", "retry"], "remaining candidate has a different prefix")
    door = _source_door(item)
    point = item["faults"][-1]["point"]
    source_feedback = read(SOURCE / "trials" /
                           f"r{item['queued_at']:04d}" / "result.json")["feedback"]
    feedback_doors = [row for row in source_feedback["doors"]
                      if row.get("point") == point and
                      row.get("event_seq") == door["seq"]]
    require(len(feedback_doors) == 1, "queue point lacks a unique graph door")
    in_closure = feedback_doors[0].get("in_closure") is True
    reason = item["selection_reason"]
    require((reason == "dynamic_closure" and in_closure) or
            (reason == "bounded_exploration" and not in_closure),
            "queue tier differs from source graph feedback")
    require(door.get("occurrence") and door.get("node") == point.get("node") and
            door.get("epoch") == point.get("epoch"), "source actor incomplete")
    if point["site"] == seed.NATIVE:
        resource = door.get("resource")
        require(isinstance(resource, str) and resource.startswith("/"),
                "native third fault lacks an observed path")
        second = seed.second_lookup(SOURCE / "trials" /
                                    f"r{item['queued_at']:04d}")
        if seed.same_execution(door, second):
            point = {"site": point["site"], "node": point["node"],
                     "epoch": point["epoch"], "solr15_parent_lookup": "after_pair"}
            if resource == second["resource"]:
                point["resource_role"] = "bound_parent"
            else:
                point["resource"] = resource
        else:
            point = {**point, "occurrence": door["occurrence"],
                     "solr15_parent_lookup": "explicit_resource",
                     "resource": resource}
        item["scope_tier"] = "dynamic_closure" if in_closure else "outside_closure"
    else:
        point = {**point, "occurrence": door["occurrence"]}
        item["scope_tier"] = "outside_closure"
    item["faults"][-1]["point"] = point
    item["source_door_id"] = door["id"]
    item["source_resource"] = door.get("resource")
    item["source_graph_rationale"] = {
        "source_trial": item["queued_at"], "source_door_id": door["id"],
        "source_feedback_event_seq": feedback_doors[0]["event_seq"],
        "source_feedback_in_closure": in_closure,
        "selection_reason": reason}
    item["signature"] = sequence_signature(item["faults"])
    return item


def reconstruct(config: dict) -> tuple[dict, dict]:
    verify_source()
    v2_config = read(SOURCE / "config.json")
    exact, picks = _replay(v2_config, sanitize_last=False)
    saved = read(SOURCE / "checkpoint.json")
    excluded = {"queue", "status", "out", "created_at", "updated_at", "config_digest"}
    require(all(exact.get(key) == value for key, value in saved.items()
                if key not in excluded), "v2 checkpoint replay diverged")
    require(exact["status"] == "running" and len(exact["queue"]) == 10 and
            saved["status"] == "fault_resource_mismatch" and saved["queue"] == [] and
            [row["trial_id"] for row in picks] == [1, 2, 3, 4],
            "v2 terminal transition differs")
    clean, clean_picks = _replay(v2_config, sanitize_last=True)
    require(picks == clean_picks and clean["completed_trials"] == [0, 1, 2, 3, 4]
            and clean["elapsed_seconds"] == saved["elapsed_seconds"] and
            clean["target_exception_candidates"] == [2, 3] and
            clean["reproduced_candidates"] ==
            [{"first_trial": 2, "replay_trial": 3}],
            "sanitized replay altered trial budget or valid findings")
    require(len(clean["edge_fingerprints"]) < len(exact["edge_fingerprints"]),
            "invalid trial edge novelty was not removed")
    queue = [qualify_candidate(item) for item in clean["queue"]]
    require(len(queue) == 10 and len({item["signature"] for item in queue}) == 10 and
            all(len(item["faults"]) == 3 for item in queue) and
            not any(item["signature"] in
                    {picks[1]["signature"], picks[2]["signature"]}
                    for item in queue), "qualified queue duplicates a valid pair")
    clean["queue"] = queue
    clean["seen_sequences"] = sorted(set(clean["seen_sequences"]) |
                                     {item["signature"] for item in queue})
    clean["out"] = str(OUT)
    clean["config_digest"] = digest(config)
    clean["created_at"] = saved["created_at"]
    clean["updated_at"] = saved["updated_at"]
    clean["status"] = "running"
    clean["running"] = None
    clean["dropped_trials"] = [{"trial_id": 4, "reason":
                                "unmatched third fault; no target or novelty credit",
                                "original_result_sha256": sha(SOURCE / "trials/r0004/result.json")}]
    clean["continuation"] = {"source_checkpoint_sha256": sha(SOURCE / "checkpoint.json"),
                             "source_summary_sha256": sha(SOURCE / "result.json"),
                             "source_output": str(SOURCE),
                             "replayed_picks": picks,
                             "retained_prior_trials": [0, 1, 2, 3, 4]}
    require(clean["next_trial"] == 5 and clean["bootstrap_fault_trials"] == 2 and
            clean["target_binding_trial"] == 2,
            "continuation would repeat or rebind a prior trial")
    receipt = {"case_id": "SOLR-15", "variant": "fault-bootstrap-node0-v3",
               "source_checkpoint_sha256": sha(SOURCE / "checkpoint.json"),
               "source_summary_sha256": sha(SOURCE / "result.json"),
               "replayed_picks": picks, "completed_trials": clean["completed_trials"],
               "next_trial": clean["next_trial"], "elapsed_seconds": clean["elapsed_seconds"],
               "remaining_queue": len(queue),
               "qualified_queue": [{"signature": item["signature"],
                                    "source_door_id": item["source_door_id"],
                                    "source_graph_rationale": item["source_graph_rationale"],
                                    "scope_tier": item["scope_tier"],
                                    "point": item["faults"][-1]["point"]}
                                   for item in queue],
               "invalid_trial_edge_fingerprints_removed":
                   len(exact["edge_fingerprints"]) - len(clean["edge_fingerprints"]),
               "valid_candidate_trials": [2, 3], "dropped_prior_trials": [4]}
    return clean, receipt


def prepare(config: dict) -> dict:
    state, receipt = reconstruct(config)
    source_receipt = read(HERE / "source-receipt.json")
    if OUT.exists():
        existing = read(OUT / "checkpoint.json")
        require(existing.get("continuation") == state["continuation"] and
                existing.get("config_digest") == state["config_digest"] and
                existing.get("completed_trials", [])[:5] == [0, 1, 2, 3, 4] and
                existing.get("next_trial", 0) >= 5 and
                read(OUT / "seed-receipt.json") == receipt,
                "existing v3 output is not this sealed continuation")
        for name, expected in source_receipt["files"].items():
            if name.startswith("trials/"):
                require(sha(OUT / name) == expected,
                        "existing v3 prior evidence changed: " + name)
        return receipt
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".solr15-v3-seed-", dir=OUT.parent))
    try:
        (stage / "trials").mkdir()
        for trial_id in range(5):
            shutil.copytree(SOURCE / "trials" / f"r{trial_id:04d}",
                            stage / "trials" / f"r{trial_id:04d}")
        campaign.atomic_json(stage / "config.json", config)
        campaign.atomic_json(stage / "checkpoint.json", state)
        campaign.atomic_json(stage / "seed-receipt.json", receipt)
        for name, expected in source_receipt["files"].items():
            if name.startswith("trials/"):
                require(sha(stage / name) == expected,
                        "copied prior evidence changed: " + name)
        require(not OUT.exists(), "v3 output appeared during seeding")
        os.rename(stage, OUT)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return receipt
