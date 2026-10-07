#!/usr/bin/env python3
"""Audit the 104-check unit-test campaign table against case records.

This checks bookkeeping and minimum evidence fields. It does not decide
whether an observed exception is a new bug; that requires the case's replay
and source review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import checklist


HERE = Path(__file__).resolve().parent
TERMINAL = checklist.TERMINAL
KNOWN_ISSUES = {
    "HDFS-54": "known_HDFS-17897_reproduced",
    "HDFS-55": "known_HDFS-17899_reproduced",
}


def audit(require_terminal: bool) -> list[str]:
    errors: list[str] = []
    selected = json.loads((HERE / "selection102.json").read_text())
    selection = selected["checks"] + selected["additional_known_issue_checks"]
    ids = [entry["case_id"] for entry in selection]
    if len(ids) != 104 or len(set(ids)) != 104:
        errors.append("selection must contain 104 distinct checks")

    table = json.loads((HERE / "checklist102.json").read_text())
    table_rows = table.get("rows", [])
    if table.get("count") != 104 or len(table_rows) != 104:
        errors.append("rendered checklist must contain 104 rows")
    actual = {row["case_id"]: row for row in table_rows}
    if len(actual) != len(table_rows) or set(actual) != set(ids):
        errors.append("rendered checklist IDs differ from the selection")

    expected = {entry["case_id"]: entry for entry in selection}
    for case_id in ids:
        path = HERE / "cases" / case_id / "result.json"
        if not path.is_file():
            errors.append(f"{case_id}: result.json missing")
            continue
        result = json.loads(path.read_text())
        row = actual.get(case_id)
        if row is None:
            continue
        if result.get("case_id") != case_id:
            errors.append(f"{case_id}: result case_id mismatch")
        if row.get("status") != result.get("status"):
            errors.append(f"{case_id}: table status differs from result")
        if row.get("bug_mark") != result.get("bug_mark", "none"):
            errors.append(f"{case_id}: table bug mark differs from result")
        for field in ("source_path", "source_line", "site_id", "function"):
            if row.get(field) != expected[case_id].get(field):
                errors.append(f"{case_id}: selected {field} changed in table")

        status = result.get("status")
        if require_terminal and status not in TERMINAL:
            errors.append(f"{case_id}: unfinished status {status}")
        if status == "quality_complete":
            duration = result.get("elapsed_seconds")
            trials = row.get("fault_trials")
            applied = row.get("fully_applied_trials")
            reached = row.get("target_after_fault")
            if not isinstance(duration, (int, float)) or duration <= 0:
                errors.append(f"{case_id}: completed check has no measured time")
            for name, value in (("fault trials", trials),
                                ("fully applied trials", applied),
                                ("postfault target reaches", reached)):
                if not isinstance(value, int) or value <= 0:
                    errors.append(f"{case_id}: completed check has no {name}")
            if (isinstance(trials, int) and isinstance(applied, int)
                    and applied > trials):
                errors.append(f"{case_id}: applied trials exceed fault trials")
            if (isinstance(applied, int) and isinstance(reached, int)
                    and reached > applied):
                errors.append(f"{case_id}: postfault reaches exceed applied trials")
        if case_id in KNOWN_ISSUES:
            if (status != "quality_complete" or
                    result.get("bug_mark") != KNOWN_ISSUES[case_id] or
                    result.get("known_bug") is not True or
                    result.get("new_bug") is not False):
                errors.append(f"{case_id}: known-issue result is not classified")
        if result.get("new_bug") is True and result.get("bug_mark") in (None, "none"):
            errors.append(f"{case_id}: new-bug claim lacks a bug mark")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-terminal", action="store_true")
    args = parser.parse_args()
    errors = audit(args.require_terminal)
    for error in errors:
        print("ERROR:", error)
    print(f"audited 104 checks; errors={len(errors)}; require_terminal={args.require_terminal}")
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
