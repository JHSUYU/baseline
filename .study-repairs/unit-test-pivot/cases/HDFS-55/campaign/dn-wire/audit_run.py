#!/usr/bin/env python3
"""Audit one checkpointed DN-wire run without treating each response as a new fault."""

import argparse
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
FIELD = re.compile(r"([a-z_]+)=([^ ]+)")


def event(line):
    return dict(FIELD.findall(line.strip()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    manifest = json.loads((run / "manifest.json").read_text())
    lines = (run / "junit.log").read_text(errors="replace").splitlines()
    selected = [(i, event(x)) for i, x in enumerate(lines)
                if "CASE55 dn_wire_selected_manager=" in x]
    rejected = [(i, event(x)) for i, x in enumerate(lines)
                if "CASE55 dn_wire_reject=" in x]
    responses = [(i, event(x)) for i, x in enumerate(lines)
                 if "CASE55 dn_wire_error_response=INVALID_KEY" in x]
    guards = [(i, event(x)) for i, x in enumerate(lines)
              if "CASE55 key_guard=" in x]
    outbound = [(i, event(x)) for i, x in enumerate(lines)
                if "CASE55 balancer_sasl_attempt=" in x]
    chosen = selected[0][1] if selected else None
    old_manager = chosen.get("dn_wire_selected_manager") if chosen else None
    old_key = chosen.get("key_id") if chosen else None
    old_nonce = chosen.get("nonce_digest") if chosen else None
    after = [fields for i, fields in guards
             if rejected and i > rejected[-1][0] and
             fields.get("manager") == old_manager and
             fields.get("cached_key_id") == old_key]
    after_logical_fault = [fields for i, fields in guards
                           if rejected and i > rejected[0][0] and
                           fields.get("manager") == old_manager and
                           fields.get("cached_key_id") == old_key]
    after_logical_fault_manager = [fields for i, fields in guards
                                   if rejected and i > rejected[0][0] and
                                   fields.get("manager") == old_manager]
    after_logical_fault_old = [fields for fields in after_logical_fault
                               if fields.get("cached_nonce_digest") == old_nonce and
                               fields.get("refresh") == "false"]
    after_old = [fields for fields in after
                 if fields.get("cached_nonce_digest") == old_nonce and
                 fields.get("refresh") == "false"]
    after_new = [fields for fields in after
                 if fields.get("cached_nonce_digest") not in (old_nonce, "none")]
    cleared_at = [i for i, x in enumerate(lines)
                  if "CASE55 balancer_key_cache_cleared=true" in x]
    stack_logged = any("DataTransferSaslUtil.readSaslMessage" in x for x in lines)
    fixed_catch_inferred = bool(responses and cleared_at and
                                any(i > responses[0][0] for i in cleared_at))
    junit = [x for x in lines if "CONTROL original_junit_failures=" in x]
    junit_failed = bool(junit and junit[-1].endswith("=1"))
    timeout = any("test timed out after" in x for x in lines)
    exit_assertion = any("expected:<0> but was:<" in x for x in lines)
    exit_codes = [int(m.group(1)) for line in lines
                  if (m := re.search(r"expected:<0> but was:<(-?\d+)>", line))]
    summary = {
        "name": run.name,
        "source_version": "3.4.3",
        "source_target": "KeyManager.newDataEncryptionKey cached-key guard",
        "fault_model": ("one persistent rejected cached DEK state" if
                        manifest.get("dn_reject_persistent") else
                        "finite remote rejection responses"),
        "logical_faults_planned": manifest.get("logical_faults_planned"),
        "logical_faults_applied": 1 if manifest.get("dn_reject_persistent") and rejected else 0,
        "remote_rejection_observations": len(rejected),
        "wire_invalid_key_responses": len(responses),
        "remote_response_complete": len(rejected) == len(responses),
        "client_ike_stack_logged": stack_logged,
        "client_ike_inferred_from_fixed_catch": fixed_catch_inferred,
        "client_received_ike_on_wire": stack_logged or fixed_catch_inferred,
        "client_ike_evidence": ("DataTransferSaslUtil.readSaslMessage stack" if stack_logged
                                else "fixed Dispatcher IKE catch clears DEK after DN INVALID_KEY"
                                if fixed_catch_inferred else "not separately logged"),
        "selected_manager": old_manager,
        "selected_key_id": old_key,
        "selected_nonce_digest": old_nonce,
        "target_datanode": chosen.get("first_target") if chosen else None,
        "actual_server_endpoints": sorted({fields.get("server_endpoint")
                                            for _, fields in rejected}),
        "same_manager_key_guards_after_final_rejection": len(after),
        "same_cached_dek_guards_after_final_rejection": len(after_old),
        "same_manager_key_guards_after_logical_fault": len(after_logical_fault),
        "same_manager_guards_after_logical_fault": len(after_logical_fault_manager),
        "same_cached_dek_guards_after_logical_fault": len(after_logical_fault_old),
        "target_after_logical_fault": bool(after_logical_fault_manager),
        "new_nonce_guards_after_final_rejection": len(after_new),
        "all_guard_events": len(guards),
        "outbound_sasl_attempts": len(outbound),
        "cache_clear_events": len(cleared_at),
        "failed_block_moves": sum("Failed to move blk_" in x for x in lines),
        "successful_block_moves": sum("Successfully moved blk_" in x for x in lines),
        "junit_failed": junit_failed,
        "junit_timeout": timeout,
        "balancer_exit_assertion_failed": exit_assertion,
        "observed_balancer_exit_codes": exit_codes,
        "returncode": manifest.get("returncode"),
        "harness_complete": manifest.get("returncode") != 124 and bool(junit),
        "elapsed_seconds": manifest.get("elapsed_seconds"),
        "covered_methods": manifest.get("covered_methods"),
        "covered_branches": manifest.get("covered_branch_counts"),
        "log": str(run / "junit.log"),
        "manifest": str(run / "manifest.json"),
    }
    tmp = run / "audit.json.tmp"
    tmp.write_text(json.dumps(summary, indent=2) + "\n")
    tmp.replace(run / "audit.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
