#!/usr/bin/env python3
"""Run immutable HBASE-32 v1 inputs with the v2 host-aware preflight."""

import argparse
import json
import sys
from pathlib import Path

from preflight import CORE, PACKAGE, preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy", "full"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    preflight(args.mode)
    sys.path.insert(0, str(CORE))
    from Mallory.core import campaign
    state = campaign.run(PACKAGE / f"config-{args.mode}.json", args.out,
                         calibration_only=(args.mode == "healthy"))
    print(json.dumps({key: state.get(key) for key in (
        "case_id", "status", "completed_trials", "elapsed_seconds",
        "runtime_attestation", "target_binding", "target_exception_candidates")},
        sort_keys=True))
    return 0 if state["status"] not in {"healthy_seed_invalid",
                                            "healthy_bootstrap_attestation_failed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
