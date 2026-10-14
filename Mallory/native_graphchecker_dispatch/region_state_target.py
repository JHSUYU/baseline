"""Bind a region-state campaign to a recorded, exact GraphChecker check.

Concolic task addresses append an occurrence number to a branch site.  A
REGION_STATE trace records the branch's static site ID instead.  The original
GraphChecker scope must also identify the selected throw and its fatal arm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path


SITE = re.compile(r"^<[^:]+: .+>#u[0-9]+$")


def healthy_reached_nonfatal(occurrence: dict) -> bool:
    """Validate the observed arm, not the polarity of the fatal arm.

    GraphChecker records ``fatalOutcome`` from the selected throw's static
    guard.  The resolver records only healthy executions of the other arm in
    ``reachedEvents``.  Either Boolean value can denote the fatal arm.
    """
    fatal = occurrence.get("fatalOutcome")
    events = occurrence.get("reachedEvents")
    count = occurrence.get("reachedEventCount")
    return (type(fatal) is bool and type(count) is int and count > 0
            and isinstance(events, list) and len(events) == count
            and all(isinstance(event, dict)
                    and type(event.get("observedOutcome")) is bool
                    and event["observedOutcome"] is not fatal
                    for event in events))


def healthy_without_target_throw(events: Iterable[dict]) -> bool:
    """The fault hook must not report a target throw in a healthy run."""
    return not any(event.get("kind") == "TARGET_THROW" for event in events)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(config: dict, occurrence: dict, scope_rows: list[dict]) -> dict:
    """Return a copy with an exact check ID, or refuse missing evidence."""
    if config.get("runner", {}).get("mode") != "region_state":
        raise ValueError("target binding requires REGION_STATE mode")
    check = occurrence.get("checkSiteId")
    throw = config.get("target_throw", {}).get("siteId")
    if (occurrence.get("kind") != "MALLORY_OBSERVED_TARGET_OCCURRENCE"
            or not isinstance(check, str) or not SITE.fullmatch(check)
            or not isinstance(throw, str) or not SITE.fullmatch(throw)):
        raise ValueError("missing exact observed check or selected throw")
    junit = config.get("junit", {})
    if occurrence.get("test") != junit.get("class", "") + "#" + junit.get("method", ""):
        raise ValueError("observed check belongs to another original JUnit")
    if config.get("target_site") not in (check,) and not re.fullmatch(
            re.escape(check) + r"#[1-9][0-9]*", str(config.get("target_site", ""))):
        raise ValueError("concolic anchor does not name the observed check")
    target_rows = [row for row in scope_rows
                   if row.get("kind") == "STATIC_SCOPE_SITE"
                   and row.get("role") == "TARGET_SITE"
                   and row.get("siteId") == throw]
    if len(target_rows) != 1:
        raise ValueError("selected throw has no unique original target row")
    row = target_rows[0]
    guards = row.get("guards", [])
    outcomes = row.get("guardOutcomes", [])
    if len(guards) != len(outcomes) or guards.count(check) != 1:
        raise ValueError("original scope lacks a unique fatal check arm")
    arm = outcomes[guards.index(check)]
    if not isinstance(arm, bool) or arm != occurrence.get("fatalOutcome"):
        raise ValueError("observed fatal arm differs from original static scope")
    if row.get("regionId") != occurrence.get("targetRegionId"):
        raise ValueError("observed target region differs from original scope")
    bound = json.loads(json.dumps(config))
    bound["target_site"] = check
    return bound


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--occurrence", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite an immutable case config")
    config = json.loads(args.config.read_text())
    occurrence = json.loads(args.occurrence.read_text())
    with args.scope.open() as source:
        rows = [json.loads(line) for line in source]
    bound = bind(config, occurrence, rows)
    args.output.write_text(json.dumps(bound, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"config_sha256": _sha(args.output),
                      "occurrence_sha256": _sha(args.occurrence),
                      "original_scope_sha256": _sha(args.scope),
                      "target_site": bound["target_site"]}, sort_keys=True))


if __name__ == "__main__":
    main()
