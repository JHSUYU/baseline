"""Opt-in, bounded priority for exact pretarget plans with retained parents.

This module only selects an already queued plan. It never constructs a fault,
changes a plan key, promotes a MAY edge into closure, or changes the oracle.
"""

from collections import Counter
from typing import Any, Callable

POLICY = "retained_parent_pretarget_two_of_sixteen_v1"
SLOTS = frozenset((9, 14))


def choose(state: dict[str, Any], *, plan_key: Callable[..., str],
           fault_id: Callable[[dict[str, Any]], str],
           depth_limit: int) -> dict[str, Any] | None:
    if state.get("retained_parent_pretarget_priority") != POLICY:
        return None
    if state["completed_fault_trials"] % 16 not in SLOTS:
        return None
    anchors = set(state.get("multi_anchor_addresses", ()))
    eligible = []
    for item in state["queue"]:
        faults = item.get("faults")
        anchor = item.get("anchor_address")
        feedback = item.get("depth_feedback")
        if (not isinstance(faults, list) or not 2 <= len(faults) <= depth_limit or
                anchor not in anchors or item.get("tier") != "observed_closure" or
                item.get("target_phase") != "before_selected_target" or
                not isinstance(feedback, dict) or
                feedback.get("strict_post_fault_target") is not True or
                feedback.get("observed_pre_target_phase") is not True or
                not isinstance(feedback.get("score"), int) or
                isinstance(feedback["score"], bool) or
                item.get("key") != plan_key(faults, anchor)):
            continue
        eligible.append(item)
    if not eligible:
        return None
    # A parent with recorded target-directed feedback gets this scarce slot
    # first. If none exists, retain the exact parent-retained admission gate.
    productive = [item for item in eligible if
                  item["depth_feedback"]["score"] >= 2]
    if productive:
        eligible = productive
    family_sizes = Counter(plan_key(item["faults"][:-1], item["anchor_address"])
                           for item in eligible)
    retained_per_anchor = Counter(trial.get("anchor_address")
                                  for trial in state.get("trials", ())
                                  if trial.get("strict_injection") is True and
                                  trial.get("post_fault_target_check_observed") is True)

    def score(item: dict[str, Any]) -> tuple[Any, ...]:
        parent = plan_key(item["faults"][:-1], item["anchor_address"])
        fault = item["faults"][-1]
        return (item["depth_feedback"]["score"],
                -retained_per_anchor[item["anchor_address"]],
                -family_sizes[parent],
                item.get("peer_relation") == "same_peer_before_target",
                -state.get("fault_id_attempts", {}).get(fault_id(fault), 0),
                -len(item["faults"]),
                item.get("novelty", 0), -item.get("attempt", 0), item["key"])

    return max(eligible, key=score)
