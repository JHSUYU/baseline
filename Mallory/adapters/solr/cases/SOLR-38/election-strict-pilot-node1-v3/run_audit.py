#!/usr/bin/env python3
"""Recompute a terminal SOLR-38 v3 campaign with its exact graph overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import graph_overlay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    graph_overlay.install()
    from Mallory.core import audit
    audit.OccurrenceGraph = graph_overlay.SourceBackedSolr38Graph
    result = audit.audit_campaign(args.campaign, args.out)
    print(json.dumps({"case_id": result["case_id"],
                      "trial_count": result["trial_count"],
                      "healthy_closure_proven": result["healthy_closure_proven"],
                      "report_gate_passed": result["report_gate_passed"]},
                     sort_keys=True))
    return 0 if result["report_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
