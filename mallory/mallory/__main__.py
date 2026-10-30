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

    sweep = sub.add_parser("sweep", help="ground truth: every single fault of a healthy run once")
    sweep.add_argument("case")
    sweep.add_argument("--node", default=settings.NODES[0])
    sweep.add_argument("--limit", type=int)
    sweep.add_argument("--reverse", action="store_true",
                       help="from the last point, beside a forward sweep of the same case")

    replay = sub.add_parser("replay", help="a campaign's detecting plan run again, N times")
    replay.add_argument("case")
    replay.add_argument("--seed", type=int, default=0)
    replay.add_argument("--repeats", type=int, default=10)
    replay.add_argument("--node", default=settings.NODES[0])
    replay.add_argument("--generalize", action="store_true",
                        help="plant each fault at all its siblings in the detecting run")

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
    elif args.command == "sweep":
        print(json.dumps(campaign.Sweep(engine.Case.resolve(args.case), campaign.Budget(),
                                        args.node).sweep(args.limit, args.reverse), indent=2))
    elif args.command == "replay":
        replaying = campaign.Replay(engine.Case.resolve(args.case), campaign.Budget(), args.node,
                                    seed=args.seed)
        replaying.generalize = args.generalize
        print(json.dumps(replaying.replay(args.repeats), indent=2))
    else:
        rows = []
        for path in sorted(args.work.glob("*/seed-*/result.json")):
            result = json.loads(path.read_text())
            detection = result.get("detection") or {}
            rows.append([result["case"], str(result.get("seed", "-")),
                         "yes" if result["detected"] else "no",
                         str(result["trials"]), str(result["elapsed_s"]),
                         str(detection.get("trial_index", "-")),
                         str(detection.get("seconds_from_start", "-")),
                         str(detection.get("seconds_with_prepare", "-")),
                         "; ".join(detection.get("faults", [])) or "-"])
        header = ["case", "seed", "detected", "trials", "seconds", "detecting trial",
                  "seconds to detect (trials)", "seconds to detect (with SEED/PLAN and healthy runs)",
                  "faults of the detecting run"]
        print("| " + " | ".join(header) + " |")
        print("|" + " --- |" * len(header))
        for row in rows:
            print("| " + " | ".join(row) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
