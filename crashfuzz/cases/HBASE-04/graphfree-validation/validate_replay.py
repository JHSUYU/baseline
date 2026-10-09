#!/usr/bin/env python3
"""Gate a fresh campaign on the independent representative JUnit replays."""

from pathlib import Path
import json


BASE = Path(__file__).resolve().parent
EXPECTED = {
    "healthy": 0,
    "read_io_0": 1,
    "read_timeout_0": 1,
    "read_io_1": 1,
    "read_retry_pair": 2,
}


def main() -> None:
    cases = {}
    for name, expected_faults in EXPECTED.items():
        log = BASE / (name + ".log")
        exit_file = BASE / (name + ".exit")
        if not log.exists() or not exit_file.exists():
            raise RuntimeError("missing independent replay evidence for " + name)
        lines = log.read_text(errors="replace").splitlines()
        applies = [index for index, line in enumerate(lines)
                   if line.startswith("HBASE04 META_READ ") and "applied=true" in line]
        checks = [index for index, line in enumerate(lines)
                  if line.startswith("HBASE04 CHECK ")]
        entries = [line for line in lines if line.startswith("HBASE04 TARGET_ENTER ")]
        exits = [line for line in lines if line.startswith("HBASE04 TARGET_EXIT ")]
        junit_pass = any("JUNIT found=1 succeeded=1 failed=0" in line for line in lines)
        after_fault = not applies or checks and max(checks) > max(applies)
        cases[name] = {
            "exit_code": int(exit_file.read_text().strip()),
            "target_entries": len(entries), "target_exits": len(exits),
            "target_checks": len(checks), "applied_faults": len(applies),
            "target_after_fault": bool(after_fault),
            "junit_pass": junit_pass,
            "target_exception": any("TableNotEnabledException" in line for line in exits),
            "expected_faults": expected_faults,
        }
    ready = all(
        row["exit_code"] == 0 and row["target_entries"] == 4
        and row["target_exits"] == 4 and row["target_checks"] == 4
        and row["applied_faults"] == row["expected_faults"]
        and row["target_after_fault"] and row["junit_pass"]
        for row in cases.values())
    result = {"ready_for_new_campaign": ready,
              "source": "case-local ByteBuddy/JaCoCo on original HBase JUnit, no GraphChecker skeleton",
              "cases": cases}
    (BASE / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if not ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
