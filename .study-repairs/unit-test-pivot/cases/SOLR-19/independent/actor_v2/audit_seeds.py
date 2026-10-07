#!/usr/bin/env python3
"""Check exact core and logical node joins in two original-JUnit traces."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from urllib.parse import urlsplit


COLUMNS = ("seq", "nano", "thread", "phase", "core", "actor", "endpoint",
           "standard", "override", "effective", "detail")
REQUIRED = ("RECEIVE_CREATE", "DESCRIPTOR_BEFORE_FILE", "EXTRA_PROPERTIES_FILE",
            "DESCRIPTOR_AFTER_FILE", "TARGET_GUARD")


def read(seed: Path):
    rows = []
    for line in (seed / "actor-events.tsv").read_text().splitlines():
        cells = line.split("\t")
        if len(cells) != len(COLUMNS):
            raise ValueError(f"{seed}: malformed event {line!r}")
        rows.append(dict(zip(COLUMNS, cells)))
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["phase"].startswith("IO_") or row["phase"] == "ZK_BIND":
            continue
        groups[row["core"]][row["phase"]].append(row)
    return rows, groups


def audit(seed: Path):
    manifest = json.loads((seed / "manifest.json").read_text())
    rows, groups = read(seed)
    results = []
    for core, phases in sorted(groups.items()):
        send = phases.get("SEND_CREATE_COLLECTION", []) + phases.get("SEND_ADD_REPLICA", [])
        counts = {phase: len(phases.get(phase, [])) for phase in REQUIRED}
        issues = []
        if len(send) != 1:
            issues.append(f"sender_count={len(send)}")
        for phase, count in counts.items():
            if count != 1:
                issues.append(f"{phase}_count={count}")
        if send and phases.get("RECEIVE_CREATE"):
            sender, receiver = send[0], phases["RECEIVE_CREATE"][0]
            if sender["actor"] != receiver["actor"]:
                issues.append("sender_receiver_actor_mismatch")
            if sender["standard"] != receiver["standard"]:
                issues.append("standard_field_changed_in_rpc")
            if sender["override"] != receiver["override"]:
                issues.append("override_field_changed_in_rpc")
            if receiver["effective"] != sender["standard"]:
                issues.append("receiver_map_differs_from_standard")
            if "_" in sender["actor"]:
                host_port, context = sender["actor"].split("_", 1)
                url = urlsplit(sender["endpoint"])
                if url.netloc != host_port or url.path.strip("/") != context:
                    issues.append("sender_baseurl_differs_from_receiver_node")
            else:
                issues.append("unexpected_sender_node_format")
        if all(phases.get(phase) for phase in ("DESCRIPTOR_BEFORE_FILE", "EXTRA_PROPERTIES_FILE", "DESCRIPTOR_AFTER_FILE")):
            before = phases["DESCRIPTOR_BEFORE_FILE"][0]
            file = phases["EXTRA_PROPERTIES_FILE"][0]
            after = phases["DESCRIPTOR_AFTER_FILE"][0]
            if before["effective"] != file["standard"]:
                issues.append("file_prevalue_differs_from_descriptor")
            if file["detail"] == "false" and before["effective"] != after["effective"]:
                issues.append("descriptor_changed_without_external_file")
        if phases.get("DESCRIPTOR_AFTER_FILE") and phases.get("TARGET_GUARD"):
            descriptor, target = phases["DESCRIPTOR_AFTER_FILE"][0], phases["TARGET_GUARD"][0]
            if descriptor["effective"] != target["effective"]:
                issues.append("descriptor_guard_value_mismatch")
            if target["detail"] != "present":
                issues.append("guard_throwing")
        if phases.get("EXTRA_PROPERTIES_FILE"):
            if phases["EXTRA_PROPERTIES_FILE"][0]["detail"] != "false":
                issues.append("external_properties_file_exists")
        if len(send) == 1 and all(count == 1 for count in counts.values()):
            ordered = [send[0]] + [phases[phase][0] for phase in REQUIRED]
            if [int(row["seq"]) for row in ordered] != sorted(int(row["seq"]) for row in ordered):
                issues.append("sender_to_guard_order_mismatch")
        results.append({
            "core": core,
            "sender_phase": send[0]["phase"] if send else None,
            "producer_role": send[0]["detail"].rsplit("|sourceRole=", 1)[-1] if send else None,
            "sender_actor": send[0]["actor"] if send else None,
            "receiver_actor": phases["RECEIVE_CREATE"][0]["actor"] if phases.get("RECEIVE_CREATE") else None,
            "standard_core_node": send[0]["standard"] if send else None,
            "property_override": send[0]["override"] if send else None,
            "file_exists": phases["EXTRA_PROPERTIES_FILE"][0]["detail"] if phases.get("EXTRA_PROPERTIES_FILE") else None,
            "target_value": phases["TARGET_GUARD"][0]["effective"] if phases.get("TARGET_GUARD") else None,
            "issues": issues,
        })
    issue_count = sum(len(result["issues"]) for result in results)
    if manifest["exit_code"] != 0:
        issue_count += 1
    io_rows = [row for row in rows if row["phase"].startswith("IO_")]
    file_open_rows = [row for row in rows if row["phase"] == "FILE_OPEN"]
    binds = [row for row in rows if row["phase"] == "ZK_BIND"]
    role_by_node = {row["core"]: row["actor"] for row in binds}
    for result in results:
        result["sender_role"] = role_by_node.get(result["sender_actor"])
        result["receiver_role"] = role_by_node.get(result["receiver_actor"])
        if result["sender_role"] is None or result["receiver_role"] is None:
            result["issues"].append("create_actor_lacks_zk_client_binding")
            issue_count += 1
        if result["producer_role"] == "UNBOUND":
            result["issues"].append("producer_actor_lacks_zk_client_binding")
            issue_count += 1
    return {"seed": str(seed), "elapsed_seconds": manifest["elapsed_seconds"],
            "junit_exit": manifest["exit_code"], "event_count": len(rows),
            "phase_counts": dict(Counter(row["phase"] for row in rows)),
            "io_count": len(io_rows),
            "file_open_count": len(file_open_rows),
            "io_bound_count": sum(row["actor"] != "UNBOUND" for row in io_rows),
            "io_unbound_count": sum(row["actor"] == "UNBOUND" for row in io_rows),
            "zk_bind_count": len(binds),
            "io_site_count": len({(row["phase"], row["detail"]) for row in io_rows}),
            "io_exact_identity_count": len({(row["phase"], row["core"], row["detail"], row["actor"]) for row in io_rows}),
            "core_count": len(results), "issue_count": issue_count,
            "cores": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("seeds", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = [audit(seed) for seed in args.seeds]
    if len(result) == 2:
        first = {(x["core"], x["sender_phase"], x["standard_core_node"])
                 for x in result[0]["cores"]}
        second = {(x["core"], x["sender_phase"], x["standard_core_node"])
                  for x in result[1]["cores"]}
        actor_a = {(x["core"], x["sender_role"], x["standard_core_node"])
                   for x in result[0]["cores"]}
        actor_b = {(x["core"], x["sender_role"], x["standard_core_node"])
                   for x in result[1]["cores"]}
        io_a = {(r["phase"], r["core"], r["detail"], r["actor"]) for r in read(args.seeds[0])[0]
                if r["phase"].startswith("IO_")}
        io_b = {(r["phase"], r["core"], r["detail"], r["actor"]) for r in read(args.seeds[1])[0]
                if r["phase"].startswith("IO_")}
        output = {"seeds": result, "stable_core_selector_intersection": len(first & second),
                  "stable_core_selector_union": len(first | second),
                  "stable_actor_core_selector_intersection": len(actor_a & actor_b),
                  "stable_actor_core_selector_union": len(actor_a | actor_b),
                  "stable_io_exact_identity_intersection": len(io_a & io_b),
                  "stable_io_exact_identity_union": len(io_a | io_b)}
    else:
        output = {"seeds": result}
    payload = json.dumps(output, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload)


if __name__ == "__main__":
    main()
