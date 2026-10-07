#!/usr/bin/env python3
"""Union production JaCoCo from healthy seeds and archived V3 trials."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    healthy = [EVIDENCE / name / "jacoco.exec" for name in ("v3-seed-a", "v3-seed-b")]
    for path in healthy:
        assert path.is_file()
    selected = []
    guard_events = 0
    missing_guard_events = 0
    with tempfile.TemporaryDirectory(prefix="solr19-coverage-") as tmp:
        temporary = Path(tmp)
        for manifest_path in args.manifests:
            receipt = json.loads(manifest_path.read_text())
            archive = manifest_path.parent / receipt["archive"]
            assert hashlib.sha256(archive.read_bytes()).hexdigest() == receipt["archive_sha256"]
            with tarfile.open(archive, "r:gz") as tar:
                prefixes = sorted({name.rsplit("/", 1)[0] for name in tar.getnames()
                                   if re.fullmatch(r"(?:v3-campaign/)?r\d{3}/trial\.json", name)})
                assert prefixes, f"no completed trials in {archive}"
                for prefix in prefixes:
                    number = int(prefix.rsplit("r", 1)[1])
                    trial = json.load(tar.extractfile(f"{prefix}/trial.json"))
                    assert trial["number"] == number
                    with tar.extractfile(f"{prefix}/actor-events.tsv") as trace:
                        for line in trace:
                            cells = line.rstrip(b"\n").split(b"\t")
                            if len(cells) > 10 and cells[3] == b"TARGET_GUARD":
                                guard_events += 1
                                missing_guard_events += cells[10] == b"missing"
                    raw = tar.extractfile(f"{prefix}/jacoco.exec").read()
                    path = temporary / f"r{number:03d}.exec"
                    if path.exists():
                        raise AssertionError(f"duplicate trial {prefix}")
                    path.write_bytes(raw)
                    selected.append((path, trial["effective"], receipt["archive"], prefix))

        def summarize(paths: list[Path]) -> dict:
            command = [sys.executable, str(HERE / "coverage_v2.py"),
                       *map(str, healthy + paths)]
            data = json.loads(subprocess.check_output(command, text=True))
            data["exec_files"] = [f"healthy/{name}" for name in ("v3-seed-a", "v3-seed-b")]
            data["exec_files"] += [f"{archive}/{prefix}/jacoco.exec" for path, _, archive, prefix
                                   in selected if path in set(paths)]
            return data

        all_result = summarize([path for path, *_ in selected])
        effective_result = summarize([path for path, effective, *_ in selected if effective])
    out = {"original_junit": "AddReplicaTest.testAddMultipleReplicas",
           "source_commit": "e27f44e", "attempts": len(selected),
           "effective": sum(effective for _, effective, _, _ in selected),
           "raw_target_guard_events": guard_events,
           "raw_missing_target_guard_events": missing_guard_events,
           "all_trials_with_healthy": all_result,
           "effective_trials_with_healthy": effective_result}
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"attempts": out["attempts"], "effective": out["effective"],
                      "raw_target_guard_events": guard_events,
                      "raw_missing_target_guard_events": missing_guard_events,
                      "all_methods": all_result["covered_methods"],
                      "all_branches": all_result["covered_branches"],
                      "effective_methods": effective_result["covered_methods"],
                      "effective_branches": effective_result["covered_branches"],
                      "selected_guard_branches_all": all_result["selected_create_branches_covered"],
                      "selected_guard_branches_effective": effective_result["selected_create_branches_covered"]}))


if __name__ == "__main__":
    main()
