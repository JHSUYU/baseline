#!/usr/bin/env python3
"""Strict actor/resource and producer-command gate for HDFS-12 V2 traces."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SITES = {
    "HDFS-11": ("BlockTokenSecretManager.retrieveDataEncryptionKey#L552",
                "BlockTokenSecretManager.retrieveDataEncryptionKey#L553",
                "org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException"),
    "HDFS-12": ("BlockTokenSecretManager.retrievePassword#L511",
                "BlockTokenSecretManager.retrievePassword#L514",
                "org.apache.hadoop.security.token.SecretManager$InvalidToken"),
}
KEYS = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal",
        "actorLocalOrdinal", "faultActor", "resource")


def atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def rows(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()
            if line]


def selector(event: dict) -> tuple:
    return tuple(event.get(key) for key in KEYS)


def eligible_pair(point: dict, target: dict) -> bool:
    return (point["seq"] < target["seq"]
            and point.get("faultActor") not in (None, "unbound")
            and point.get("faultActor") == target.get("targetActor")
            and point.get("resource") not in (None, "unbound")
            and point.get("resource") == target.get("resource"))


def inspect_seed(run: Path, case: str) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    trace = rows(run)
    target_site, throw_site, throw_type = SITES[case]
    targets = [row for row in trace if row.get("event") == "TARGET_CHECK"
               and row.get("caseId") == case and row.get("siteId") == target_site]
    throws = [row for row in trace if row.get("event") == "TARGET_THROW"
              and row.get("caseId") == case and row.get("siteId") == throw_site
              and row.get("exception") == throw_type]
    points = [row for row in trace if row.get("event") == "FAULT_POINT_OBSERVED"]
    eligible = [row for row in points if any(eligible_pair(row, t) for t in targets)]
    registered = [row for row in trace if row.get("event") == "ACTOR_REGISTERED"]
    managers = [row for row in trace if row.get("event") == "MANAGER_BOUND"]
    servers = [row for row in trace if row.get("event") == "SERVER_BOUND"]
    issues = []
    if manifest["returncode"] != 0:
        issues.append("original JUnit failed")
    if not registered or not managers or not servers:
        issues.append("DataNode/manager/SASL binding incomplete")
    if not targets:
        issues.append("selected exact target not reached")
    if any(t.get("targetActor") in (None, "unbound") or
           t.get("resource") in (None, "unbound") for t in targets):
        issues.append("selected target has unbound actor/resource")
    if not eligible:
        issues.append("no earlier SASL I/O on the same actor and block pool")
    if any(row.get("faultActor") in (None, "unbound") or
           row.get("resource") in (None, "unbound") for row in eligible):
        issues.append("eligible I/O is unbound")
    actor_counts: dict[str, int] = {}
    for row in registered:
        actor_counts[row["actorKey"]] = actor_counts.get(row["actorKey"], 0) + 1
    if any(count != 1 for count in actor_counts.values()):
        issues.append("actor key collision among DataNode instances")
    producer_links = []
    producer_points = []
    if case == "HDFS-12":
        if throws:
            issues.append("healthy original JUnit reached selected null-key exception")
        by_actor_pool: dict[tuple[str, str], list[dict]] = {}
        for target in targets:
            by_actor_pool.setdefault((target.get("targetActor"), target.get("resource")), []).append(target)
        if not any(len({t.get("keyId") for t in group if t.get("keyPresent")}) >= 2
                   for group in by_actor_pool.values()):
            issues.append("early and late selected target key IDs were not distinct on one actor/pool")
        responses = [r for r in trace if r.get("event") == "KEY_UPDATE_RESPONSE"
                     and r.get("identityBound") is True
                     and r.get("keyRole") == "ROTATED_CURRENT"]
        imports = [r for r in trace if r.get("event") == "KEY_IMPORT_APPLIED"
                   and r.get("responseCommandMatched") is True]
        producer_points = [r for r in eligible if r.get("marker") in (
            "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE", "FAULT:HDFS_KEY_UPDATE:LOCAL_APPLY")
            and r.get("keyRole") == "ROTATED_CURRENT"]
        for response in responses:
            for imported in imports:
                same_command = all(response.get(k) == imported.get(k) for k in (
                    "faultActor", "resource", "rawBlockPoolId", "nnLogical",
                    "rawNameNodeEndpoint", "rawDatanodeUuid", "dnObjectHash",
                    "rawKeyId", "allKeyIds", "commandIdentity", "managerIdentity"))
                if not same_command or response["seq"] >= imported["seq"]:
                    continue
                same_targets = by_actor_pool.get((response.get("faultActor"),
                                                  response.get("resource")), [])
                early = [t for t in same_targets if t["seq"] < response["seq"]
                         and t.get("managerIdentity") == response.get("managerIdentity")]
                late = [t for t in same_targets if t["seq"] > imported["seq"]
                        and t.get("managerIdentity") == response.get("managerIdentity")]
                if early and late and any(t.get("keyId") != early[0].get("keyId") for t in late):
                    producer_links.append(dict(response_seq=response["seq"],
                                               import_seq=imported["seq"],
                                               actor=response["faultActor"],
                                               pool=response["resource"],
                                               nn=response["nnLogical"],
                                               raw_key_id=response["rawKeyId"],
                                               manager_identity=response["managerIdentity"],
                                               command_identity=response["commandIdentity"],
                                               command_object_hash=response["commandObjectHash"]))
        if not producer_links:
            issues.append("no ordered, identity-matched rotated key response/import between early and late target")
        if not producer_points:
            issues.append("no eligible rotated-key producer fault point before selected target")
    stable = sorted({selector(row) for row in eligible})
    return {
        "run": str(run), "test": manifest["test"], "junit_exit": manifest["returncode"],
        "elapsed_seconds": manifest["elapsed_seconds"],
        "instrumentation_digest_sha256": manifest["instrumentation_digest_sha256"],
        "trace_sha256": hashlib.sha256((run / "runtime_trace.jsonl").read_bytes()).hexdigest(),
        "actors_registered": len(registered), "managers_bound": len(managers),
        "servers_bound": len(servers), "target_checks": len(targets),
        "selected_target_throws": len(throws), "eligible_points": len(eligible),
        "target_actor_resources": sorted({(t.get("targetActor"), t.get("resource"))
                                          for t in targets}),
        "target_key_ids_by_actor_pool": {str(key): sorted({t.get("keyId") for t in group})
                                         for key, group in by_actor_pool.items()}
        if case == "HDFS-12" else {},
        "rotated_producer_links": producer_links,
        "rotated_producer_selectors": [list(item) for item in sorted(
            {selector(row) for row in producer_points})],
        "selectors": [list(item) for item in stable], "issues": issues,
    }


def calibrate(case: str, output: Path, max_seeds: int, timeout: int, method: str | None) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    seeds = []
    for suffix in ("a", "b")[:max_seeds]:
        run = output / f"healthy-{suffix}"
        if not (run / "manifest.json").exists():
            cmd = [sys.executable, str(HERE / "run_original.py"), "--case", case,
                   "--output", str(run), "--timeout", str(timeout)]
            if method:
                cmd.extend(("--method", method))
            with (output / f"runner-{suffix}.log").open("w") as log:
                subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=False)
        if not (run / "manifest.json").exists():
            raise RuntimeError(f"missing healthy manifest; see {output / ('runner-' + suffix + '.log')}")
        seeds.append(inspect_seed(run, case))
    issues = [f"healthy-{suffix}: {issue}" for suffix, seed in zip("ab", seeds)
              for issue in seed["issues"]]
    stable_selectors = []
    stable_producer_selectors = []
    if len(seeds) == 2:
        if seeds[0]["test"] != seeds[1]["test"]:
            issues.append("original JUnit method differs across healthy seeds")
        if seeds[0]["instrumentation_digest_sha256"] != seeds[1]["instrumentation_digest_sha256"]:
            issues.append("instrumentation digest differs across healthy seeds")
        if seeds[0]["target_actor_resources"] != seeds[1]["target_actor_resources"]:
            issues.append("target actor/resource set differs across healthy seeds")
        stable_selectors = sorted(set(map(tuple, seeds[0]["selectors"]))
                                  & set(map(tuple, seeds[1]["selectors"])))
        if not stable_selectors:
            issues.append("no stable full actor-local I/O selector across two seeds")
        if case == "HDFS-12":
            stable_producer_selectors = sorted(
                set(map(tuple, seeds[0]["rotated_producer_selectors"]))
                & set(map(tuple, seeds[1]["rotated_producer_selectors"])))
            if not stable_producer_selectors:
                issues.append("no stable rotated-key producer selector across two seeds")
    receipt = {
        "schema": "hdfs-key-actor-v2-healthy-1", "case_id": case,
        "status": ("awaiting_second_seed" if len(seeds) == 1 else
                   "pass" if not issues else "failed"),
        "pass": len(seeds) == 2 and not issues,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "seeds": seeds, "issues": issues,
        "stable_selectors": [list(item) for item in stable_selectors],
        "stable_selector_count": len(stable_selectors),
        "stable_producer_selectors": [list(item) for item in stable_producer_selectors],
        "stable_producer_selector_count": len(stable_producer_selectors),
        "healthy_target_throw_count": max(s["selected_target_throws"] for s in seeds),
    }
    atomic(output / "healthy_receipt.json", receipt)
    return receipt


def read_plan(path: Path) -> list[dict]:
    plan = []
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        values = line.split("\t")
        if len(values) != 7:
            raise ValueError("HDFS-12 V2 plan requires marker,siteId,faultActor,resource,ordinal,faultType,requiredRawKeyId")
        plan.append(dict(zip(("marker", "siteId", "faultActor", "resource",
                              "hitOrdinal", "faultType", "requiredRawKeyId"), values)))
        plan[-1]["hitOrdinal"] = int(plan[-1]["hitOrdinal"])
        producer = plan[-1]["marker"].startswith("FAULT:HDFS_KEY_UPDATE:")
        required_key = plan[-1]["requiredRawKeyId"]
        if (producer and required_key == "-") or (not producer and required_key != "-"):
            raise ValueError("raw key ID constraint does not match fault marker")
        if producer and required_key != "*" and (not required_key.isdecimal()):
            raise ValueError("producer raw key ID must be wildcard or nonnegative integer")
    if not plan:
        raise ValueError("empty V2 plan")
    if len({(step["faultActor"], step["resource"]) for step in plan}) != 1:
        raise ValueError("V2 sequence requires one actor and one block pool")
    return plan


def evaluate(case: str, run: Path, plan_path: Path, healthy_receipt: Path) -> dict:
    healthy = json.loads(healthy_receipt.read_text())
    if not healthy.get("pass") or healthy.get("case_id") != case:
        raise ValueError("matching two-seed healthy receipt required")
    plan = read_plan(plan_path)
    manifest = json.loads((run / "manifest.json").read_text())
    trace = rows(run)
    target_site, throw_site, throw_type = SITES[case]
    expected = [dict(step, planIndex=i) for i, step in enumerate(plan)]
    matched = [r for r in trace if r.get("event") == "FAULT_MATCHED"]
    applied = [r for r in trace if r.get("event") == "FAULT_APPLIED"]
    observed = [r for r in trace if r.get("event") == "FAULT_POINT_OBSERVED"]

    def exact(rows_to_check: list[dict]) -> bool:
        return len(rows_to_check) == len(expected) and all(
            all(row.get(k) == step[k] for k in (*step.keys(),))
            and (row.get("rawKeyId", -1) >= 0 if step["requiredRawKeyId"] == "*" else
                 row.get("rawKeyId", -1) < 0 if step["requiredRawKeyId"] == "-" else
                 row.get("rawKeyId") == int(step["requiredRawKeyId"]))
            and row.get("actorLocalOrdinal") == step["hitOrdinal"]
            and row.get("sourceKey") == step["faultActor"] + "/resource=" + step["resource"]
            and row.get("occurrence") == row.get("sourceKey") + "/site=" + step["siteId"]
            for row, step in zip(rows_to_check, expected))

    strict = exact(matched) and exact(applied)
    if strict:
        strict = all(m["seq"] < a["seq"] for m, a in zip(matched, applied))
        strict = strict and all(applied[i]["seq"] < matched[i + 1]["seq"]
                                for i in range(len(plan) - 1))
        strict = strict and all(any(o["seq"] < m["seq"] and selector(o) == selector(m)
                                    and o.get("rawKeyId") == m.get("rawKeyId")
                                    and o.get("managerIdentity") == m.get("managerIdentity")
                                    and o.get("commandIdentity") == m.get("commandIdentity")
                                    for o in observed) for m in matched)
    last_seq = applied[-1]["seq"] if strict else None
    selected_actor, selected_pool = plan[-1]["faultActor"], plan[-1]["resource"]
    post_targets = [r for r in trace if r.get("event") == "TARGET_CHECK"
                    and r.get("caseId") == case and r.get("siteId") == target_site
                    and last_seq is not None and r["seq"] > last_seq
                    and r.get("targetActor") == selected_actor
                    and r.get("resource") == selected_pool]
    post_throws = [r for r in trace if r.get("event") == "TARGET_THROW"
                   and r.get("caseId") == case and r.get("siteId") == throw_site
                   and r.get("exception") == throw_type and last_seq is not None
                   and r["seq"] > last_seq and r.get("targetActor") == selected_actor
                   and r.get("resource") == selected_pool]
    valid = strict and bool(post_targets)
    candidate = valid and len(post_throws) > healthy["healthy_target_throw_count"]
    producer_faults = [r for r in applied if r.get("marker", "").startswith(
        "FAULT:HDFS_KEY_UPDATE:")]
    same_manager_targets = [r for r in post_targets if any(
        r.get("managerIdentity") == f.get("managerIdentity")
        and f.get("managerIdentity") not in (None, 0) for f in producer_faults)]
    later_imports = [r for r in trace if r.get("event") == "KEY_IMPORT_APPLIED"
                     and last_seq is not None and r["seq"] > last_seq
                     and r.get("faultActor") == selected_actor
                     and r.get("resource") == selected_pool]
    result = {
        "schema": "hdfs-key-actor-v2-trial-1", "case_id": case,
        "run": str(run), "test": manifest["test"],
        "elapsed_seconds": manifest["elapsed_seconds"], "junit_exit": manifest["returncode"],
        "plan": str(plan_path), "requested_faults": len(plan),
        "matched_faults": len(matched), "applied_faults": len(applied),
        "exact_order_applied": strict,
        "postfault_target_same_actor_resource": bool(post_targets),
        "postfault_target_count": len(post_targets),
        "postfault_target_raw_key_ids": sorted({r.get("keyId") for r in post_targets}),
        "postfault_target_same_producer_manager_count": len(same_manager_targets),
        "postfault_target_exception_count": len(post_throws),
        "applied_producer_faults": [{key: row.get(key) for key in (
            "marker", "siteId", "faultActor", "resource", "nnLogical",
            "rawBlockPoolId", "rawDatanodeUuid", "rawNameNodeEndpoint",
            "dnObjectHash", "managerIdentity", "managerObjectHash",
            "rawKeyId", "allKeyIds", "commandIdentity", "commandObjectHash",
            "keyRole")} for row in producer_faults],
        "postfault_key_import_count": len(later_imports),
        "valid_for_feedback": valid,
        "target_exception_candidate": candidate,
        "classification": ("candidate_needs_replay_and_source_review" if candidate else
                           "valid_no_new_target_exception" if valid else
                           "unmatched_or_target_lost"),
    }
    atomic(run / "v2_result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    cal = sub.add_parser("calibrate")
    cal.add_argument("--case", choices=SITES, required=True)
    cal.add_argument("--output", type=Path, required=True)
    cal.add_argument("--max-seeds", type=int, choices=(1, 2), default=2)
    cal.add_argument("--timeout", type=int, default=600)
    cal.add_argument("--method")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--case", choices=SITES, required=True)
    ev.add_argument("--run", type=Path, required=True)
    ev.add_argument("--plan", type=Path, required=True)
    ev.add_argument("--healthy-receipt", type=Path, required=True)
    args = parser.parse_args()
    result = (calibrate(args.case, args.output, args.max_seeds, args.timeout, args.method)
              if args.command == "calibrate" else
              evaluate(args.case, args.run.resolve(), args.plan.resolve(),
                       args.healthy_receipt.resolve()))
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
