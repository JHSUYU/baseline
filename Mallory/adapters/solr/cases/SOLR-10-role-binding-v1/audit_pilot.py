#!/usr/bin/env python3
"""Attest physical role match and target continuation for one bounded pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prepare_pilot import TARGET, events_from
from role_plan import attest_applied


def audit(plan: dict, events: list[dict]) -> dict:
    receipt = attest_applied(plan, events)
    applied = next(index for index, event in enumerate(events)
                   if event.get("type") == "FAULT_APPLIED"
                   and event.get("fault_id") == receipt["fault_id"])
    later = events[applied + 1:]
    checks = [event for event in later
              if event.get("type") == "TARGET_CHECK" and event.get("site") == TARGET]
    throws = [event for event in later
              if event.get("type") == "TARGET_THROW"
              and event.get("site", "").startswith(TARGET.split("@", 1)[0])]
    receipt.update({"status": "applied_target_continued" if checks else "target_lost",
                    "postfault_target_checks": len(checks),
                    "postfault_target_throws": len(throws),
                    "first_postfault_target_check_id": checks[0].get("id") if checks else None})
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = audit(json.loads(args.plan.read_text()), events_from(args.events))
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
