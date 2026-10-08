#!/usr/bin/env python3
"""Audit the 104-check unit-test campaign table against case records.

This checks bookkeeping and minimum evidence fields. It does not decide
whether an observed exception is a new bug; that requires the case's replay
and source review.
"""

from __future__ import annotations

import argparse
import json
import re
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
    check_starts = json.loads((HERE / "check_locations.json").read_text())[
        "check_start_lines"]
    if set(check_starts) != set(ids):
        errors.append("check location catalog differs from the selection")
    markdown_lines = (HERE / "checklist102.md").read_text().splitlines()
    markdown_rows = {}
    for line in markdown_lines:
        match = re.match(r"^\| ([A-Z]+-\d+) \|", line)
        if match:
            markdown_rows[match.group(1)] = line
    if len(markdown_rows) != 104 or set(markdown_rows) != set(ids):
        errors.append("Markdown checklist must contain all 104 check rows")
    if "| Check location |" not in "\n".join(markdown_lines[:30]):
        errors.append("Markdown checklist lacks the check location column")
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
        start_line = check_starts.get(case_id)
        expected_location = {
            "file": expected[case_id]["source_path"],
            "check_start_line": start_line,
            "selected_line": expected[case_id]["source_line"],
            "enclosing_function": expected[case_id]["function"],
            "site_id": expected[case_id]["site_id"],
        }
        if (not isinstance(start_line, int) or isinstance(start_line, bool) or
                not 0 < start_line <= expected[case_id]["source_line"] or
                row.get("exact_check_location") != expected_location):
            errors.append(f"{case_id}: exact check location is missing or invalid")
        markdown_row = markdown_rows.get(case_id, "")
        if (f"{expected[case_id]['source_path']}:{start_line}" not in markdown_row or
                expected[case_id]["function"] not in markdown_row):
            errors.append(f"{case_id}: Markdown row lacks its exact source location")
        total_time = row.get("total_elapsed_seconds")
        case_time = row.get("elapsed_seconds")
        if isinstance(total_time, (int, float)) and total_time > 0:
            reported_time, time_scope = total_time, "total elapsed"
        elif isinstance(case_time, (int, float)) and case_time > 0:
            reported_time, time_scope = case_time, "case reported"
        else:
            reported_time, time_scope = None, "unrecorded"
        if (row.get("reported_time_seconds") != reported_time or
                row.get("reported_time_scope") != time_scope):
            errors.append(f"{case_id}: reported time differs from the case record")
        if (reported_time is None and "unrecorded" not in markdown_row) or (
                reported_time is not None and
                f"{reported_time}<br>{time_scope}" not in markdown_row):
            errors.append(f"{case_id}: Markdown row lacks its reported time")

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
            if (result.get("bug_mark") != KNOWN_ISSUES[case_id] or
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
