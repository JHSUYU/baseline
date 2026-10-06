#!/usr/bin/env python3
"""Exercise the command-line campaign, including checkpoint resume.

The fixture uses the plan and trace row shapes emitted by the integrated
GraphChecker unit-test-core JAR.  It intentionally avoids starting a system
cluster, so this checks the generic driver protocol only.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from test_fuzzer import (FAKE_RUNNER, OCC_TARGET, SITE, TARGET,
                         seed_files, trial_config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    trace, plan = seed_files(root)
    runner = root / "fixture_trial.py"
    runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                      "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                      FAKE_RUNNER)
    config = trial_config(root, trace, plan, runner)
    config["target"]["occurrence"] = OCC_TARGET
    config_file = root / "case.json"
    config_file.write_text(json.dumps(config, indent=2) + "\n")
    command = [sys.executable, str(Path(__file__).with_name("fuzzer.py")),
               str(config_file), "--root", str(root / "cases")]
    first = subprocess.run(command, text=True, capture_output=True, check=True)
    second = subprocess.run(command, text=True, capture_output=True, check=True)
    first_summary = json.loads(first.stdout)
    second_summary = json.loads(second.stdout)
    result_file = root / "cases" / "CHECK-01" / "result.json"
    result = json.loads(result_file.read_text())
    if (first_summary["trials"] != 1 or second_summary["trials"] != 1 or
            result["strict_injections"] != 1 or
            result["oracle_candidates"] != 1 or
            result["status"] != "candidate_review"):
        raise RuntimeError("synthetic campaign or checkpoint resume failed")
    print(json.dumps({"config": str(config_file),
                      "result": str(result_file),
                      "first": first_summary,
                      "resume": second_summary,
                      "case_status": result["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
