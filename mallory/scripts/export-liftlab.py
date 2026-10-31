#!/usr/bin/env python3
"""export-liftlab.py <work> <data> <label>=<dir> ...: a Mallory work directory's records into the repository's data/.

For each <label> (a MALLORY_WORK, e.g. run-a) and each case under it, data/<dir>/<case>/ receives what the README's
tables are read from: result.json and prepared.json, trials.json (every trial of the campaign), the detecting run's
plant (detecting.plant.jsonl and detecting.plant-outside.jsonl, the input of `run_engine.sh plant-run`), its
GraphChecker trace (detecting.trace.jsonl.gz: the evidence of the detection, with the target's PLANT_FATAL rows), and
the replays (replay.json, replay-generalized.json). The other runs' traces and logs stay in the work directory.
"""
import json
import shutil
import sys
from pathlib import Path

work, data = Path(sys.argv[1]), Path(sys.argv[2])
for spec in sys.argv[3:]:
    label, directory = spec.split("=", 1)
    for case in sorted((work / label).iterdir()):
        seed = case / "seed-0"
        if not (seed / "result.json").is_file():
            continue
        out = data / directory / case.name
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy(seed / "result.json", out / "result.json")
        if (case / "prepared.json").is_file():
            shutil.copy(case / "prepared.json", out / "prepared.json")
        state = json.loads((seed / "state.json").read_text())
        (out / "trials.json").write_text(json.dumps(
            {key: state.get(key) for key in ("case", "seed", "healthy_fatal_arms", "healthy_noise_edges",
                                             "prepare_s", "healthy_s", "elapsed_s", "trials")},
            indent=1) + "\n")
        detection = json.loads((seed / "result.json").read_text()).get("detection")
        if detection:
            for suffix in (".plant.jsonl", ".plant-outside.jsonl"):
                plant = seed / "runs" / (detection["trial"] + suffix)
                if plant.is_file():
                    shutil.copy(plant, out / ("detecting" + suffix))
            trace = seed / "runs" / detection["trial"] / "runtime_trace.jsonl.gz"
            if trace.is_file():
                shutil.copy(trace, out / "detecting.trace.jsonl.gz")
        for replay in ("replay", "replay-generalized"):
            record = seed / replay / "replay.json"
            if record.is_file():
                shutil.copy(record, out / (replay + ".json"))
        print(out)
