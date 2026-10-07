#!/usr/bin/env python3
"""Offline SOLR-05 80/128 effective-trial and 8/10 fault budget check."""

import json
from pathlib import Path
import tempfile

import campaign
from campaign import (BASE_ATTEMPTS, BASE_FAULTS, BASE_VALID_PER_SITE,
                      EXTENDED_ATTEMPTS, EXTENDED_FAULTS,
                      EXTENDED_VALID_PER_SITE, update_progress, valid_count)

SITE = "SOLR-05"


def state() -> dict:
    return {
        "budget": {"max_attempts": BASE_ATTEMPTS, "max_faults": BASE_FAULTS},
        "site_progress": {SITE: {"effective": 0, "goal": BASE_VALID_PER_SITE,
                                 "extension": "pending", "last_eight_effective": []}},
    }


def trial(number: int, *, strict: bool = True, target: bool = True,
          methods: int = 0, branches: int = 0, families: int = 0) -> dict:
    return {"number": number, "strict": strict,
            "target_after_fault": {SITE: target},
            "new_methods": {SITE: methods}, "new_branches": {SITE: branches},
            "new_io_families": {SITE: families}}


def main() -> None:
    assert (BASE_ATTEMPTS, BASE_VALID_PER_SITE, BASE_FAULTS) == (240, 80, 8)
    assert (EXTENDED_ATTEMPTS, EXTENDED_VALID_PER_SITE, EXTENDED_FAULTS) == (384, 128, 10)
    current = state()
    for number in range(1, 80):
        update_progress(current, trial(number, methods=1 if number == 73 else 0))
    assert valid_count(current, SITE) == 79
    update_progress(current, trial(80, strict=False, methods=1))
    update_progress(current, trial(81, target=False, branches=1))
    assert valid_count(current, SITE) == 79
    update_progress(current, trial(82))
    assert current["site_progress"][SITE]["extension"] == "extended"
    assert current["site_progress"][SITE]["goal"] == 128
    assert current["budget"] == {"max_attempts": 384, "max_faults": 10}
    boundary = state()
    for number in range(1, 81):
        update_progress(boundary, trial(number, families=1 if number == 72 else 0))
    assert boundary["site_progress"][SITE]["extension"] == "not_extended"
    assert boundary["budget"] == {"max_attempts": 240, "max_faults": 8}
    boundary.update({"trials": [], "queue": [], "inflight": None})
    campaign.update_stop_reasons(boundary)
    assert boundary["site_progress"][SITE]["stop_reason"] == "goal_met"
    incomplete = state()
    incomplete.update({"trials": [{}] * 240, "queue": [["unrun-selector"]], "inflight": None})
    campaign.update_stop_reasons(incomplete)
    assert incomplete["site_progress"][SITE]["stop_reason"] == "attempt_cap_before_goal"
    old = campaign.CAMPAIGN
    with tempfile.TemporaryDirectory(prefix="solr05-v2-budget-smoke-") as temp:
        try:
            campaign.CAMPAIGN = Path(temp)
            campaign.write_checkpoints(incomplete)
            checkpoint = json.loads((Path(temp) / "checkpoints/SOLR-05.json").read_text())
            assert checkpoint["effective"] == 0 and checkpoint["max_attempts"] == 240
        finally:
            campaign.CAMPAIGN = old
    print("SOLR05_V2_BUDGET_SMOKE_PASS")


if __name__ == "__main__":
    main()
