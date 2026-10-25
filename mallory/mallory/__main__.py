"""Mallory baseline: ``python3 -m mallory {prepare,run,report} ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import campaign, engine, settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mallory", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="GraphChecker's SEED and PLAN of a case")
    prepare.add_argument("case")
    prepare.add_argument("--node", default=settings.NODES[0])

    run = sub.add_parser("run", help="one Mallory campaign over a case")
    run.add_argument("case")
    run.add_argument("--trials", type=int, default=campaign.Budget.trials)
    run.add_argument("--seconds", type=int, default=campaign.Budget.seconds)
    run.add_argument("--max-faults", type=int, default=campaign.Budget.max_faults)
    run.add_argument("--trial-bound", type=int, default=campaign.Budget.trial_bound_s)
    run.add_argument("--node", default=settings.NODES[0],
                     help="the node every trial of this campaign runs on")
    run.add_argument("--continue-after-detection", action="store_true")
    run.add_argument("--seed", type=int, default=0)

    report = sub.add_parser("report", help="every case's result under the work directory")
    report.add_argument("--work", type=Path, default=settings.WORK)

    args = parser.parse_args(argv)
    if args.command == "prepare":
        print(json.dumps(engine.prepare(engine.Case.resolve(args.case), args.node), indent=2))
    elif args.command == "run":
        budget = campaign.Budget(trials=args.trials, seconds=args.seconds,
                                 max_faults=args.max_faults, trial_bound_s=args.trial_bound,
                                 stop_at_detection=not args.continue_after_detection)
        result = campaign.Campaign(engine.Case.resolve(args.case), budget, args.node,
                                   seed=args.seed).run()
        print(json.dumps(result, indent=2))
    else:
        rows = []
        for path in sorted(args.work.glob("*/result.json")):
            result = json.loads(path.read_text())
            detection = result.get("detection") or {}
            rows.append([result["case"], "yes" if result["detected"] else "no",
                         str(result["trials"]), str(result["elapsed_s"]),
                         str(detection.get("trial_index", "-")),
                         str(detection.get("seconds_from_start", "-")),
                         "; ".join(detection.get("faults", [])) or "-"])
        header = ["case", "detected", "trials", "seconds", "detecting trial", "seconds to detect",
                  "faults of the detecting run"]
        print("| " + " | ".join(header) + " |")
        print("|" + " --- |" * len(header))
        for row in rows:
            print("| " + " | ".join(row) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
