"""Check whether RAM_DISK and local reads cover the two missing methods."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.graph import read_events
from adhoc_crashfuzz.model import FaultSequence

from discover import TRANSPORT_METHODS


HERE = Path(__file__).resolve().parent


def main() -> None:
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
    })
    sites = json.loads((HERE / "mapped10.json").read_text())["sites"][:2]
    methods = ({site["agent_method"].split("(", 1)[0] for site in sites}
               | TRANSPORT_METHODS)
    classes = {method.split("#", 1)[0] for method in methods}
    properties = HERE / "agent-discovery-special.properties"
    properties.write_text("\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "point.entries=", "trace.fields=false", "trace.branches=false",
        "target.guard=", "target.throw=", "adapter.hdfs.datatransfer=true",
        "adapter.hadoop.rpc=true", "",
    ]))
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
    settings = Settings.from_file(HERE / "campaign_special.json")
    output = HERE / "out_discovery_special"
    trial = Campaign(replace(settings, output_dir=output))._trial(
        FaultSequence(), "discovery")
    events = read_events(output / "runs" / trial.run_id / "traces")
    entered = {event.site for event in events if event.kind == "METHOD_ENTER"}
    throws = {event.site for event in events if event.kind == "THROW"}
    report = {
        "run_id": trial.run_id,
        "workload_returncode": trial.workload.returncode,
        "checker_returncode": (None if trial.checker is None
                               else trial.checker.returncode),
        "rows": [{
            "draw": site["draw"],
            "site_id": site["site_id"],
            "method_entered": site["agent_method"] in entered,
            "source_line_throw_observed": site["compiled_target_throw"] in throws,
        } for site in sites],
    }
    (output / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
