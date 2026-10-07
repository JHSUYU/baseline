#!/usr/bin/env python3
"""Rebuild untried V3 mutation plans after the sender-relative ordinal fix."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

import audit_seeds
import campaign_v3


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
ORIGIN = "mutated_from_observed_postfault_io"


def signature(plan):
    return json.dumps(plan["steps"], sort_keys=True)


def trial_rows(number, temporary):
    if number <= 2:
        archive = EVIDENCE / "v3-pilot-r001-r002.tar.gz"
        member = f"v3-campaign/r{number:03d}/actor-events.tsv"
    else:
        archive = EVIDENCE / "v3-pilot-r003-r008.tar.gz"
        member = f"r{number:03d}/actor-events.tsv"
    directory = temporary / f"r{number:03d}"
    directory.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        (directory / "actor-events.tsv").write_bytes(tar.extractfile(member).read())
    return audit_seeds.read(directory)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    before = args.state.read_bytes()
    state = json.loads(before)
    if state["inflight"] is not None or len(state["attempts"]) != 8:
        raise ValueError("repair must run on the complete r008 pilot boundary")
    if sum(trial["effective"] for trial in state["attempts"]) != 5:
        raise ValueError("unexpected effective count at r008")
    old_queue = state["queue"]
    retained = [plan for plan in old_queue if plan["origin"] != ORIGIN]
    old_children = [plan for plan in old_queue if plan["origin"] == ORIGIN]
    known = set(state["seen_plans"]) | {signature(plan) for plan in retained}
    queue = retained
    derived = []
    with tempfile.TemporaryDirectory(prefix="solr19_queue_v3_") as dirname:
        temporary = Path(dirname)
        for trial in state["attempts"]:
            if not trial["effective"]:
                continue
            events = trial_rows(trial["number"], temporary)
            applied = [event for event in events if event["phase"] == "FAULT_APPLIED_CONNECTION_LOSS"]
            if len(applied) != len(trial["plan"]["steps"]):
                raise ValueError(f"r{trial['number']:03d} no longer matches its saved plan")
            last_seq = int(applied[-1]["seq"])
            novel = bool(trial["new_production_probes"] or trial["new_stable_io_families"])
            children = campaign_v3.new_children(events, trial["plan"]["steps"], last_seq,
                                                 known, novel, state["budget"]["max_ordered_faults"])
            queue = children + queue
            derived.append({"parent_trial": trial["number"], "children": len(children),
                            "selectors": [child["steps"][-1]["selector"] for child in children]})
    signatures = [signature(plan) for plan in queue]
    if len(signatures) != len(set(signatures)) or set(signatures) & set(state["seen_plans"]):
        raise ValueError("repaired queue has duplicates or already attempted plans")
    state["queue"] = queue
    receipt = {"case_id": "SOLR-19", "complete_boundary_trial": 8,
               "prior_state_sha256": hashlib.sha256(before).hexdigest(),
               "old_queue_count": len(old_queue), "old_mutation_children": len(old_children),
               "retained_nonmutation_queue": len(retained),
               "new_queue_count": len(queue),
               "new_mutation_children": len(queue) - len(retained),
               "removed_old_child_signatures": sorted(set(map(signature, old_children)) - set(signatures)),
               "added_corrected_child_signatures": sorted(set(signatures) - set(map(signature, old_queue))),
               "derived": derived,
               "attempts_unchanged": len(state["attempts"]),
               "seen_plans_unchanged": len(state["seen_plans"]),
               "reason": "child occurrence ordinal now counts from same-core CREATE sender before filtering postfault I/O; generated qn IDs are not new exact-path children"}
    state["queue_repair"] = {"complete_boundary_trial": 8,
                             "receipt": args.receipt.name,
                             "prior_state_sha256": receipt["prior_state_sha256"]}
    output = json.dumps(state, indent=2, sort_keys=True).encode() + b"\n"
    receipt["repaired_state_sha256"] = hashlib.sha256(output).hexdigest()
    args.output.write_bytes(output)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in ("old_queue_count", "old_mutation_children",
                                                    "new_queue_count", "new_mutation_children",
                                                    "attempts_unchanged")}))


if __name__ == "__main__":
    main()
