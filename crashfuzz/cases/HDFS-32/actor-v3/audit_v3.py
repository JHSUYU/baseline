#!/usr/bin/env python3
"""Independent raw audit of the HDFS-32 actor-bound campaign."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
METRICS = ("probes", "methods", "branch_counts")
ACTOR = "episode1/dn1"
SERVICE = "namesServerId1"
TEST = "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDeleteBlockPool"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(directory: Path) -> list[dict]:
    path = directory / "runtime_trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def covered(directory: Path, metric: str) -> set[str]:
    path = directory / ("covered_" + metric + ".txt")
    return set(path.read_text().splitlines()) if path.is_file() else set()


def pool(events: list[dict]) -> str | None:
    ns = {e.get("rawBpid") for e in events if e.get("event") == "NN_POOL"
          and e.get("nnIndex") == "0" and e.get("service") == SERVICE
          and e.get("rawBpid")}
    if len(ns) == 1:
        return next(iter(ns))
    bp = {e.get("rawBpid") for e in events
          if e.get("event") in ("BP_ACTOR_BEGIN", "POOL_ADD")
          and e.get("actor") == ACTOR and e.get("service") == SERVICE
          and e.get("rawBpid")}
    return next(iter(bp)) if len(bp) == 1 else None


def physical(event: dict, events: list[dict], bpid: str | None) -> bool:
    if not bpid or event.get("event") != "IO_OBSERVED" or event.get("bound") != "true":
        return False
    if (event.get("actor") != ACTOR or event.get("service") != SERVICE
            or event.get("rawBpid") != bpid or not event.get("uuid")):
        return False
    if event.get("marker") == "RPC":
        return any(e.get("event") == "BP_ACTOR_BEGIN" and e.get("seq", 0) < event["seq"]
                   and e.get("actor") == ACTOR and e.get("service") == SERVICE
                   and e.get("nnEndpoint") == event.get("rawEndpoint")
                   for e in events)
    if event.get("marker") == "FILE":
        return any(e.get("event") == "DATASET_MAP" and e.get("seq", 0) < event["seq"]
                   and e.get("actor") == ACTOR
                   and e.get("uuid") == event.get("uuid")
                   and e.get("datasetId") == event.get("datasetId")
                   for e in events)
    return False


def selected(events: list[dict]) -> dict | None:
    checks = [e for e in events if e.get("event") == "TARGET_CHECK"
              and e.get("selected") == "true"]
    return checks[0] if len(checks) == 1 else None


def signature(events: list[dict], check: dict) -> dict:
    throws = [e for e in events if e.get("event") == "TARGET_THROW"
              and e.get("selected") == "true" and e.get("seq", 0) > check["seq"]
              and e.get("actor") == check.get("actor")
              and e.get("uuid") == check.get("uuid")
              and e.get("rawBpid") == check.get("rawBpid")]
    return {"actor": check["actor"], "service": check["service"],
            "force": check["force"], "present": check["present"],
            "throws": [[e["type"], e["message"]] for e in throws]}


def family(event: dict) -> str:
    return "|".join(event.get(key, "") for key in ("marker", "api", "actor", "service"))


def trace_ordinal_errors(events: list[dict]) -> list[str]:
    seen: Counter[tuple[str, ...]] = Counter()
    errors = []
    for event in events:
        if event.get("event") != "IO_OBSERVED":
            continue
        key = tuple(event.get(k, "") for k in ("marker", "api", "actor", "service"))
        seen[key] += 1
        if event.get("ordinal") != str(seen[key]):
            errors.append(f"I/O ordinal mismatch at seq {event.get('seq')}")
    return errors


def main() -> int:
    state_file = HERE / "checkpoint.json"
    state = json.loads(state_file.read_text())
    errors: list[str] = []
    if state.get("schema") != 1 or state.get("case") != "HDFS-32":
        errors.append("checkpoint schema/case mismatch")
    baseline = {metric: set() for metric in METRICS}
    base_io = set()
    healthy = []
    provenance_fields = ("original_test_jar_sha256", "original_hdfs_jar_sha256",
                         "original_common_jar_sha256", "classpath_sha256")
    for suffix in ("a", "b"):
        directory = HERE / ("healthy-" + suffix)
        manifest = json.loads((directory / "manifest.json").read_text())
        if sha(directory / "manifest.json") != state["healthy_manifest_sha256"][len(healthy)]:
            errors.append("healthy manifest hash mismatch " + suffix)
        events = rows(directory)
        check = selected(events)
        bpid = pool(events)
        if (manifest.get("junit_exit") != 0 or manifest.get("test") != TEST
                or manifest.get("build") != state["build"]
                or check is None or bpid is None or check.get("actor") != ACTOR
                or check.get("rawBpid") != bpid or check.get("present") != "true"
                or check.get("force") != "true"
                or not any(e.get("event") == "CLUSTER_DN_LIST"
                           and e.get("actors") == "episode1/dn0,episode1/dn1"
                           for e in events)):
            errors.append("healthy actor/target mismatch " + suffix)
        elif signature(events, check) != state["healthy_signature"]:
            errors.append("healthy target signature mismatch " + suffix)
        if [e.get("seq") for e in events] != list(range(1, len(events) + 1)):
            errors.append("healthy trace gap " + suffix)
        errors.extend("healthy " + suffix + " " + message
                      for message in trace_ordinal_errors(events))
        for metric in METRICS:
            if not (directory / ("covered_" + metric + ".txt")).is_file():
                errors.append("healthy missing " + metric + " feedback " + suffix)
            baseline[metric] |= covered(directory, metric)
        if check and bpid:
            base_io |= {family(e) for e in events
                        if e.get("seq", 0) < check["seq"] and physical(e, events, bpid)}
        healthy.append(manifest)
    for key in provenance_fields:
        if healthy[0].get(key) != healthy[1].get(key):
            errors.append("healthy JAR/classpath mismatch " + key)
    for metric in METRICS:
        if baseline[metric] != set(state["healthy_coverage"][metric]):
            errors.append("healthy coverage union mismatch " + metric)
    if base_io != set(state["healthy_io_families"]):
        errors.append("healthy I/O family union mismatch")
    cv_union = {metric: set(baseline[metric]) for metric in METRICS}
    io_union = set(base_io)
    strict = effective = 0
    candidates = []
    total_seconds = 0.0
    for number, trial in enumerate(state["completed"], 1):
        directory = HERE / "runs" / ("trial-%04d" % number)
        if Path(trial["run"]).resolve() != directory.resolve():
            errors.append(f"trial {number} path/order mismatch"); continue
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
            events = rows(directory)
            plan = (directory / "fault-plan.tsv").read_text().splitlines()
        except (FileNotFoundError, json.JSONDecodeError) as error:
            errors.append(f"trial {number} missing raw: {error}"); continue
        if [e.get("seq") for e in events] != list(range(1, len(events) + 1)):
            errors.append(f"trial {number} trace gap")
        errors.extend(f"trial {number} {message}"
                      for message in trace_ordinal_errors(events))
        expected = ["\t".join(p[key] for key in
                    ("marker", "api", "actor", "service", "ordinal", "exception"))
                    for p in trial["sequence"]]
        if plan != expected:
            errors.append(f"trial {number} plan differs")
        bpid = pool(events)
        matched = [e for e in events if e.get("event") == "FAULT_MATCHED"]
        applied = [e for e in events if e.get("event") == "FAULT_APPLIED"]
        exact = len(matched) == len(applied) == len(trial["sequence"])
        if exact:
            for i, p in enumerate(trial["sequence"]):
                a, m = applied[i], matched[i]
                prior = next((e for e in events if e.get("seq") == a["seq"] - 2), {})
                exact &= (m["seq"] < a["seq"] and a.get("planIndex") == str(i)
                          and m.get("planIndex") == str(i)
                          and all(a.get(k) == m.get(k) == p[k] for k in
                                  ("marker", "api", "actor", "service", "ordinal"))
                          and a.get("exception") == m.get("exception") == p["exception"]
                          and a.get("rawBpid") == bpid and physical(prior, events, bpid)
                          and all(a.get(k) == m.get(k) == prior.get(k) for k in
                                  ("uuid", "rawBpid", "rawEndpoint", "datasetId", "blockId")))
                if i:
                    exact &= applied[i - 1]["seq"] < m["seq"]
        strict += bool(exact)
        if bool(exact) != trial["exact_order_applied"]:
            errors.append(f"trial {number} strict mismatch")
        last = applied[-1] if exact else None
        check = selected(events)
        retained = bool(last and check and check["seq"] > last["seq"]
                        and check.get("actor") == ACTOR
                        and check.get("rawBpid") == bpid
                        and check.get("uuid") == last.get("uuid"))
        effective += retained
        if retained != trial["post_fault_target"]:
            errors.append(f"trial {number} postfault target mismatch")
        observed = signature(events, check) if retained else None
        if observed != trial["target_signature"]:
            errors.append(f"trial {number} target outcome mismatch")
        candidate = bool(retained and observed != state["healthy_signature"])
        if candidate != trial["candidate_needs_source_review"]:
            errors.append(f"trial {number} candidate mismatch")
        if candidate:
            candidates.append({"trial": number, "signature": observed})
        if manifest.get("build") != state["build"] or manifest.get("test") != TEST:
            errors.append(f"trial {number} source provenance mismatch")
        if any(manifest.get(key) != healthy[0].get(key) for key in provenance_fields):
            errors.append(f"trial {number} JAR/classpath provenance mismatch")
        if manifest.get("junit_exit") != trial["junit_exit"] or manifest.get("elapsed_seconds") != trial["elapsed_seconds"]:
            errors.append(f"trial {number} JUnit manifest mismatch")
        if sha(directory / "manifest.json") != trial["manifest_sha256"]:
            errors.append(f"trial {number} manifest hash mismatch")
        if (sha(directory / "runtime_trace.jsonl") if events else None) != trial["raw_trace_sha256"]:
            errors.append(f"trial {number} trace hash mismatch")
        for metric in METRICS:
            if retained and not (directory / ("covered_" + metric + ".txt")).is_file():
                errors.append(f"trial {number} missing {metric} feedback")
            gain = sorted(covered(directory, metric) - cv_union[metric]) if retained else []
            if gain != trial["coverage_gain"][metric]:
                errors.append(f"trial {number} {metric} feedback mismatch")
            if retained:
                cv_union[metric] |= covered(directory, metric)
        post = [e for e in events if retained and last["seq"] < e.get("seq", 0) < check["seq"]
                and physical(e, events, bpid)]
        novelty = sorted({family(e) for e in post} - io_union)
        if novelty != trial["new_io_families"]:
            errors.append(f"trial {number} I/O feedback mismatch")
        if retained:
            io_union |= {family(e) for e in post}
        total_seconds += manifest["elapsed_seconds"]
    for metric in METRICS:
        if cv_union[metric] != set(state["coverage"][metric]):
            errors.append("final coverage union mismatch " + metric)
    if io_union != set(state["io_families"]):
        errors.append("final I/O union mismatch")
    result = {"schema": 1, "checkpoint_sha256": sha(state_file),
              "attempts": len(state["completed"]), "strict": strict,
              "effective": effective, "goal": state["goal"],
              "candidate_reviews": candidates, "fault_junit_seconds": round(total_seconds, 3),
              "errors": errors, "raw_files_retained": True}
    pending = HERE / "audit-v3.json.tmp"
    pending.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    pending.replace(HERE / "audit-v3.json")
    print(json.dumps({"attempts": result["attempts"], "strict": strict,
                      "effective": effective, "candidates": len(candidates),
                      "errors": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
