#!/usr/bin/env python3
"""Offline check of independent effective budgets and the last-eight gate."""

import json
from pathlib import Path
import tempfile

import campaign

from campaign import (BASE_ATTEMPTS, BASE_FAULTS, BASE_VALID_PER_SITE,
                      EXTENDED_ATTEMPTS, EXTENDED_FAULTS,
                      EXTENDED_VALID_PER_SITE, update_progress, valid_count)
from feedback import CASES


def state() -> dict:
    return {
        "budget": {"max_attempts": BASE_ATTEMPTS, "max_faults": BASE_FAULTS},
        "site_progress": {
            site: {"effective": 0, "goal": BASE_VALID_PER_SITE,
                   "extension": "pending", "last_eight_effective": []}
            for site in CASES},
    }


def trial(number: int, active: str, *, strict: bool = True,
          methods: int = 0, branches: int = 0, families: int = 0) -> dict:
    return {
        "number": number, "strict": strict,
        "target_after_fault": {site: site == active for site in CASES},
        "new_methods": {site: methods if site == active else 0 for site in CASES},
        "new_branches": {site: branches if site == active else 0 for site in CASES},
        "new_io_families": {site: families if site == active else 0 for site in CASES},
    }


def main() -> None:
    current = state()
    number = 0
    for count in range(79):
        number += 1
        update_progress(current, trial(number, "SOLR-10", methods=1 if count == 72 else 0))
    assert valid_count(current, "SOLR-10") == 79
    assert current["site_progress"]["SOLR-10"]["extension"] == "pending"
    number += 1
    update_progress(current, trial(number, "SOLR-10"))
    assert current["site_progress"]["SOLR-10"]["extension"] == "extended"
    assert current["site_progress"]["SOLR-10"]["goal"] == EXTENDED_VALID_PER_SITE
    assert current["budget"] == {"max_attempts": EXTENDED_ATTEMPTS,
                                 "max_faults": EXTENDED_FAULTS}
    assert current["site_progress"]["SOLR-39"]["effective"] == 0

    for _ in range(79):
        number += 1
        update_progress(current, trial(number, "SOLR-39"))
    number += 1
    update_progress(current, trial(number, "SOLR-39", strict=False, families=1))
    assert valid_count(current, "SOLR-39") == 79
    assert current["site_progress"]["SOLR-39"]["extension"] == "pending"
    number += 1
    update_progress(current, trial(number, "SOLR-39"))
    assert valid_count(current, "SOLR-39") == 80
    assert current["site_progress"]["SOLR-39"]["extension"] == "not_extended"
    assert current["site_progress"]["SOLR-39"]["goal"] == 80

    for count in range(80):
        number += 1
        update_progress(current, trial(number, "SOLR-40", branches=1 if count == 72 else 0))
    assert current["site_progress"]["SOLR-40"]["extension"] == "extended"
    assert len(current["site_progress"]["SOLR-40"]["last_eight_effective"]) == 8

    boundary = state()
    for count in range(80):
        update_progress(boundary, trial(count + 1, "SOLR-10", families=1 if count == 71 else 0))
    assert boundary["site_progress"]["SOLR-10"]["extension"] == "not_extended"
    assert boundary["budget"] == {"max_attempts": BASE_ATTEMPTS,
                                  "max_faults": BASE_FAULTS}
    boundary["trials"] = []
    boundary["queue"] = []
    boundary["inflight"] = None
    campaign.update_stop_reasons(boundary)
    assert boundary["site_progress"]["SOLR-10"]["stop_reason"] == "goal_met"
    assert boundary["site_progress"]["SOLR-39"]["stop_reason"] == "queue_exhausted_before_goal"
    boundary["trials"] = [{}] * BASE_ATTEMPTS
    boundary["queue"] = [["unrun-actor-selector"]]
    campaign.update_stop_reasons(boundary)
    assert boundary["site_progress"]["SOLR-39"]["stop_reason"] == "attempt_cap_before_goal"
    read_plan = "GET_DATA|/aliases.json|1|caller=org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process:2312|actor=jetty:node1"
    writer_plan = "SET_DATA|/aliases.json|1|caller=org.apache.solr.common.cloud.ZkStateReader$AliasesManager#applyModificationAndExportToZk:2259|actor=alias-writer"
    schedule = state()
    schedule["trials"] = [{}] * 5  # next trial is divisible by three
    schedule["queue"] = [[writer_plan], [read_plan]]
    schedule["seed_target_sites"] = {read_plan: ["SOLR-39"]}
    assert campaign.pick(schedule) == [read_plan]
    assert schedule["queue"] == [[writer_plan]]
    retries = state()
    retries["queue"] = []
    retries["seed_target_sites"] = {read_plan: ["SOLR-39"]}
    retries["reader_retry_counts"] = {}
    mismatch = {"plan": [read_plan], "strict": True,
                "target_after_fault_any_actor": {"SOLR-39": True},
                "target_after_fault": {"SOLR-39": False}}
    assert campaign.schedule_reader_retry(retries, mismatch)
    assert retries["queue"].pop() == [read_plan]
    assert campaign.schedule_reader_retry(retries, mismatch)
    assert retries["queue"].pop() == [read_plan]
    assert not campaign.schedule_reader_retry(retries, mismatch)
    original_directory = campaign.CAMPAIGN
    with tempfile.TemporaryDirectory(prefix="solr103940-v2-budget-smoke-") as temp:
        try:
            campaign.CAMPAIGN = Path(temp)
            campaign.write_checkpoints(boundary)
            for site in CASES:
                checkpoint = json.loads((Path(temp) / "checkpoints" / f"{site}.json").read_text())
                assert checkpoint["case_id"] == site
                assert checkpoint["effective"] == boundary["site_progress"][site]["effective"]
        finally:
            campaign.CAMPAIGN = original_directory
    print("SOLR103940_V2_BUDGET_SMOKE_PASS")


if __name__ == "__main__":
    main()
