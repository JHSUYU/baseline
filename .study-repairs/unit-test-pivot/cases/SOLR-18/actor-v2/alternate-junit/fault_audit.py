#!/usr/bin/env python3
"""Strict ordered-fault and same-live-client audit for the alternate phase."""
from __future__ import annotations

from pathlib import Path

from audit import actor, audit, parse


def selector(row: tuple[int, str, str, list[str]]) -> str:
    return row[3][0] + '@@' + row[3][1]


def check(path: Path, plan: list[str]) -> dict:
    assert plan and len(plan) == len(set(plan))
    rows = parse(path)
    target = audit(path)
    matched = [row for row in rows if row[1] == 'FAULT_MATCHED']
    applied = [row for row in rows if row[1] == 'FAULT_APPLIED']
    actual_matched = [selector(row) for row in matched if len(row[3]) >= 4]
    actual_applied = [selector(row) for row in applied if len(row[3]) >= 4]
    strict = bool(len(matched) == len(applied) == len(plan)
                  and actual_matched == actual_applied == plan
                  and all(m[0] + 1 == a[0] for m, a in zip(matched, applied))
                  and all(m[3][2] == a[3][2] == str(i)
                          for i, (m, a) in enumerate(zip(matched, applied))))
    target_actor = target.get('target_actor') if target['selected_target'] else None
    all_bound = bool(strict and target_actor
                     and all(actor(row[3]) == target_actor for row in applied))
    postfinal = bool(target['selected_target'] and applied
                     and target['selected_target_sequence'] > applied[-1][0])
    target_outcome = target.get('target_outcome')
    return {'plan': plan, 'matched': actual_matched, 'applied': actual_applied,
            'matched_actor_ids': [actor(row[3]) for row in matched],
            'applied_actor_ids': [actor(row[3]) for row in applied],
            'strict_ordered_faults': strict,
            'selected_target': target['selected_target'],
            'selected_target_sequence': target.get('selected_target_sequence'),
            'first_api_apply_sequence': target.get('first_api_apply_sequence'),
            'next_same_manager_apply_sequence': target.get('next_same_manager_apply_sequence'),
            'target_actor': target_actor,
            'target_versions_cmp': target.get('target_versions_cmp'),
            'target_outcome': target_outcome,
            'target_json_equal': target.get('target_json_equal'),
            'all_faults_on_target_client': all_bound,
            'target_after_final_fault': postfinal,
            'effective': bool(strict and all_bound and postfinal
                              and target_outcome in ('TARGET_EQUAL_CHECK', 'TARGET_THROW')),
            'target_throw_count': sum(row[1] == 'TARGET_THROW' for row in rows),
            'same_actor_pretarget_roots': target.get('same_actor_pretarget_roots', [])}
