#!/usr/bin/env python3
"""Resumable HDFS31 actor/BP-aware exception campaign for the original JUnit."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import run_original
from audit_healthy import rows, selector as stable_selector

HERE = Path(__file__).resolve().parent
CASE = "HDFS-31"
MARKER = "FAULT:HDFS31_BP_RPC:RESPONSE"
FAULTS = ("IOException", "SocketTimeoutException", "EOFException")
COVERAGE = ("probes", "methods", "branch_counts", "lines")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def covered(run: Path, kind: str) -> set[str]:
    path = run / f"covered_{kind}.txt"
    return set(path.read_text().splitlines()) if path.is_file() else set()


def target_checks(trace: list[dict]) -> list[dict]:
    transfers = [r for r in trace if r["event"] == "DIRECT_TRANSFER"
                 and r.get("caseId") == CASE]
    return [r for r in trace if r["event"] == "DIRECT_TARGET_CHECK"
            and r.get("caseId") == CASE and r.get("actorKey") not in (None, "unbound")
            and r.get("dnUuidRaw") and r.get("blockPoolIdRaw")
            and (r.get("serviceOwnerSameDnBp") is True or
                 (r.get("servicePresent") is False and
                  r.get("priorPoolOwnerSameDnBp") is True))
            and any(t["seq"] < r["seq"] and all(t.get(k) == r.get(k) for k in
                    ("actorKey", "dnObjectId", "dnUuidRaw", "blockPoolIdRaw", "blockIdRaw"))
                    for t in transfers)]


def related(io: dict, target: dict) -> bool:
    return (io["seq"] < target["seq"] and io.get("marker") == MARKER
            and io.get("sourceKey") != "unbound" and io.get("peerRole") == "NN0"
            and io.get("actorKey") == target.get("actorKey")
            and io.get("dnObjectId") == target.get("dnObjectId")
            and io.get("serviceObjectId") == target.get("serviceObjectId")
            and target.get("serviceObjectId", -1) > 0)


def eligible_io(trace: list[dict], after: int = -1, actor: str | None = None) -> list[dict]:
    targets = target_checks(trace)
    return [r for r in trace if r["event"] == "FAULT_POINT_OBSERVED"
            and r["seq"] > after and (actor is None or r.get("actorKey") == actor)
            and any(related(r, target) for target in targets)]


def step(row: dict, fault: str) -> dict:
    return {key: row.get(key) for key in
            ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal", "actorKey",
             "peerRole")} | {"faultType": fault}


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]


def plan_text(sequence: list[dict]) -> str:
    return "".join("\t".join((s["marker"], s["siteId"], s["sourceKey"],
                              str(s["hitOrdinal"]), "pending", s["faultType"])) + "\n"
                   for s in sequence)


def exact_applied(sequence: list[dict], trace: list[dict]) -> tuple[bool, list[dict]]:
    applied = [r for r in trace if r["event"] == "FAULT_APPLIED"]
    keys = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal",
            "actorKey", "peerRole", "faultType")
    exact = len(sequence) == len(applied) and all(
        a.get("faultIndex") == i and all(a.get(k) == s.get(k) for k in keys)
        for i, (s, a) in enumerate(zip(sequence, applied)))
    if not exact:
        return False, applied
    endpoint_by_actor: dict[str, set[str]] = {}
    for row in trace:
        if (row.get("event") == "FAULT_POINT_OBSERVED" and row.get("peerRole") == "NN0"
                and row.get("sourceKey") != "unbound"):
            endpoint_by_actor.setdefault(row["actorKey"], set()).add(row.get("endpointRaw", ""))
    actor = sequence[0]["actorKey"]
    endpoint = endpoint_by_actor.get(actor, set())
    if len(endpoint) != 1 or "" in endpoint:
        return False, applied
    if any(a.get("actorKey") != actor or a.get("endpointRaw") not in endpoint
           or a.get("actorNamenodeRaw") != a.get("endpointRaw")
           or a.get("dnObjectId") != applied[0].get("dnObjectId")
           or a.get("serviceObjectId") != applied[0].get("serviceObjectId")
           or a.get("serviceObjectId", -1) <= 0 for a in applied):
        return False, applied
    return True, applied


def same_target(row: dict, applied: list[dict], last_seq: int) -> bool:
    first = applied[0]
    if (row["seq"] <= last_seq or row.get("actorKey") != first.get("actorKey")
            or row.get("dnObjectId") != first.get("dnObjectId")
            or not row.get("dnUuidRaw") or not row.get("blockPoolIdRaw")):
        return False
    if row["event"] == "DIRECT_TARGET_CHECK" and row.get("servicePresent"):
        return (row.get("serviceObjectId") == first.get("serviceObjectId")
                and row.get("serviceOwnerSameDnBp") is True)
    # A null service is precisely the candidate failure at this guard.
    return row.get("priorPoolOwnerSameDnBp") is True


def postfault(trace: list[dict], applied: list[dict], exact: bool) -> tuple[list[dict], list[dict]]:
    if not exact or not applied:
        return [], []
    last_seq = applied[-1]["seq"]
    linked_bp = {r.get("blockPoolIdRaw") for r in trace if r["event"] == "POOL_ADD"
                 and r.get("actorKey") == applied[0].get("actorKey")
                 and r.get("dnObjectId") == applied[0].get("dnObjectId")
                 and r.get("serviceObjectId") == applied[0].get("serviceObjectId")}
    checks = [r for r in target_checks(trace) if same_target(r, applied, last_seq)
              and r.get("blockPoolIdRaw") in linked_bp]
    throws = [r for r in trace if r["event"] == "DIRECT_TARGET_THROW"
              and r.get("caseId") == CASE and same_target(r, applied, last_seq)
              and any(c["seq"] < r["seq"] and c.get("actorKey") == r.get("actorKey")
                      and c.get("dnObjectId") == r.get("dnObjectId")
                      and c.get("dnUuidRaw") == r.get("dnUuidRaw")
                      and c.get("blockPoolIdRaw") == r.get("blockPoolIdRaw")
                      and c.get("blockIdRaw") == r.get("blockIdRaw") for c in checks)]
    return checks, throws


def family(row: dict) -> str:
    return "|".join((row["marker"], row["siteId"], row["sourceKey"]))


def initial_queue(receipt: dict, trace: list[dict]) -> list[dict]:
    stable = {tuple(x) for x in receipt["stable_selectors"]}
    queue: dict[str, dict] = {}
    for row in eligible_io(trace):
        if stable_selector(row) not in stable:
            continue
        distance = min(t["seq"] - row["seq"] for t in target_checks(trace)
                       if related(row, t))
        for kind in FAULTS:
            sequence = [step(row, kind)]
            identity = sequence_id(sequence)
            queue[identity] = {"id": identity, "sequence": sequence,
                               "score": 1000 - distance, "seed": "healthy-a"}
    return sorted(queue.values(), key=lambda x: (-x["score"], x["id"]))


def load_state(anchor: Path, receipt: dict, max_attempts: int) -> dict:
    path = anchor / "campaign-state.json"
    receipt_sha = sha(anchor / "healthy_receipt.json")
    overlay_sha = receipt["seeds"][0]["instrumentation_digest_sha256"]
    if path.is_file():
        state = json.loads(path.read_text())
        if (state.get("schema") != "hdfs31-actor-v3-campaign-1"
                or state.get("healthy_receipt_sha256") != receipt_sha
                or state.get("instrumentation_digest_sha256") != overlay_sha
                or len(state["completion_order"]) != len(set(state["completion_order"]))
                or set(state["completion_order"]) != set(state["completed"])):
            raise RuntimeError("checkpoint, receipt, or overlay identity changed")
        state["budget"]["max_attempts"] = max(
            max_attempts, state["budget"]["max_attempts"])
        return state
    seed = anchor / "healthy-a"
    trace = rows(seed / "runtime_trace.jsonl")
    state = {"schema": "hdfs31-actor-v3-campaign-1", "case_id": CASE,
             "healthy_receipt_sha256": receipt_sha,
             "instrumentation_digest_sha256": overlay_sha,
             "healthy_throw_signatures": receipt["seeds"][0]["throw_signatures"],
             "budget": {"base_effective": 80, "extended_effective": 128,
                        "goal": 80, "max_faults": 8, "max_attempts": max_attempts},
             "queue": initial_queue(receipt, trace), "completed": {},
             "completion_order": [], "in_flight": None, "effective": 0,
             "effective_history": [],
             "coverage": {k: sorted(covered(seed, k)) for k in COVERAGE},
             "io_families": sorted({family(r) for r in eligible_io(trace)}),
             "started_at_utc": datetime.now(timezone.utc).isoformat()}
    save(path, state)
    return state


def pick(state: dict) -> dict | None:
    if state["in_flight"] is not None:
        return state["in_flight"]
    while state["queue"]:
        n = len(state["completion_order"])
        # Spend most tests on reachable targets; periodically explore deeper
        # recovery sequences without enumerating the full Cartesian product.
        deep = [i for i, item in enumerate(state["queue"]) if len(item["sequence"]) >= 3]
        if n % 10 == 9 and deep:
            i = max(deep, key=lambda j: (len(state["queue"][j]["sequence"]),
                                         state["queue"][j]["score"]))
        else:
            i = max(range(len(state["queue"])), key=lambda j:
                    (state["queue"][j]["score"] - 120 * (len(state["queue"][j]["sequence"]) - 1),
                     -j))
        item = state["queue"].pop(i)
        if item["id"] in state["completed"]:
            continue
        state["in_flight"] = item
        return item
    return None


def summarize(anchor: Path, state: dict, item: dict, run: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("instrumentation_digest_sha256") != state["instrumentation_digest_sha256"]:
        raise RuntimeError("trial overlay differs from both healthy seeds")
    if manifest.get("test") != "org.apache.hadoop.hdfs.server.datanode.TestDiskError#testDataTransferWhenBytesPerChecksumIsZero":
        raise RuntimeError("original JUnit method changed")
    trace = rows(run / "runtime_trace.jsonl")
    exact, applied = exact_applied(item["sequence"], trace)
    checks, throws = postfault(trace, applied, exact)
    valid = exact and bool(checks)
    covered_now = {k: covered(run, k) for k in COVERAGE}
    gains = {k: len(covered_now[k] - set(state["coverage"][k])) if valid else 0
             for k in COVERAGE}
    new_io = len({family(r) for r in eligible_io(trace)} - set(state["io_families"])) if valid else 0
    throw_signatures = sorted({json.dumps({"siteId": r.get("siteId"),
        "actorKey": r.get("actorKey"), "exception": r.get("exception")}, sort_keys=True)
        for r in throws})
    novel = [x for x in throw_signatures if x not in state["healthy_throw_signatures"]]
    summary = {"manifest": str(run / "manifest.json"),
               "trace": str(run / "runtime_trace.jsonl"),
               "trace_sha256": sha(run / "runtime_trace.jsonl"),
               "junit_log": str(run / "junit.log"),
               "started_at_utc": manifest.get("started_at_utc"),
               "finished_at_utc": manifest.get("finished_at_utc"),
               "elapsed_seconds": manifest["elapsed_seconds"],
               "junit_exit": manifest["returncode"],
               "requested_faults": len(item["sequence"]),
               "applied_faults": len(applied), "exact_order_applied": exact,
               "same_dn_bp_post_target": len(checks), "target_exceptions_after_fault": len(throws),
               "target_exceptions": throws, "target_exception_signatures": throw_signatures,
               "target_exceptions_with_novel_signature": len(novel),
               "bug_mark": "candidate_needs_replay_source_review" if novel else "none",
               "valid_for_feedback": valid, "coverage_gain": gains,
               "new_io_families": new_io}
    return summary, trace


def mutate(state: dict, item: dict, trace: list[dict]) -> None:
    exact, applied = exact_applied(item["sequence"], trace)
    if not postfault(trace, applied, exact)[0] or len(item["sequence"]) >= state["budget"]["max_faults"]:
        return
    seen = set(state["completed"]) | {x["id"] for x in state["queue"]}
    seen.add(item["id"])
    for row in eligible_io(trace, after=applied[-1]["seq"], actor=applied[0]["actorKey"]):
        if (row.get("dnObjectId") != applied[0].get("dnObjectId")
                or row.get("serviceObjectId") != applied[0].get("serviceObjectId")):
            continue
        for kind in FAULTS:
            sequence = item["sequence"] + [step(row, kind)]
            identity = sequence_id(sequence)
            if identity in seen:
                continue
            state["queue"].append({"id": identity, "sequence": sequence,
                                   "score": 1000 + 80 * len(sequence)
                                   + state["completed"][item["id"]]["result"]["coverage_gain"]["branch_counts"],
                                   "seed": item["id"]})
            seen.add(identity)


def campaign(anchor: Path, max_attempts: int, timeout: int, once: int) -> dict:
    receipt = json.loads((anchor / "healthy_receipt.json").read_text())
    if receipt.get("schema") != "hdfs31-actor-v3-healthy-1" or not receipt.get("pass"):
        raise RuntimeError("two original healthy JUnits have not passed the actor gate")
    state = load_state(anchor, receipt, max_attempts)
    ran = 0
    while state["effective"] < state["budget"]["goal"]:
        if len(state["completion_order"]) >= state["budget"]["max_attempts"]:
            state["status"] = "budget_recheck_pending"
            state["stop_reason"] = "attempt_cap"
            break
        item = pick(state)
        if item is None:
            state["status"] = "budget_recheck_pending"
            state["stop_reason"] = "queue_exhausted"
            break
        save(anchor / "campaign-state.json", state)
        run = anchor / "runs" / item["id"] / "attempt-1"
        if not (run / "manifest.json").is_file():
            if run.exists() and any(run.iterdir()):
                raise RuntimeError("in-flight JUnit has no terminal manifest; reconcile its process and raw files")
            run.mkdir(parents=True)
            plan = run / "faults.tsv"
            plan.write_text(plan_text(item["sequence"]))
            # The caller must hold the shared host JVM start lock through this JUnit.
            run_original.run(run_id=item["id"], plan=plan, timeout=timeout,
                             output=run)
        result, trace = summarize(anchor, state, item, run)
        state["completed"][item["id"]] = {"item": item, "result": result}
        state["completion_order"].append(item["id"])
        state["in_flight"] = None
        if result["valid_for_feedback"]:
            state["effective"] += 1
            state["effective_history"].append({"coverage_gain": result["coverage_gain"],
                                                "new_io_families": result["new_io_families"]})
            for kind in COVERAGE:
                state["coverage"][kind] = sorted(set(state["coverage"][kind]) | covered(run, kind))
            state["io_families"] = sorted(set(state["io_families"]) |
                                          {family(r) for r in eligible_io(trace)})
        mutate(state, item, trace)
        if state["effective"] == 80 and state["budget"]["goal"] == 80:
            last = state["effective_history"][-8:]
            if any(x["coverage_gain"]["branch_counts"] or x["new_io_families"] for x in last):
                state["budget"]["goal"] = 128
                state["budget"]["max_faults"] = 10
                state["budget"]["max_attempts"] = max(512, state["budget"]["max_attempts"])
                state["extension"] = {"reason": "last_eight_effective_novelty",
                                      "at_completed": len(state["completion_order"])}
        state["status"] = "running"
        state["last_completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        save(anchor / "campaign-state.json", state)
        ran += 1
        if once and ran >= once:
            state["status"] = "batch_pause"
            break
    else:
        state["status"] = "budget_complete"
        state["stop_reason"] = "effective_goal_reached"
    save(anchor / "campaign-state.json", state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=Path, default=HERE / "evidence")
    parser.add_argument("--max-attempts", type=int, default=320)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--once", type=int, default=0)
    args = parser.parse_args()
    if args.max_attempts < 1 or args.max_attempts > 512:
        parser.error("max-attempts must be in [1,512]")
    state = campaign(args.anchor.resolve(), args.max_attempts, args.timeout, args.once)
    print(json.dumps({"status": state["status"], "completed": len(state["completion_order"]),
                      "effective": state["effective"], "goal": state["budget"]["goal"]}))


if __name__ == "__main__":
    main()
