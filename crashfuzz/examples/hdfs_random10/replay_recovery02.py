"""Replay the archived HDFS draw-2 recovery sequence with current identity."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import FaultSequence, TargetSpec

from analyze_checks import guard_sites
from run_batch import agent_properties


HERE = Path(__file__).resolve().parent


def confirmed_replay(path: Path) -> bool:
    row = json.loads(path.read_text())
    return (row["triggered"] and row["target_reached"]
            and not row["target_fatal"]
            and len(row["injected"]) == len(row["sequence"]["actions"])
            and all(item["match_mode"] == "exact" for item in row["injected"])
            and row["workload"]["returncode"] == 0
            and not row["workload"]["timed_out"]
            and row["checker"] is not None
            and row["checker"]["returncode"] == 0
            and not row["checker"]["timed_out"])


def main() -> None:
    site = json.loads((HERE / "mapped10.json").read_text())["sites"][1]
    guard = guard_sites(site)[-1]
    out = HERE / "out_replay02_epoch"
    out.mkdir(exist_ok=True)
    config = out / "agent.properties"
    config.write_text(agent_properties(site).replace(
        "target.guard=\n", "target.guard=" + guard + "\n").replace(
        "target.entry=" + site["agent_method"] + "\n", "target.entry=\n"))
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(config.resolve())
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
    })
    settings = replace(Settings.from_file(HERE / "campaign_special.json"),
                       target=TargetSpec(guard), output_dir=out)
    campaign = Campaign(settings)
    sequence_bytes = (HERE / "recovery_sequence02.json").read_bytes()
    sequence = FaultSequence.from_dict(json.loads(sequence_bytes))
    runs = out / "runs"
    existing = list(runs.glob("*/result.json"))
    campaign._trial_number = max((int(path.parent.name.rsplit("-", 1)[1])
                                  for path in existing), default=0)
    if not existing:
        campaign._trial(FaultSequence(), "seed")
    seed_result = json.loads((runs / "seed-00001/result.json").read_text())
    if (seed_result["workload"]["returncode"]
            or seed_result["workload"]["timed_out"]
            or seed_result["checker"] is None
            or seed_result["checker"]["returncode"]
            or seed_result["checker"]["timed_out"]
            or seed_result["target_fatal"]):
        raise RuntimeError("recovery replay requires a passing healthy seed")
    while True:
        replay_paths = list(runs.glob("replay-*/result.json"))
        confirmed = sum(confirmed_replay(path) for path in replay_paths)
        if confirmed >= 2 or len(replay_paths) >= 5:
            break
        campaign._trial(sequence, "replay")
    rows = []
    for path in sorted(runs.glob("*/result.json"),
                       key=lambda item: int(item.parent.name.rsplit("-", 1)[1])):
        result = json.loads(path.read_text())
        rows.append({
            "run_id": result["run_id"],
            "planned_actions": len(result["sequence"]["actions"]),
            "injected_actions": len(result["injected"]),
            "triggered": result["triggered"],
            "match_modes": [item["match_mode"] for item in result["injected"]],
            "target_reached": result["target_reached"],
            "target_fatal": result["target_fatal"],
            "workload_returncode": result["workload"]["returncode"],
            "checker_returncode": (None if result["checker"] is None else
                                   result["checker"]["returncode"]),
        })
    report = {"source": "archived pre-epoch draw 2 run-00003",
              "sequence_sha256": hashlib.sha256(sequence_bytes).hexdigest(),
              "site_id": site["site_id"], "target_guard": guard,
              "runs": rows}
    (HERE / "recovery_replay02.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
