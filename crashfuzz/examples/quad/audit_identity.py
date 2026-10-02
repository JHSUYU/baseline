"""Verify recorded fault matches against each trial's controller journal."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
CAMPAIGNS = {
    "hdfs": ROOT / "hdfs_random10/out_coverage10",
    "hdfs_replay02": ROOT / "hdfs_random10/out_replay02_epoch",
    "hbase": ROOT / "hbase_266/out_campaign",
    "hbase_shape": ROOT / "hbase_266/out_campaign_shape",
    "zookeeper": ROOT / "zookeeper_387/out_campaign",
    "solr": ROOT / "solr_8114/out_campaign",
}


def shape(context: str) -> str:
    return re.sub(r"#\d+(?=/|$)", "#*", context)


def audit(root: Path) -> dict:
    faults = full = partial = 0
    replays = full_replays = partial_replays = 0
    modes: Counter[str] = Counter()
    errors: list[str] = []
    paths = (list(root.glob("*/runs/*/result.json"))
             + list(root.glob("runs/*/result.json")))
    for path in sorted(paths):
        result = json.loads(path.read_text())
        hits = result.get("target_hits", [])
        if bool(hits) != bool(result["target_reached"]):
            errors.append(str(path) + ": target hit identities disagree with reachability")
        if result["target_fatal"] and not hits:
            errors.append(str(path) + ": fatal target has no runtime identity")
        for hit in hits:
            if not all(key in hit for key in
                       ("node", "epoch", "site", "context", "process", "span")):
                errors.append(str(path) + ": incomplete target runtime identity")
        planned = result["sequence"]["actions"]
        if not planned:
            continue
        is_fault_trial = result["run_id"].startswith("run-")
        if is_fault_trial:
            faults += 1
        else:
            replays += 1
        injected = result["injected"]
        if is_fault_trial and len(injected) == len(planned) and result["triggered"]:
            full += 1
        elif not is_fault_trial and len(injected) == len(planned) and result["triggered"]:
            full_replays += 1
        elif is_fault_trial and injected:
            partial += 1
        elif not is_fault_trial and injected:
            partial_replays += 1
        if bool(result["triggered"]) != (len(injected) == len(planned)
                                         and not result["controller_error"]):
            errors.append(str(path) + ": triggered disagrees with action count")
        journal_path = path.with_name("point-events.jsonl")
        journal = ([json.loads(line) for line in
                    journal_path.read_text().splitlines()]
                   if journal_path.exists() else [])
        for index, item in enumerate(injected):
            mode = item["match_mode"]
            modes[mode] += 1
            action = item["action"]
            point = item["observed_point"]
            epoch = item["observed_epoch"]
            order = item["order"]
            label = str(path) + ": action " + str(index + 1)
            if action != planned[index]:
                errors.append(label + " differs from planned action")
            if order >= len(journal):
                errors.append(label + " missing controller journal row")
                continue
            record = journal[order]
            if (record["order"] != order or not record["matched"]
                    or record["match_mode"] != mode
                    or record["point"] != point
                    or record["epoch"] != epoch):
                errors.append(label + " disagrees with controller journal")
            trigger = action["trigger"]
            same_epoch = epoch == action["trigger_epoch"]
            if mode == "exact":
                if not same_epoch or point != trigger:
                    errors.append(label + " violates exact runtime identity")
            elif mode == "shape_occurrence":
                if (not same_epoch
                        or record["site_occurrence"]
                        != action["site_occurrence"]
                        or any(point[key] != trigger[key] for key in
                               ("node", "site", "ordinal", "phase"))
                        or shape(point["context"])
                        != shape(trigger["context"])):
                    errors.append(label + " violates shape occurrence identity")
            else:
                errors.append(label + " has unknown match mode " + mode)
    return {"fault_trials": faults, "replay_trials": replays,
            "full_replays": full_replays,
            "partial_replays": partial_replays,
            "full_matches": full,
            "partial_matches": partial, "injected_action_modes": dict(modes),
            "errors": errors}


def main() -> None:
    result = {name: audit(root) for name, root in CAMPAIGNS.items()}
    path = Path(__file__).resolve().parent / "identity_audit.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({name: {key: value for key, value in row.items()
                             if key != "errors"}
                      for name, row in result.items()}, indent=2, sort_keys=True))
    failures = {name: row["errors"] for name, row in result.items()
                if row["errors"]}
    if failures:
        raise SystemExit(json.dumps(failures, indent=2))


if __name__ == "__main__":
    main()
