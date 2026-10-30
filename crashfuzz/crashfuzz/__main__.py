"""``python3 -m crashfuzz <command>`` (run from the crashfuzz/ directory).

  select   Soot-select one checklist case (no JUnit run)
  run      run (or resume) one checklist case end to end
  worker   run (or resume) a system's cases, optionally one shard of them
  cluster  start one worker per node over ssh
  replay   run one fault sequence N times on a case
  plan     write a trial's realized plan for replays (--siblings: at all its siblings)
  report   write the 102-check table of a results root
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

from . import cluster, report, settings
from .selection import select_case
from .faults import point_from_event, shape_ordinal_plan, sibling_plan
from .systems import SYSTEMS, system_of
from .worker import checklist_rows, replay_case, run_case


def _row(checklist: Path, case_id: str) -> dict:
    row = next((item for item in json.loads(checklist.read_text())["rows"]
                if item["case_id"] == case_id), None)
    if row is None:
        raise SystemExit(f"case not in the checklist: {case_id}")
    return row


def _selector(sequence: list[dict]) -> list[dict]:
    """A fault-trial.json lists the agent's form; the selector is the point."""
    return [{key: value for key, value in point.items()
             if key not in {"faultId", "value"} and
             not (key == "phase" and value == "before")} for point in sequence]


def write_plan(trial: Path, output: Path, siblings: bool = False) -> dict:
    """A trial's plan for replays: its realized faults (a partial candidate's prefix),
    each lost reply named by its shape ordinal in the trial's own run, and with
    ``siblings`` planted at all its siblings there (a replay aid)."""
    plan = _selector(json.loads((trial / "fault-trial.json").read_text())["faults"])
    realized = json.loads((trial / "result.json").read_text()).get("realized_fault_count")
    plan = plan[:realized or len(plan)]
    attempt = sorted(trial.glob("attempt-*"))[-1] / "trace"
    trace = next(path for path in (attempt / "runtime_trace.jsonl",
                                   attempt / "runtime_trace.jsonl.gz") if path.is_file())
    stream = gzip.open(trace, "rt") if trace.suffix == ".gz" else trace.open()
    observed = []
    with stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "FAULT_POINT_OBSERVED":
                point = point_from_event(event)
                if point is not None:
                    observed.append(point)
    written = shape_ordinal_plan(plan, observed)
    if siblings:
        written = sibling_plan(written, observed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(written, indent=1) + "\n")
    return {"trial": str(trial), "plan": len(plan), "written": len(written),
            "siblings": siblings, "output": str(output)}


def _print(result: dict) -> None:
    print(json.dumps({key: result.get(key) for key in
                      ("case_id", "status", "finished", "fault_trials", "strict_injections",
                       "total_elapsed_seconds", "first_candidate_trial",
                       "first_candidate_seconds", "error")}), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crashfuzz", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checklist", type=Path, default=settings.CHECKLIST)
    commands = parser.add_subparsers(dest="command", required=True)

    select = commands.add_parser("select")
    select.add_argument("--case-id", required=True)
    select.add_argument("--output", type=Path, required=True)

    def budget(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--results", type=Path, default=settings.RESULTS)
        sub.add_argument("--max-trials", type=int, default=240)
        sub.add_argument("--max-faults", type=int, default=10)
        sub.add_argument("--campaign-suffix", default="")
        sub.add_argument("--refresh-selection", action="store_true")
        sub.add_argument("--stop-at-candidate", action="store_true",
                         help="end the campaign at its first candidate (a time-to-detect run, "
                              "which spends its whole budget: --max-trials or --max-seconds)")
        sub.add_argument("--max-seconds", type=int,
                         help="a budget of JUnit seconds over the campaign's trials")

    run = commands.add_parser("run")
    run.add_argument("--case-id", required=True)
    budget(run)

    worker = commands.add_parser("worker")
    worker.add_argument("--system", choices=SYSTEMS, required=True)
    worker.add_argument("--case-id", action="append")
    worker.add_argument("--exclude-case", action="append", default=[])
    worker.add_argument("--include-added-checks", action="store_true",
                        help="also run the two separately listed known-issue checks")
    worker.add_argument("--shard-index", type=int, default=0)
    worker.add_argument("--shard-count", type=int, default=1)
    budget(worker)

    nodes = commands.add_parser("cluster")
    nodes.add_argument("--nodes", nargs="+", required=True)
    nodes.add_argument("--system", choices=SYSTEMS, required=True)
    nodes.add_argument("--results", type=Path, default=settings.RESULTS)
    nodes.add_argument("--dry-run", action="store_true")
    nodes.add_argument("worker_options", nargs=argparse.REMAINDER,
                       help="passed on to each worker after --")

    replay = commands.add_parser("replay")
    replay.add_argument("--case-id", required=True)
    replay.add_argument("--plan", type=Path, required=True,
                        help="JSON list of fault points, or a fault-trial.json")
    replay.add_argument("--repeats", type=int, default=10)
    replay.add_argument("--name", required=True, help="the replay directory's suffix")
    replay.add_argument("--results", type=Path, default=settings.RESULTS)

    plan_command = commands.add_parser("plan")
    plan_command.add_argument("--trial", type=Path, required=True,
                              help="a trial directory: its fault-trial.json, result.json and its "
                                   "last attempt's trace")
    plan_command.add_argument("--output", type=Path, required=True)
    plan_command.add_argument("--siblings", action="store_true",
                              help="plant each fault at all its siblings (a replay aid)")

    table = commands.add_parser("report")
    table.add_argument("--results", type=Path, default=settings.RESULTS)
    table.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if getattr(args, "campaign_suffix", "") and not re.fullmatch(r"[a-z0-9-]+",
                                                                 args.campaign_suffix):
        parser.error("campaign-suffix must use lowercase letters, digits, or hyphens")

    if args.command == "select":
        row = _row(args.checklist, args.case_id)
        location = row["exact_check_location"]
        selection = select_case(location["site_id"].split("#", 1)[0], location,
                                system_of(row["system"]).analysis(),
                                args.output / args.case_id)
        print(json.dumps({"case_id": args.case_id, "system": row["system"],
                          "selection": selection["artifact_path"],
                          "coverage_methods": len(selection["coverage_methods"]),
                          "io_calls": len(selection["io_calls"]),
                          "branches": len(selection["branches"])}), flush=True)
    elif args.command == "run":
        _print(run_case(_row(args.checklist, args.case_id), args.results, args.max_trials,
                        args.max_faults, args.campaign_suffix, args.refresh_selection,
                        args.stop_at_candidate, args.max_seconds))
    elif args.command == "worker":
        if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
            parser.error("shard-index must be in [0, shard-count)")
        rows = checklist_rows(args.checklist, args.system, args.include_added_checks)
        for index, row in enumerate(rows):
            if (index % args.shard_count != args.shard_index or
                    (args.case_id and row["case_id"] not in args.case_id) or
                    row["case_id"] in args.exclude_case):
                continue
            _print(run_case(row, args.results, args.max_trials, args.max_faults,
                            args.campaign_suffix, args.refresh_selection))
    elif args.command == "cluster":
        extra = [option for option in args.worker_options if option != "--"]
        for line in cluster.launch(args.nodes, args.system, args.results, extra, args.dry_run):
            print(line, flush=True)
    elif args.command == "replay":
        plan = json.loads(args.plan.read_text())
        sequence = _selector(plan["faults"] if isinstance(plan, dict) else plan)
        print(json.dumps(replay_case(_row(args.checklist, args.case_id), args.results,
                                     sequence, args.repeats, args.name)), flush=True)
    elif args.command == "plan":
        print(json.dumps(write_plan(args.trial, args.output, args.siblings)), flush=True)
    elif args.command == "report":
        rows = report.table(args.results, args.checklist)
        report.write_tsv(rows, args.output)
        print(json.dumps({"rows": len(rows),
                          "started": sum(row.get("status") != "pending" for row in rows),
                          "finished": sum(bool(row.get("finished")) for row in rows),
                          "output": str(args.output)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
