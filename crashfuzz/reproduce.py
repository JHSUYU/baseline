#!/usr/bin/env python3
"""Inspect or invoke the recorded graph-free cluster-test campaign for one check."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
ENTRYPOINTS = HERE / "entrypoints.json"
TERMINAL_WITHOUT_REPRO = {"no_cluster_test", "no_usable_cluster_test", "source_excluded"}


def entries() -> dict[str, dict]:
    return json.loads(ENTRYPOINTS.read_text())


def command(case_id: str, entry: dict, output: Path) -> list[str] | None:
    runner = entry.get("runner")
    if runner is None:
        return None
    return [sys.executable, str(HERE / runner),
            *(argument.replace("{output}", str(output))
              for argument in entry.get("args", []))]


def validate(case_id: str, entry: dict) -> list[str]:
    errors = []
    case_dir = HERE / "cases" / case_id
    result = case_dir / "result.json"
    script = case_dir / "reproduce.sh"
    if not result.is_file():
        errors.append(f"{case_id}: missing result.json")
    elif json.loads(result.read_text()).get("status") != entry["status"]:
        errors.append(f"{case_id}: result status differs from entrypoint")
    if not script.is_file():
        errors.append(f"{case_id}: missing reproduce.sh")
    elif not os.access(script, os.X_OK):
        errors.append(f"{case_id}: reproduce.sh is not executable")
    if entry["status"] == "quality_complete":
        if not entry.get("runner") or not (HERE / entry["runner"]).is_file():
            errors.append(f"{case_id}: missing campaign runner")
        if not entry.get("cluster_test"):
            errors.append(f"{case_id}: missing original cluster test")
        for source in entry.get("instrumentation_sources", []):
            if not (HERE / source).is_file():
                errors.append(f"{case_id}: missing instrumentation source {source}")
    elif entry["status"] not in TERMINAL_WITHOUT_REPRO:
        errors.append(f"{case_id}: unexpected status {entry['status']}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", nargs="?", help="one of the 104 check IDs")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--run", action="store_true", help="invoke the original case campaign")
    actions.add_argument("--check", action="store_true", help="validate one entrypoint")
    actions.add_argument("--check-all", action="store_true", help="validate all 104 entrypoints")
    parser.add_argument("--output", type=Path, default=HERE / "reproductions",
                        help="fresh output root for runners that support --output")
    args = parser.parse_args()
    mapping = entries()
    if args.check_all:
        selected = json.loads((DATA / "selection102.json").read_text())
        ids = {r["case_id"] for r in selected["checks"]}
        ids.update(r["case_id"] for r in selected["additional_known_issue_checks"])
        errors = [message for case_id, entry in mapping.items()
                  for message in validate(case_id, entry)]
        if set(mapping) != ids or len(mapping) != 104:
            errors.append("entrypoints do not match the 104 selected checks")
        table = json.loads((DATA / "checklist102.json").read_text())
        table_rows = {row["case_id"]: row for row in table["rows"]}
        if set(table_rows) != ids:
            errors.append("final results do not match the selected checks")
        for case_id, entry in mapping.items():
            row = table_rows.get(case_id)
            if row is None:
                continue
            if entry["status"] != row["status"]:
                errors.append(f"{case_id}: entrypoint status differs from final result")
            if (entry["source_path"] != row["source_path"] or
                    entry["source_line"] != row["exact_check_location"]["check_start_line"]):
                errors.append(f"{case_id}: entrypoint targets a different source check")
        for error in errors:
            print("ERROR:", error)
        print(f"checked {len(mapping)} entrypoints; errors={len(errors)}")
        raise SystemExit(bool(errors))
    if not args.case_id or args.case_id not in mapping:
        parser.error("supply a selected case ID, or use --check-all")
    entry = mapping[args.case_id]
    errors = validate(args.case_id, entry)
    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        raise SystemExit(2)
    if args.check:
        print(f"{args.case_id}: entrypoint valid ({entry['status']})")
        return
    cmd = command(args.case_id, entry, args.output.resolve())
    if not args.run:
        print(json.dumps({"case_id": args.case_id, **entry,
                          "command": cmd, "output_root": str(args.output.resolve())},
                         indent=2, sort_keys=True))
        return
    if cmd is None:
        print(f"{args.case_id}: {entry['status']}; no usable original cluster-test "
              "fault campaign is available. See its result.json for the screening reason.",
              file=sys.stderr)
        raise SystemExit(3)
    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CRASHFUZZ_CASE_ID"] = args.case_id
    environment["CRASHFUZZ_OUTPUT_ROOT"] = str(args.output.resolve())
    print("Running:", " ".join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd, cwd=(HERE / entry["runner"]).parent,
                                     env=environment))


if __name__ == "__main__":
    main()
