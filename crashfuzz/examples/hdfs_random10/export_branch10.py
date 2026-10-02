"""Export exact target-closure branch outcomes for the completed ten checks."""

from __future__ import annotations

import json
from pathlib import Path

from adhoc_crashfuzz.graph import build_graph, read_events, target_closure
from adhoc_crashfuzz.model import TargetSpec


HERE = Path(__file__).resolve().parent
ROOT = HERE / "out_coverage10"


def main() -> None:
    progress = json.loads((ROOT / "progress.json").read_text())
    output = {"selection_sha256": progress["selection_sha256"], "rows": []}
    for draw in range(1, 11):
        name = "candidate-{:02d}".format(draw)
        detail = progress["targets"][name]
        if detail["status"] != "complete":
            raise RuntimeError(name + " is not complete")
        roles = json.loads((HERE / detail["campaign"]).read_text())["roles"]
        target = TargetSpec(detail["target_guard"])
        seen: set[str] = set()
        runs = []
        paths = list((ROOT / name / "runs").glob("*/result.json"))
        paths.sort(key=lambda path: (
            not path.parent.name.startswith("seed-"), path.parent.name))
        for path in paths:
            result = json.loads(path.read_text())
            start = result["workload_start_wall_ms"]
            end = result["workload_end_wall_ms"]
            events = [event for event in read_events(path.parent / "traces")
                      if not event.wall_ms or start <= event.wall_ms <= end]
            closure = target_closure(build_graph(events), target, roles)
            features = set(closure.branch_features)
            if (len(features) != result["closure_branch_outcomes"]
                    or closure.reached != result["target_reached"]
                    or closure.fatal != result["target_fatal"]):
                raise RuntimeError("closure mismatch in " + str(path))
            accepted = (result["run_id"].startswith("seed-")
                        or bool(result["triggered"]))
            new = features - seen if accepted else set()
            if accepted:
                feedback = json.loads((path.parent / "feedback.json").read_text())
                if len(new) != feedback["new_closure_branch_outcomes"]:
                    raise RuntimeError("branch feedback mismatch in " + str(path))
                seen.update(features)
            runs.append({
                "run_id": result["run_id"],
                "matched": bool(result["triggered"]),
                "target_reached": closure.reached,
                "branch_features": sorted(features),
                "new_branch_features": sorted(new),
            })
        output["rows"].append({
            "draw": draw, "guard": detail["target_guard"],
            "runs": runs,
        })
    path = HERE / "branches10.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
