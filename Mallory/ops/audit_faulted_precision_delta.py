#!/usr/bin/env python3
"""Apply the frozen historical faulted-path audit to an explicit case cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from Mallory.ops.audit_faulted_precision import review_case, sha


FROZEN_AUDIT_SHA256 = "03f1938c9d5ead0a1a1f290504b4130c03440d6fb8e892b5200e8e98d409064d"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cases", nargs="+", required=True)
    args = parser.parse_args()
    if len(set(args.cases)) != len(args.cases):
        raise ValueError("duplicate case ID")
    repo = args.repo.resolve()
    frozen_source = repo / "Mallory/ops/audit_faulted_precision.py"
    if sha(frozen_source) != FROZEN_AUDIT_SHA256:
        raise ValueError("historical audit implementation differs from pinned SHA")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for case_id in args.cases:
        if not (case_id.startswith("HBASE-") or case_id.startswith("HDFS-") or
                case_id.startswith("SOLR-") or case_id.startswith("ZOOKEEPER-")):
            raise ValueError(f"invalid case ID: {case_id}")
        review = review_case(repo / "data/mallory/cases" / case_id)
        path = out / f"{case_id}.json"
        path.write_text(json.dumps(review, sort_keys=True, indent=2) + "\n")
        rows.append({"case_id": case_id,
                     "classification": review["classification"],
                     "recommended_quality_status": review["recommended_quality_status"],
                     "strict_target_trials": review["strict_target_trials"],
                     "same_region_continuation_trials": review[
                         "same_region_continuation_trials"],
                     "same_actor_named_thread_order_trials": review[
                         "same_actor_named_thread_order_trials"],
                     "ordered_root_free_region_path_trials": review[
                         "ordered_root_free_region_path_trials"],
                     "root_free_occurrence_path_trials": review[
                         "root_free_occurrence_path_trials"],
                     "canonical_result_sha256": review["canonical_result_sha256"],
                     "canonical_audit_sha256": review["canonical_audit_sha256"],
                     "review_sha256": sha(path)})
        print(case_id, review["classification"],
              review["same_region_continuation_trials"],
              review["ordered_root_free_region_path_trials"], flush=True)
    index = {"schema_version": 1,
             "analysis_kind": "explicit_legacy_faulted_run_precision_read_only",
             "cohort": args.cases,
             "frozen_audit_source_sha256": FROZEN_AUDIT_SHA256,
             "wrapper_source_sha256": sha(Path(__file__)),
             "rows": rows}
    (out / "index.json").write_text(json.dumps(index, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
