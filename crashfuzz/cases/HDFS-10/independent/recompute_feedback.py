#!/usr/bin/env python3
"""Remove per-run Mockito mock probes and rebuild feedback from saved trials."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import campaign


def clean_probes(path: Path) -> None:
    if not path.is_file():
        return
    kept = [line for line in path.read_text().splitlines()
            if "$MockitoMock$" not in line]
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as output:
        output.write("\n".join(kept) + "\n")
        temporary = Path(output.name)
    temporary.replace(path)
    manifest_path = path.parent / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        manifest["covered_probes_count"] = len(kept)
        campaign.atomic_json(manifest_path, manifest)


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if state.get("coverage_revision") == "exclude_dynamic_mocks_v1":
        raise SystemExit("Already recomputed")
    for path in campaign.EVIDENCE.rglob("covered_probes.txt"):
        clean_probes(path)
    coverage = {name: campaign.covered(campaign.HEALTHY, name)
                for name in ("probes", "methods", "branch_counts", "lines")}
    for trial in state["completed"].values():
        run = Path(trial["manifest"]).parent
        per_run = {name: campaign.covered(run, name) for name in coverage}
        trial["coverage_total"] = {name: len(values) for name, values in per_run.items()}
        if trial["valid_for_feedback"]:
            trial["coverage_gain"] = {name: len(values - coverage[name])
                                      for name, values in per_run.items()}
            for name, values in per_run.items():
                coverage[name] |= values
        else:
            trial["coverage_gain"] = {name: 0 for name in coverage}
    state["coverage"] = {name: sorted(values) for name, values in coverage.items()}
    state["coverage_revision"] = "exclude_dynamic_mocks_v1"
    campaign.atomic_json(campaign.STATE, state)
    campaign.update_result(state)
    print(json.dumps({"completed": len(state["completed"]),
                      "production_probe_union": len(coverage["probes"]),
                      "recent_novelty": [trial["coverage_gain"] for trial in
                                         list(state["completed"].values())[-8:]]}))


if __name__ == "__main__":
    main()
