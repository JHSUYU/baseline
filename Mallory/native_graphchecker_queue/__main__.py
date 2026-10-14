"""Two-slot owner-host queue for original native GraphChecker campaigns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, _native_case_files,
    load_inventory, load_ownership,
)
from .queue import (MAX_SLOTS, _cached_terminal_inspection, atomic, completion,
                    obj, physical_host,
                    pilot_receipt, run_host, run_worker, sha,
                    validate_isolation)
from .results import export_native_results

DEFAULT_RESULTS_DIR = (Path(__file__).resolve().parents[2] /
                       "data/mallory/native_graphchecker_queue")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pilot", "run-host", "worker"))
    parser.add_argument("--host", choices=("node0", "node1", "node2"), required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--ownership", type=Path, default=DEFAULT_OWNERSHIP)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--isolation", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--slots", type=int, default=MAX_SLOTS)
    parser.add_argument("--slot", type=int, default=0)
    parser.add_argument("--case-id")
    parser.add_argument("--pilot-receipt", type=Path)
    parser.add_argument("--min-memory-gib", type=float, default=12)
    parser.add_argument("--min-state-gib", type=float, default=2)
    parser.add_argument("--min-scratch-gib", type=float, default=4)
    args = parser.parse_args()
    physical_host(args.host)
    if any(value < 0 for value in (args.min_memory_gib, args.min_state_gib,
                                   args.min_scratch_gib)):
        parser.error("resource floors must be nonnegative")
    if args.command == "run-host":
        if args.pilot_receipt is None or args.case_id:
            parser.error("run-host requires --pilot-receipt and no --case-id")
        codes = run_host(host=args.host, slots=args.slots,
                         pilot=args.pilot_receipt, inventory=args.inventory,
                         ownership_file=args.ownership,
                         config_root=args.config_root, state_root=args.state_root,
                         scratch_root=args.scratch_root,
                         results_dir=args.results_dir,
                         isolation_file=args.isolation, reviews=args.reviews,
                         min_memory_gib=args.min_memory_gib,
                         min_state_gib=args.min_state_gib,
                         min_scratch_gib=args.min_scratch_gib)
        print(json.dumps({"host": args.host, "worker_exit_codes": codes},
                         sort_keys=True))
        if any(code != 0 for code in codes):
            raise SystemExit(1)
        return
    cases, by_id = load_inventory(args.inventory)
    owners = load_ownership(args.ownership, set(by_id))
    if args.command == "pilot":
        if not args.case_id or args.pilot_receipt is None:
            parser.error("pilot requires --case-id and --pilot-receipt")
        item = next((item for item in cases if item["case_id"] == args.case_id), None)
        if item is None or owners[args.case_id] != args.host:
            raise ValueError("pilot case is not owned by this host")
        config_file, native_root = _native_case_files(item, args.config_root,
                                                       args.state_root)
        binding_file = args.config_root / f"{args.case_id}.json"
        if config_file == binding_file:
            binding_file = None
        validate_isolation(obj(args.isolation), item["system"], args.case_id,
                           obj(config_file),
                           owners, args.host)
        result = run_worker(host=args.host, slot=0, slots=1,
                            inventory=args.inventory, ownership_file=args.ownership,
                            config_root=args.config_root, state_root=args.state_root,
                            scratch_root=args.scratch_root,
                            results_dir=args.results_dir,
                            isolation_file=args.isolation, reviews=args.reviews,
                            only_case=args.case_id,
                            min_memory_gib=args.min_memory_gib,
                            min_state_gib=args.min_state_gib,
                            min_scratch_gib=args.min_scratch_gib)
        row = _cached_terminal_inspection(item, args.host, args.config_root,
                                          args.state_root)
        if row["native_tested_complete"] is not True:
            raise RuntimeError("pilot did not complete an audited native fuzz budget")
        completion(item, row, config_file, args.state_root,
                   args.state_root / ".native-queue", native_root=native_root,
                   binding_file=binding_file, config_root=args.config_root)
        export_native_results(args.inventory, args.ownership, args.config_root,
                              args.state_root, args.results_dir)
        receipt = {"schema_version": 1, "passed": True,
                   "case_id": args.case_id, "host": args.host,
                   "inventory_sha256": sha(args.inventory),
                   "ownership_sha256": sha(args.ownership),
                   "isolation_sha256": sha(args.isolation),
                   "config_sha256": sha(config_file),
                   "summary_sha256": sha(native_root / "summary.json")}
        if binding_file is not None:
            receipt["binding_sha256"] = sha(binding_file)
        atomic(args.pilot_receipt, receipt)
        print(json.dumps(result, sort_keys=True))
        return
    if args.case_id or args.pilot_receipt is None:
        parser.error("worker requires --pilot-receipt and no --case-id")
    pilot_receipt(args.pilot_receipt, args.inventory, args.ownership,
                  args.config_root, args.state_root, cases, owners,
                  args.isolation)
    result = run_worker(host=args.host, slot=args.slot, slots=args.slots,
                        inventory=args.inventory, ownership_file=args.ownership,
                        config_root=args.config_root, state_root=args.state_root,
                        scratch_root=args.scratch_root,
                        results_dir=args.results_dir,
                        isolation_file=args.isolation, reviews=args.reviews,
                        min_memory_gib=args.min_memory_gib,
                        min_state_gib=args.min_state_gib,
                        min_scratch_gib=args.min_scratch_gib)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
