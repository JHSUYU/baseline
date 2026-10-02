"""Command-line entry points for graph inspection and cluster fuzzing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .campaign import Campaign, Settings
from .graph import build_graph, read_events, target_closure
from .model import TargetSpec


def main() -> None:
    parser = argparse.ArgumentParser(prog="adhoc-crashfuzz")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="fuzz a configured cluster")
    run.add_argument("--config", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="inspect a native event trace")
    inspect.add_argument("--trace-dir", type=Path, required=True)
    inspect.add_argument("--target-site", required=True)
    arguments = parser.parse_args()
    if arguments.command == "run":
        answer = Campaign(Settings.from_file(arguments.config)).run()
    else:
        graph = build_graph(read_events(arguments.trace_dir))
        closure = target_closure(graph, TargetSpec(arguments.target_site))
        answer = {"graph_nodes": len(graph.nodes),
                  "graph_edges": len(graph.edges),
                  "closure_nodes": len(closure.nodes),
                  "closure_edges": len(closure.edges),
                  "target_reached": closure.reached,
                  "target_fatal": closure.fatal,
                  "fault_points_in_closure": len(closure.points),
                  "gaps": graph.gaps[:50]}
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
