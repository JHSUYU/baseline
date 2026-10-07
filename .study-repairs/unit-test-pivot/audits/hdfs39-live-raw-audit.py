#!/usr/bin/env python3
"""Read-only, independent raw audit of a HDFS-39 actor V2 checkpoint snapshot."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

KEYS = ("marker", "api", "endpoint", "ordinal", "exception")
TEST = "org.apache.hadoop.hdfs.TestFileAppend#testMultipleAppends"
TARGET = "FSDirAppendOp.appendFile:131"


def read_json(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lines(path: Path) -> set[str]:
    return set(path.read_text().splitlines())


def relevant(event: dict, path: str, block: int) -> bool:
    if event.get("event") != "IO_OBSERVED":
        return False
    marker, api, endpoint = (event.get(k, "") for k in ("marker", "api", "endpoint"))
    if marker in ("RPC_SEND", "RPC_RESPONSE_WAIT"):
        if api.startswith("DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"):
            match = re.search(r"blocks=\[([0-9, ]+)\]", api)
            return bool(match and str(block) in match.group(1).split(", ")
                        and re.fullmatch(r"nn0<-dn[0-3]", endpoint)
                        and event.get("sourceUuid") and event.get("blockPoolId")
                        and event.get("peerPort", -1) > 0)
        return (api == f"ClientNamenodeProtocolTranslatorPB.append[append:{path}]"
                and endpoint == "nn0<-client" and event.get("peerPort", -1) > 0)
    return marker == "FILE_FLUSH" and api == "editLog:durable" and endpoint == "nnlocal"


def inspect(root: Path) -> dict:
    state = read_json(root / "campaign-v2/checkpoint.json")
    calibration = read_json(root / "healthy-calibration.json")
    completed = list(state["completed"])
    target = state["target"]
    path, block = target["path"], target["block_id"]
    errors: list[str] = []
    if (state.get("case") != "HDFS-39" or state.get("version") != 2 or
            state.get("legacy_effective_imported") != 0 or
            not calibration.get("pass") or calibration.get("cluster_junit_seeds") != 2):
        errors.append("campaign/healthy provenance mismatch")
    for healthy in calibration["healthy"]:
        if (healthy["target_path"] != path or healthy["target_block_id"] != block or
                set(healthy["dn_roles"].values()) != {"dn0", "dn1", "dn2", "dn3"}):
            errors.append("healthy original fixture target/actor map mismatch")
    coverage_union = set().union(*(lines(root / f"healthy-{letter}/coverage.tsv")
                                   for letter in ("a", "b")))
    io_union: set[str] = set()
    healthy_class_sha: str | None = None
    for letter in ("a", "b"):
        healthy_manifest = read_json(root / f"healthy-{letter}/manifest.json")
        class_sha = healthy_manifest.get("overlay_test_sha256")
        if not class_sha or (healthy_class_sha is not None and class_sha != healthy_class_sha):
            errors.append(f"healthy-{letter} original JUnit class mismatch")
        healthy_class_sha = class_sha
        trace = [json.loads(line) for line in (root / f"healthy-{letter}/trace/runtime_trace.jsonl").read_text().splitlines() if line]
        guards = [e["seq"] for e in trace if e.get("event") == "TARGET_GUARD" and
                  e.get("site") == TARGET and e.get("path") == path and e.get("blockId") == block]
        if not guards:
            errors.append(f"healthy-{letter} missing target")
            continue
        io_union.update("\t".join(str(e[k]) for k in ("marker", "api", "endpoint"))
                        for e in trace if e.get("seq", 0) < max(guards) and relevant(e, path, block))
    candidates: list[str] = []
    missed_candidates: list[str] = []
    audited_effective = 0
    fully_applied = 0
    for number, row in enumerate(completed, 1):
        run_id = row["run"]
        run = root / run_id
        try:
            if not run_id.startswith(f"trial-{number:04d}-attempt-"):
                raise ValueError("run numbering or duplicate checkpoint row")
            plan_path = root / "campaign-v2/plans" / (run_id + ".tsv")
            plan = [line.split("\t") for line in plan_path.read_text().splitlines() if line]
            expected = [[str(fault[key]) for key in KEYS] for fault in row["sequence"]]
            ident = hashlib.sha256(json.dumps(row["sequence"], sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()[:20]
            if plan != expected or row["id"] != ident:
                raise ValueError("exact immutable plan/sequence ID mismatch")
            manifest = read_json(run / "manifest.json")
            trace_path = run / "trace/runtime_trace.jsonl"
            jacoco = run / "jacoco.exec"
            if (manifest["test"] != TEST or manifest["exit"] != row["junit_exit"] or
                    manifest["elapsed_seconds"] != row["elapsed_seconds"] or
                    manifest.get("overlay_test_sha256") != healthy_class_sha or
                    manifest["plan_sha256"] != sha(plan_path) or
                    manifest["trace_sha256"] != sha(trace_path) or
                    manifest["jacoco_sha256"] != sha(jacoco)):
                raise ValueError("original JUnit manifest/hash mismatch")
            trace = [json.loads(line) for line in trace_path.read_text().splitlines() if line]
            peer = None
            bp = None
            roles: dict[str, str] = {}
            binding: dict[int, tuple[str, str, str] | None] = {}
            matched: list[dict] = []
            applied: list[dict] = []
            for event in trace:
                kind = event.get("event")
                if kind == "NN_ENDPOINT_REGISTER":
                    ident_pair = (event.get("peerPort"), event.get("blockPoolId"))
                    if peer is not None and ident_pair != (peer, bp):
                        raise ValueError("conflicting physical NN peer/BP")
                    peer, bp = ident_pair
                elif kind == "DN_ROLE_MAP":
                    uuid, role = event.get("sourceUuid"), event.get("role")
                    if not uuid or uuid in roles and roles[uuid] != role:
                        raise ValueError("ambiguous physical DN UUID")
                    roles[uuid] = role
                elif kind == "DN_RPC_BIND":
                    binding[event["threadId"]] = (event.get("sourceUuid"),
                                                  event.get("blockPoolId"), event.get("sourceRole"))
                elif kind == "DN_RPC_UNBIND":
                    binding[event["threadId"]] = None
                elif kind in ("FAULT_MATCHED", "FAULT_APPLIED"):
                    selected = matched if kind == "FAULT_MATCHED" else applied
                    index = len(selected)
                    if index >= len(plan):
                        raise ValueError(f"extra {kind}")
                    actual = [str(event.get(k)) for k in KEYS[:4]]
                    if actual != plan[index][:4] or (kind == "FAULT_APPLIED" and
                                                     event.get("exception") != plan[index][4]):
                        raise ValueError(f"{kind} exact selector mismatch at {index}")
                    if kind == "FAULT_APPLIED" and event.get("marker", "").startswith("RPC_"):
                        if not peer or event.get("peerPort") != peer:
                            raise ValueError("fault RPC does not reach actual NN peer")
                        endpoint = event.get("endpoint", "")
                        if endpoint.startswith("nn0<-dn"):
                            actor = binding.get(event.get("threadId"))
                            if not actor:
                                raise ValueError("fault has no same-thread DN binding")
                            uuid, pool, role = actor
                            if (roles.get(uuid) != role or pool != bp or
                                    endpoint != "nn0<-" + role or
                                    event.get("sourceUuid") != uuid or
                                    event.get("blockPoolId") != bp):
                                raise ValueError("fault physical DN UUID/BP/role mismatch")
                            if event.get("api", "").startswith("DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"):
                                m = re.search(r"blocks=\[([0-9, ]+)\]", event["api"])
                                if not m or str(block) not in m.group(1).split(", "):
                                    raise ValueError("fault not for target block")
                        elif endpoint == "nn0<-client":
                            if (event.get("api", "").startswith("ClientNamenodeProtocolTranslatorPB.append") and
                                    event["api"] != f"ClientNamenodeProtocolTranslatorPB.append[append:{path}]"):
                                raise ValueError("client fault not for target file")
                        else:
                            raise ValueError("unknown RPC actor endpoint")
                    selected.append(event)
            if len(roles) != 4 or set(roles.values()) != {"dn0", "dn1", "dn2", "dn3"}:
                raise ValueError("incomplete four-DN UUID/role map")
            exact_applied = len(applied) == len(plan) and len(matched) == len(plan)
            if exact_applied and any(a["seq"] > b["seq"] for a, b in zip(matched, applied)):
                raise ValueError("fault matched after applied")
            fully_applied += exact_applied
            last = applied[-1]["seq"] if applied else -1
            guards = [e for e in trace if e.get("event") == "TARGET_GUARD" and
                      e.get("seq", -1) > last and e.get("site") == TARGET and
                      e.get("path") == path and e.get("blockId") == block]
            if not applied:
                guards = []
            independent_effective = exact_applied and bool(guards)
            audited_effective += independent_effective
            committed = {(g.get("threadId"), g.get("ordinal")) for g in guards if g.get("committed")}
            exceptions = [e for e in trace if e.get("event") == "TARGET_EXCEPTION" and
                          e.get("seq", -1) > last and e.get("site") == TARGET and
                          e.get("path") == path and e.get("blockId") == block and
                          e.get("type") == "org.apache.hadoop.ipc.RetriableException" and
                          (e.get("threadId"), e.get("ordinal")) in committed]
            if independent_effective and exceptions:
                candidates.append(run_id)
                if not row["candidate"]:
                    missed_candidates.append(run_id)
            if independent_effective != row["effective"]:
                raise ValueError("recomputed target/effective receipt mismatch")
            if independent_effective and len(exceptions) != row["receipt"]["postfault_target_exceptions"]:
                raise ValueError("recomputed postfault target exception receipt mismatch")
            current = lines(run / "coverage.tsv")
            gain = current - coverage_union if independent_effective else set()
            observed_io = {"\t".join(str(e[k]) for k in ("marker", "api", "endpoint"))
                           for e in trace if relevant(e, path, block)}
            new_io = observed_io - io_union if independent_effective else set()
            if (set(row["new_coverage_ids"]) != gain or
                    set(row["new_io_family_ids"]) != new_io):
                raise ValueError("recomputed JaCoCo or I/O feedback differs")
            if independent_effective:
                coverage_union.update(current)
                io_union.update(observed_io)
            if read_json(run / "trial-result.json") != row:
                raise ValueError("immutable trial-result/checkpoint mismatch")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"{run_id}: {error}")
    if set(state["coverage_union"]) != coverage_union:
        errors.append("checkpoint production JaCoCo union differs from raw")
    if set(state["io_union"]) != io_union:
        errors.append("checkpoint actor-aware I/O union differs from raw")
    return {"case": "HDFS-39", "completed_snapshot": len(completed),
            "current_at_snapshot": state["current"] and state["current"].get("run_id"),
            "recomputed_fully_applied": fully_applied,
            "recomputed_effective": audited_effective,
            "recomputed_coverage_ids": len(coverage_union),
            "recomputed_io_families": len(io_union),
            "postfault_target_exception_runs": candidates,
            "missed_candidate_labels": missed_candidates,
            "errors": errors, "pass": not errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.evidence)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["pass"] else 1)
