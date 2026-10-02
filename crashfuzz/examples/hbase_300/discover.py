"""Run one fault-free HBase 3.0.0 workload to measure candidate reachability."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from adhoc_crashfuzz.campaign import Campaign, Settings  # noqa: E402
from adhoc_crashfuzz.graph import read_events  # noqa: E402
from adhoc_crashfuzz.model import FaultSequence  # noqa: E402


def main() -> None:
    properties = HERE / "out_selection/agent_discovery.properties"
    if not properties.is_file():
        raise RuntimeError("run select_candidates.py first")
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
    settings = replace(Settings.from_file(HERE / "campaign.json"),
                       output_dir=HERE / "out_discovery")
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    trial = Campaign(settings)._trial(FaultSequence(), "discovery")
    names = list(settings.backend.containers.values())
    subprocess.run(settings.backend.docker_command +
                   ["stop", "-t", "15"] + names,
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    trace = settings.output_dir / "runs" / trial.run_id / "traces"
    events = read_events(trace)
    completion = (settings.output_dir / "runs" / trial.run_id /
                  "hbase-client.exit").stat()
    workload_end_ms = int(completion.st_mtime * 1000)
    observed = [e for e in events if e.wall_ms <= workload_end_ms]
    summary = {"run_id": trial.run_id, "workload_returncode": trial.workload.returncode,
               "checker_returncode": None if trial.checker is None
               else trial.checker.returncode,
               "events": len(observed),
               "workload_end_ms": workload_end_ms,
               "entered_methods": len({e.site for e in observed
                                       if e.kind == "METHOD_ENTER"}),
               "trace_dir": str(trace)}
    (settings.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    if trial.workload.returncode or (trial.checker and trial.checker.returncode):
        raise SystemExit("discovery workload failed; inspect the saved run")


if __name__ == "__main__":
    main()
