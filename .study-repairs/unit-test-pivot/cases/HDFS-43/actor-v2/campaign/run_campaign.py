#!/usr/bin/env python3
"""Resumable actor-aware HDFS-43 original-JUnit coverage and I/O campaign."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time

CASE = Path(__file__).resolve().parents[1]
TOP = CASE.parent
CAMP = CASE / "campaign"
SEED = CASE / "healthy/actor-seed"
STATE = CAMP / "checkpoint.json"
LEDGER = CAMP / "trial-ledger.csv"
REMOTE_ROOT = Path("/users/ZhenyuLi/hdfs43-actor-v2")
REMOTE = "ZhenyuLi@node2"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", REMOTE]
RSYNC = ["rsync", "-a", "-e",
         "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"]
TEST = "org.apache.hadoop.hdfs.server.namenode.TestFileTruncate#testTruncateTwiceTogether"
SITE = "FSDirTruncateOp.truncate:113-117"
PATH = "/testTruncateTwiceTogether/file"
SELECTOR = ("marker", "api", "endpoint", "sourceRole", "path", "blockId",
            "requestedLength", "ordinal", "exception")
POINT = SELECTOR[:-1]
EXCEPTIONS = ("IOException", "SocketTimeoutException", "EOFException")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temp.open("w") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    if [row.get("seq") for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"noncontiguous raw trace: {path}")
    return rows


def covered(path: Path) -> set[str]:
    return set(path.read_text().splitlines()) if path.is_file() else set()


def selector(row: dict, exception: str) -> dict:
    return {**{key: row[key] for key in POINT}, "exception": exception}


def sequence_id(sequence: list[dict]) -> str:
    return digest(json.dumps(sequence, sort_keys=True,
                             separators=(",", ":")).encode())[:20]


def point_id(row: dict) -> str:
    return "|".join(str(row.get(key)) for key in POINT)


def family_id(row: dict) -> str:
    return "|".join(str(row.get(key)) for key in
                    ("marker", "api", "endpoint", "sourceRole", "path", "blockId"))


def roles(rows: list[dict]) -> dict[str, str]:
    return {row["role"]: row["sourceUuid"] for row in rows
            if row.get("event") == "DN_ROLE_MAP"}


def guard(row: dict) -> bool:
    return (row.get("event") == "TARGET_GUARD" and row.get("site") == SITE
            and row.get("path") == PATH and
            row.get("state") == "UNDER_RECOVERY" and
            row.get("phase") == "secondTruncate" and
            isinstance(row.get("blockId"), int) and row["blockId"] >= 0)


def io_eligible(row: dict, target: dict, mapping: dict[str, str]) -> bool:
    if row.get("event") != "IO_OBSERVED" or row.get("marker") != "RPC_RESPONSE_WAIT":
        return False
    if row.get("endpoint") != "nn0" or row.get("seq", 0) >= target["seq"]:
        return False
    if not row.get("rpcKey") or row["rpcKey"].endswith(":-1"):
        return False
    if row.get("api") == "truncate":
        return (row.get("sourceRole") == "client" and row.get("sourceUuid") == ""
                and row.get("path") == target["path"] and
                row.get("requestedLength") in
                (target["requestedLength"], target["inProgressLength"]))
    if row.get("api") == "blockReceivedAndDeleted":
        role = row.get("sourceRole")
        return (role in mapping and row.get("sourceUuid") == mapping[role]
                and row.get("blockId") in
                (target["blockId"], target["truncateBlockId"]))
    return False


def relationship(fault: dict, target: dict, mapping: dict[str, str]) -> str | None:
    if fault.get("endpoint") != "nn0" or fault.get("seq", -1) >= target["seq"]:
        return None
    if fault.get("api") == "truncate":
        if fault.get("sourceRole") != "client" or fault.get("path") != target["path"]:
            return None
        if fault.get("requestedLength") == target["requestedLength"]:
            return ("same_rpc" if fault.get("rpcKey") == target.get("rpcKey")
                    else None)
        if (fault.get("requestedLength") == target["inProgressLength"] and
                fault.get("phase") == "firstTruncate"):
            return "same_file_precursor"
        return None
    if fault.get("api") == "blockReceivedAndDeleted":
        role = fault.get("sourceRole")
        if (role in mapping and fault.get("sourceUuid") == mapping[role]
                and fault.get("blockId") in
                (target["blockId"], target["truncateBlockId"])):
            return "same_block_report"
    return None


def enqueue(state: dict, sequence: list[dict], reason: str, score: int) -> None:
    identifier = sequence_id(sequence)
    if identifier in state["seen"] or len(state["queue"]) >= 5000:
        return
    state["seen"].append(identifier)
    state["queue"].append({"id": identifier, "sequence": sequence,
                           "target": state["healthy_target"],
                           "reason": reason, "score": score,
                           "queued_at": len(state["completed"])})


def initial_state() -> dict:
    if STATE.is_file():
        state = read(STATE)
        if state.get("case_id") != "HDFS-43" or state.get("test") != TEST:
            raise RuntimeError("wrong case checkpoint")
        if state.get("source_build_sha256") != digest(
                (CASE / "system-test/build-probe.json").read_bytes()):
            raise RuntimeError("instrumentation receipt changed after seed checkpoint")
        return state
    manifest = read(SEED / "manifest.json")
    rows = events(SEED / "trace/runtime_trace.jsonl")
    targets = [row for row in rows if guard(row)]
    mapping = roles(rows)
    if (manifest["test"] != TEST or manifest["exit"] != 0 or len(targets) != 1
            or targets[0].get("equal") is not False or
            set(mapping) != {"dn0", "dn1", "dn2"} or
            len(set(mapping.values())) != 3):
        raise RuntimeError("healthy original JUnit or actor calibration failed")
    target = targets[0]
    throws = [row for row in rows if row.get("event") == "TARGET_EXCEPTION"
              and row.get("rpcKey") == target.get("rpcKey") and
              row.get("blockId") == target.get("blockId")]
    if (len(throws) != 1 or throws[0].get("type") !=
            "org.apache.hadoop.hdfs.protocol.AlreadyBeingCreatedException"):
        raise RuntimeError("healthy target exception is not the original expected one")
    if not any(row.get("event") == "IO_OBSERVED" and
               row.get("api") == "truncate" and
               row.get("requestedLength") == target["requestedLength"] and
               row.get("rpcKey") == target["rpcKey"]
               for row in rows):
        raise RuntimeError("client truncate RPC and server guard have no shared request key")
    points = [row for row in rows if io_eligible(row, target, mapping)]
    if not points:
        raise RuntimeError("healthy target has no actor-resolved I/O")
    source_digest = digest((CASE / "system-test/build-probe.json").read_bytes())
    state = {"schema_version": 2, "case_id": "HDFS-43", "test": TEST,
             "started_at_utc": now(), "source_build_sha256": source_digest,
             "healthy_target": {key: target[key] for key in
                                ("path", "blockId", "truncateBlockId",
                                 "requestedLength", "inProgressLength")},
             "healthy_target_checks": len(targets), "healthy_relevant_io": len(points),
             "budget": {"max_attempts": 80, "max_faults": 8},
             "extension": {"max_attempts": 128, "max_faults": 10},
             "extended": False, "active": None, "queue": [], "seen": [],
             "completed": [], "stop_reason": None}
    for row in sorted(points, key=lambda p: (p["api"] != "blockReceivedAndDeleted",
                                            target["seq"] - p["seq"])):
        for exception in EXCEPTIONS:
            enqueue(state, [selector(row, exception)],
                    f"healthy I/O seq {row['seq']}",
                    300 if row["api"] == "blockReceivedAndDeleted" else 240)
    atomic_json(STATE, state)
    return state


def remote_exists(path: Path) -> bool:
    return subprocess.run(SSH + ["test", "-f", str(path)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def command(args: list[str], log: Path | None = None) -> None:
    if log is None:
        subprocess.run(args, check=True)
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True)


def fetch(remote: Path, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    command(RSYNC + [f"{REMOTE}:{remote}", str(local)])


def prepare_remote() -> None:
    # Build once before any trial; after that the checkpoint pins the classes.
    if STATE.is_file() and read(STATE).get("completed"):
        return
    command(SSH + ["mkdir", "-p", str(REMOTE_ROOT / "system-test"),
                   str(REMOTE_ROOT / "source")])
    command(RSYNC + [str(CASE / "source") + "/",
                     f"{REMOTE}:{REMOTE_ROOT / 'source'}/"])
    for name in ("Probe.java", "CoverageDump.java", "RunJUnitMethod.java",
                 "OfflineProbeSmoke.java", "build_probe.py", "run_original.py",
                 "run_coverage.py"):
        command(RSYNC + [str(CASE / "system-test" / name),
                         f"{REMOTE}:{REMOTE_ROOT / 'system-test' / name}"])
    if not remote_exists(REMOTE_ROOT / "system-test/build-probe.json"):
        command(SSH + ["python3", str(REMOTE_ROOT / "system-test/build_probe.py")],
                CAMP / "remote-build.log")
    fetch(REMOTE_ROOT / "system-test/build-probe.json",
          CASE / "remote-build-probe.json")
    remote_build = read(CASE / "remote-build-probe.json")
    local_build = read(CASE / "system-test/build-probe.json")
    if (remote_build["exit"] != 0 or
            remote_build["generated_sources"] != local_build["generated_sources"] or
            remote_build["original_sources"] != local_build["original_sources"]):
        raise RuntimeError("remote actor probes failed to build")


def run_artifacts(name: str, plan: Path | None = None) -> tuple[Path, dict, float]:
    out = CASE / name
    out.mkdir(parents=True, exist_ok=True)
    remote_out = REMOTE_ROOT / name
    remote_plan = None
    if plan:
        remote_plan = REMOTE_ROOT / "campaign/plans" / plan.name
        command(SSH + ["mkdir", "-p", str(remote_plan.parent)])
        command(RSYNC + [str(plan), f"{REMOTE}:{remote_plan}"])
    started = time.monotonic()
    if not remote_exists(remote_out / "manifest.json"):
        if (remote_exists(remote_out / "jacoco.exec") or
                remote_exists(remote_out / "trace/runtime_trace.jsonl")):
            raise RuntimeError("partial prior JUnit evidence exists without manifest; "
                               "inspect it before any replay")
        arguments = SSH + ["python3", str(REMOTE_ROOT / "system-test/run_original.py"),
                           "--method", "testTruncateTwiceTogether", "--name", name,
                           "--timeout-seconds", "240"]
        if remote_plan:
            arguments += ["--plan", str(remote_plan)]
        command(arguments, out / "driver.log")
    if (remote_exists(remote_out / "jacoco.exec") and
            not remote_exists(remote_out / "coverage.tsv")):
        command(SSH + ["python3", str(REMOTE_ROOT / "system-test/run_coverage.py"),
                       "--exec", str(remote_out / "jacoco.exec"), "--output",
                       str(remote_out / "coverage.tsv")], out / "coverage-driver.log")
    for filename in ("manifest.json", "trace/runtime_trace.jsonl",
                     "jacoco.exec", "coverage.tsv"):
        source = remote_out / filename
        if remote_exists(source):
            fetch(source, out / filename)
    remote_log = remote_out / "logs/runtime.log"
    if remote_exists(remote_log) and not (out / "junit.log.gz").exists():
        with (out / "junit.log.gz").open("wb") as stream:
            subprocess.run(SSH + ["gzip", "-c", str(remote_log)],
                           stdout=stream, check=True)
    manifest = read(out / "manifest.json")
    if manifest.get("test") != TEST:
        raise RuntimeError("remote run used a different original JUnit")
    return out, manifest, max(time.monotonic() - started,
                               manifest["elapsed_seconds"])


def ensure_seed() -> None:
    required = ("manifest.json", "trace/runtime_trace.jsonl", "jacoco.exec",
                "coverage.tsv")
    if all((SEED / name).is_file() for name in required):
        return
    prepare_remote()
    out, manifest, _ = run_artifacts("healthy/actor-seed")
    if manifest["exit"] != 0:
        raise RuntimeError(f"original healthy JUnit failed; see {out}")


def analyze(number: int, item: dict, out: Path, manifest: dict,
            seconds: float, coverage_union: set[str], io_union: set[str],
            family_union: set[str]) -> dict:
    rows = events(out / "trace/runtime_trace.jsonl")
    mapping = roles(rows)
    selected = item["sequence"]
    matched = [row for row in rows if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in rows if row.get("event") == "FAULT_APPLIED"]
    requested = [tuple(p[k] for k in SELECTOR) for p in selected]
    actual = [tuple(p.get(k) for k in SELECTOR) for p in applied]
    mapped = set(mapping) == {"dn0", "dn1", "dn2"} and len(set(mapping.values())) == 3
    physical = all(p.get("sourceRole") == "client" and not p.get("sourceUuid")
                   if p.get("api") == "truncate" else
                   p.get("sourceRole") in mapping and
                   p.get("sourceUuid") == mapping[p["sourceRole"]]
                   for p in applied)
    strict = (requested == actual and len(matched) == len(requested)
              and mapped and physical)
    after = max((p["seq"] for p in applied), default=-1)
    target_options = [p for p in rows if guard(p) and p["seq"] > after >= 0
                      and p["path"] == PATH and
                      p["blockId"] == item["target"]["blockId"]]
    linked: list[str] = []
    target = None
    for candidate in target_options:
        relations = [relationship(p, candidate, mapping) for p in applied]
        if all(relations):
            target = candidate
            linked = [str(x) for x in relations]
            break
    valid = strict and target is not None
    exceptions = [p for p in rows if p.get("event") == "TARGET_EXCEPTION"
                  and target is not None and p["seq"] > target["seq"]
                  and p.get("path") == target["path"]
                  and p.get("blockId") == target["blockId"]
                  and p.get("rpcKey") == target["rpcKey"]
                  and p.get("ordinal") == target["ordinal"]]
    expected = (valid and target.get("equal") is False and
                len(exceptions) == 1 and exceptions[0].get("type") ==
                "org.apache.hadoop.hdfs.protocol.AlreadyBeingCreatedException" and
                "is being truncated" in exceptions[0].get("message", ""))
    candidate = valid and not expected
    status = ("unmatched_or_partial" if not strict else
              "lost_target_or_actor" if not valid else
              "target_outcome_candidate" if candidate else
              "workload_timeout" if manifest["exit"] == 124 else "checked")
    coverage_ids = covered(out / "coverage.tsv")
    new_coverage = coverage_ids - coverage_union if valid else set()
    observed = [p for p in rows if p.get("event") == "IO_OBSERVED" and
                p.get("marker") == "RPC_RESPONSE_WAIT"]
    new_io = {point_id(p) for p in observed} - io_union if valid else set()
    new_family = {family_id(p) for p in observed} - family_union if valid else set()
    result = {"trial": number, "id": f"trial-{number:03d}",
              "sequence_id": item["id"], "selection_reason": item["reason"],
              "sequence": selected, "requested_faults": len(selected),
              "matched_faults": len(matched), "applied_faults": len(applied),
              "strict_injection": strict, "role_map_confirmed": mapped,
              "physical_source_confirmed": physical,
              "last_applied_seq": after,
              "target_after_fault_same_actor": valid,
              "post_fault_target_guard": target,
              "fault_target_relationships": linked,
              "post_fault_target_exception_count": len(exceptions),
              "expected_original_guard_response": expected,
              "status": status, "bug_mark": "candidate" if candidate else "none",
              "junit_exit": manifest["exit"],
              "junit_elapsed_seconds": manifest["elapsed_seconds"],
              "elapsed_seconds": round(seconds, 3),
              "coverage_ids": len(coverage_ids),
              "coverage_tsv_sha256": digest((out / "coverage.tsv").read_bytes())
              if (out / "coverage.tsv").is_file() else None,
              "new_coverage_ids": sorted(new_coverage),
              "new_coverage_count": len(new_coverage),
              "new_io_point_ids": sorted(new_io),
              "new_io_family_ids": sorted(new_family),
              "trace": str(out / "trace/runtime_trace.jsonl"),
              "jacoco": str(out / "jacoco.exec"),
              "junit_log_gzip": str(out / "junit.log.gz"),
              "manifest": str(out / "manifest.json"),
              "completed_at_utc": now()}
    atomic_json(out / "trial-result.json", result)
    return result


def mutate(state: dict, row: dict) -> None:
    if not row["target_after_fault_same_actor"]:
        return
    if len(row["sequence"]) >= state["budget"]["max_faults"]:
        return
    rows = events(Path(row["trace"]))
    target = row["post_fault_target_guard"]
    mapping = roles(rows)
    after = row["last_applied_seq"]
    points = [p for p in rows if after < p["seq"] < target["seq"] and
              io_eligible(p, target, mapping)]
    points.sort(key=lambda p: (p["api"] != "blockReceivedAndDeleted",
                               target["seq"] - p["seq"]))
    families: set[str] = set()
    for point in points:
        family = family_id(point)
        if family in families:
            continue
        families.add(family)
        for exception in EXCEPTIONS:
            enqueue(state, row["sequence"] + [selector(point, exception)],
                    f"mutation of {row['id']}",
                    175 + 20 * len(row["sequence"]) +
                    min(row["new_coverage_count"], 30) +
                    (60 if point["api"] == "blockReceivedAndDeleted" else 0))
        if len(families) >= 6:
            break


def choose(state: dict) -> dict:
    queue = state["queue"]
    age = len(state["completed"])
    ranked = sorted(queue, key=lambda item: -(
        item["score"] + min(age - item["queued_at"], 80)))
    top = ranked[:min(16, len(ranked))]
    rng = random.Random(0x430043 + age)
    weights = [max(1, item["score"] - top[-1]["score"] + 10) for item in top]
    selected = rng.choices(top, weights=weights, k=1)[0]
    queue.remove(selected)
    return selected


def publish(state: dict, union: set[str], seed: set[str]) -> None:
    completed = state["completed"]
    valid = [r for r in completed if r["target_after_fault_same_actor"]]
    delta = union - seed
    gain = {kind: sum(identifier.startswith(kind + "\t") for identifier in delta)
            for kind in ("METHOD", "BRANCH_UNIT", "PROBE")}
    result = {"case_id": "HDFS-43", "status": (
                  "candidate_review" if any(r["bug_mark"] == "candidate"
                                            for r in completed) else
                  "pending_final_audit" if state["stop_reason"] else "fuzzing"),
              "methodology": "original_embedded_cluster_junit_actor_aware_source_probes",
              "cluster_test": TEST,
              "target_source_file": "hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp.java",
              "target_function": "FSDirTruncateOp.truncate",
              "target_code": "newLength == truncateLength for a block UNDER_RECOVERY",
              "target_site": SITE, "healthy_target": state["healthy_target"],
              "fault_trials": len(completed),
              "fully_applied_trials": sum(r["strict_injection"] for r in completed),
              "target_after_fault": len(valid),
              "target_exception_after_fault": sum(
                  bool(r["post_fault_target_exception_count"]) for r in valid),
              "expected_original_guard_response_trials": sum(
                  r["expected_original_guard_response"] for r in valid),
              "coverage_gain": gain, "bug_mark": (
                  "candidate" if any(r["bug_mark"] == "candidate"
                                     for r in completed) else "none"),
              "elapsed_seconds": round(read(SEED / "manifest.json")[
                  "elapsed_seconds"] + sum(r["elapsed_seconds"]
                                            for r in completed), 3),
              "budget": state["budget"], "extended": state["extended"],
              "stop_reason": state["stop_reason"],
              "checkpoint": str(STATE), "ledger": str(LEDGER),
              "updated_at_utc": now(),
              "legacy_no_actor_trials_excluded": 80,
              "legacy_equal_branch_trials_excluded": 128}
    atomic_json(CASE / "result.json", result)
    fields = ("trial", "id", "status", "requested_faults", "matched_faults",
              "applied_faults", "strict_injection", "target_after_fault_same_actor",
              "post_fault_target_exception_count", "junit_exit", "elapsed_seconds",
              "new_coverage_count", "new_io_family_ids", "bug_mark", "sequence_id")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in completed:
        values = {key: row.get(key, "") for key in fields}
        values["new_io_family_ids"] = ";".join(row["new_io_family_ids"])
        writer.writerow(values)
    atomic_text(LEDGER, buffer.getvalue())


def main() -> None:
    ensure_seed()
    state = initial_state()
    seed_cov = covered(SEED / "coverage.tsv")
    coverage_union = set(seed_cov)
    seed_events = events(SEED / "trace/runtime_trace.jsonl")
    io_union = {point_id(p) for p in seed_events if p.get("event") == "IO_OBSERVED"}
    family_union = {family_id(p) for p in seed_events if p.get("event") == "IO_OBSERVED"}
    for row in state["completed"]:
        coverage_union.update(row["new_coverage_ids"])
        io_union.update(row["new_io_point_ids"])
        family_union.update(row["new_io_family_ids"])
    publish(state, coverage_union, seed_cov)
    stop_after = int(os.environ.get("HDFS43_STOP_AFTER", "0"))
    while (state["active"] is not None or state["queue"]) and not state["stop_reason"]:
        if (CAMP / "pause.request").exists():
            state["stop_reason"] = "paused_by_case_owner"
            break
        if shutil.disk_usage(CASE).free < 1024 ** 3:
            state["stop_reason"] = "local_disk_below_1GiB"
            break
        if len(state["completed"]) >= state["budget"]["max_attempts"]:
            recent = state["completed"][-8:]
            novelty = any(r["target_after_fault_same_actor"] and (
                any(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t", "PROBE\t"))
                    for identifier in r["new_coverage_ids"]) or
                r["new_io_family_ids"]) for r in recent)
            if not state["extended"] and novelty:
                state["budget"] = dict(state["extension"])
                state["extended"] = True
                state["extension_reason"] = "production coverage or stable I/O family in chronological trials 73-80"
                atomic_json(STATE, state)
            else:
                state["stop_reason"] = "attempt_budget_reached"
                break
        if state["active"] is None:
            state["active"] = choose(state)
            atomic_json(STATE, state)
        number = len(state["completed"]) + 1
        item = state["active"]
        name = f"trial-{number:03d}"
        plan = CAMP / "plans" / (name + ".tsv")
        body = "".join("\t".join(str(point[key]) for key in SELECTOR) + "\n"
                       for point in item["sequence"])
        if plan.is_file() and plan.read_text() != body:
            raise RuntimeError("resumed selector plan changed")
        if not plan.is_file():
            atomic_text(plan, body)
        out, manifest, seconds = run_artifacts("campaign/" + name, plan)
        trial_file = out / "trial-result.json"
        row = (read(trial_file) if trial_file.is_file() else
               analyze(number, item, out, manifest, seconds, coverage_union,
                       io_union, family_union))
        state["completed"].append(row)
        state["active"] = None
        coverage_union.update(row["new_coverage_ids"])
        io_union.update(row["new_io_point_ids"])
        family_union.update(row["new_io_family_ids"])
        mutate(state, row)
        atomic_json(STATE, state)
        publish(state, coverage_union, seed_cov)
        export = out / "coverage.tsv"
        if export.is_file():
            with gzip.open(out / "coverage.tsv.gz", "wb", 6) as zipped:
                zipped.write(export.read_bytes())
            export.unlink()
        print(json.dumps({"trial": number, "status": row["status"],
                          "strict": row["strict_injection"],
                          "target_after": row["target_after_fault_same_actor"],
                          "coverage_gain": row["new_coverage_count"],
                          "seconds": row["elapsed_seconds"]}), flush=True)
        if row["bug_mark"] == "candidate":
            state["stop_reason"] = "candidate_requires_replay_source_review"
            break
        if stop_after and len(state["completed"]) >= stop_after:
            print(json.dumps({"clean_pause_after": stop_after}), flush=True)
            return
    if not state["stop_reason"]:
        state["stop_reason"] = "observed_actor_io_queue_exhausted"
    atomic_json(STATE, state)
    publish(state, coverage_union, seed_cov)


if __name__ == "__main__":
    main()
