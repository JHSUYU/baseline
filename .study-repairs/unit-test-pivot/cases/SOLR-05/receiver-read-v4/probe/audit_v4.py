#!/usr/bin/env python3
"""Reconstruct SOLR-05 V4 actor and version links from raw JVM events.

This reader imports neither the runtime probe nor the campaign scheduler.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
CONTEXT = ("collection", "shard", "replica", "core")
PATH = "/collections/testAddMultipleReplicas/state.json"
CALLER = "caller=org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_events(path: Path) -> list[dict]:
    result = []
    previous = 0
    for line in path.read_text().splitlines():
        part = line.split("\t")
        if len(part) < 4:
            raise ValueError("malformed trace row")
        seq = int(part[0])
        if seq != previous + 1:
            raise ValueError(f"nonconsecutive sequence: {previous} -> {seq}")
        previous = seq
        result.append({"seq": seq, "kind": part[2], "parts": part[3:],
                       "fields": dict(p.split("=", 1) for p in part[3:] if "=" in p)})
    return result


def semantic(event: dict, node_field: str = "node") -> tuple[str, ...]:
    f = event["fields"]
    return tuple(f.get(k, "") for k in (*CONTEXT, node_field))


def registrations(events: list[dict]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    roles = {}
    clients = {}
    for e in events:
        f = e["fields"]
        if e["kind"] == "JETTY_ROLE_BOUND":
            node, role = f["node"], f["role"]
            if (node in roles and roles[node] != role) or role in (
                    r for n, r in roles.items() if n != node):
                raise ValueError("ambiguous physical Jetty role")
            roles[node] = role
        if e["kind"] == "ACTOR_REGISTERED":
            key, value = f["client_id"], (f["node"], f["reader_id"])
            if key in clients and clients[key] != value:
                raise ValueError("ambiguous reader/client identity")
            clients[key] = value
    if len(roles) != 3 or len(clients) != 3:
        raise ValueError("expected three concrete embedded Solr nodes")
    return roles, clients


def observed_pairs(events: list[dict]) -> list[dict]:
    roles, clients = registrations(events)
    writes = {}
    last_io_by_thread = {}
    pairs = []
    for e in events:
        f, kind = e["fields"], e["kind"]
        if kind == "UPSTREAM_BATCH_AMBIGUOUS":
            raise ValueError("writer has ambiguous pending replica")
        if kind == "UPSTREAM_IO_OBSERVED" and e["parts"][0] == "STATE_SET_DATA_POST":
            if e["parts"][1] != PATH or int(f["zk_version"]) < 0:
                continue
            key = (f["collection"], f["zk_version"])
            if key in writes:
                raise ValueError("duplicate collection/version write")
            writes[key] = e
        elif kind == "RECEIVER_IO_OBSERVED":
            if e["parts"][:3] != ["STATE_GET_DATA_POST", PATH, CALLER]:
                raise ValueError("receiver hook has wrong I/O family")
            key = (f["collection"], f["zk_version"])
            write = writes.get(key)
            if write is None or write["seq"] >= e["seq"]:
                raise ValueError("receiver read lacks prior successful versioned write")
            wf = write["fields"]
            if (semantic(write, "target_node") != semantic(e) or
                    wf["writer_id"] != f["writer_id"] or
                    f["node"] != f["target_node"] or
                    clients.get(f["client_id"]) != (f["node"], f["reader_id"]) or
                    f["actor"] != "jetty:" + roles.get(f["node"], "")):
                raise ValueError("receiver read has wrong replica/host/client/reader")
            predecessor = last_io_by_thread.get(f.get("thread"))
            # The getData invocation can overlap the writer's setData response;
            # the returned Stat version, not entry order, establishes which
            # committed state it actually read.
            if (predecessor is None or
                    predecessor["kind"] != "IO_OBSERVED" or
                    predecessor["parts"][:2] != ["GET_DATA", PATH] or
                    not predecessor["fields"].get("caller", "").startswith(
                        CALLER.removeprefix("caller=") + ":") or
                    any(predecessor["fields"].get(k) != f.get(k) for k in
                        ("thread", "node", "client_id", "reader_id"))):
                raise ValueError("receiver hook lacks same-thread latest real getData")
            pairs.append({"write": write, "read": e})
        if kind in ("IO_OBSERVED", "UPSTREAM_IO_OBSERVED", "RECEIVER_IO_OBSERVED",
                    "IO_MATCHED", "IO_APPLIED_CONNECTION_LOSS") and f.get("thread"):
            last_io_by_thread[f["thread"]] = e
    return pairs


def healthy(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    log = (directory / "junit.log").read_text(errors="replace")
    if (manifest["exit_code"] != 0 or manifest["faults"] or
            "SOLR05_V4_JUNIT_RESULT run=1 failures=0 ignored=0" not in log or
            "SOLR05_V4_JUNIT_ASSUMPTION" in log):
        raise ValueError("healthy original JUnit did not pass")
    if manifest["original_classes"]:
        return {"name": directory.name, "original_classes": True,
                "elapsed_seconds": manifest["elapsed_seconds"],
                "junit_sha256": sha(directory / "junit.log")}
    events = trace_events(directory / "events.tsv")
    pairs = observed_pairs(events)
    targets = [e for e in events if e["kind"] == "TARGET_CHECK" and
               e["parts"][1] == "SOLR-05"]
    linked = {(semantic(p["read"]), p["write"]["fields"]["zk_version"])
              for p in pairs if any(t["seq"] > p["read"]["seq"] and
                                    semantic(t) == semantic(p["read"])
                                    for t in targets)}
    if len(targets) != 9 or len(linked) != 9 or any(
            e["kind"] == "TARGET_EXCEPTION" for e in events):
        raise ValueError("healthy receiver/target links incomplete")
    return {"name": directory.name, "original_classes": False,
            "elapsed_seconds": manifest["elapsed_seconds"],
            "state_writes": len({p["write"]["seq"] for p in pairs}),
            "receiver_reads": len(pairs), "targets": len(targets),
            "linked_replicas": len(linked),
            "trace_sha256": sha(directory / "events.tsv"),
            "junit_sha256": sha(directory / "junit.log"),
            "jacoco_sha256": sha(directory / "jacoco.exec")}


def trial(directory: Path, plan: list[str]) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["original_classes"] or manifest["faults"] != ";".join(plan):
        raise ValueError("trial manifest does not match fault plan")
    events = trace_events(directory / "events.tsv")
    pairs = observed_pairs(events)
    by_read = {p["read"]["seq"]: p for p in pairs}
    matched = [e for e in events if e["kind"] == "IO_MATCHED"]
    applied = [e for e in events if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    strict = len(matched) == len(applied) == len(plan)
    preceding = 0
    linked = []
    for index, selector in enumerate(plan):
        spec = selector.split("|")
        if len(spec) not in (9, 11) or not strict:
            strict = False
            break
        m, a = matched[index], applied[index]
        f = a["fields"]
        read = by_read.get(m["seq"] - 1)
        expected = [a["parts"][0], a["parts"][1],
                    "ordinal=" + spec[2], CALLER,
                    "actor=receiver_state_read_for_replica",
                    *(key + "=" + f.get(key, "") for key in CONTEXT)]
        if (m["seq"] + 1 != a["seq"] or m["parts"] != a["parts"] or
                read is None or a["parts"][:3] != expected[:3] or
                spec[:2] != a["parts"][:2] or spec[3:9] != expected[3:] or
                f.get("fault_id") != f"F{index}" or
                f.get("plan_index") != str(index) or
                f.get("previous_fault_id") != (f"F{index-1}" if index else "<none>") or
                semantic(read["read"]) != semantic(a) or
                int(f.get("zk_version", -1)) != int(read["write"]["fields"]["zk_version"])):
            strict = False
            break
        threshold = preceding if spec[2].startswith("@") else 0
        relevant = [p for p in pairs if threshold < p["read"]["seq"] <= m["seq"] and
                    p["read"]["parts"][:3] == [spec[0], spec[1], spec[3]] and
                    semantic(p["read"]) == semantic(a)]
        if len(relevant) != int(spec[2].lstrip("@")):
            strict = False
            break
        preceding = a["seq"]
        linked.append(read)
    final = applied[-1] if strict and applied else None
    last_read = linked[-1]["read"] if final else None
    targets = [e for e in events if final and e["seq"] > final["seq"] and
               e["kind"] == "TARGET_CHECK" and e["parts"][1] == "SOLR-05" and
               semantic(e) == semantic(last_read) and
               e["fields"].get("client_id") == last_read["fields"].get("client_id") and
               e["fields"].get("reader_id") == last_read["fields"].get("reader_id") and
               e["fields"].get("last_fault") == f"F{len(plan)-1}"]
    selected_target_seqs = {target["seq"] for target in targets}
    last_target_by_thread = {}
    exceptions = []
    for event in events:
        thread = event["fields"].get("thread")
        if event["kind"] == "TARGET_CHECK":
            last_target_by_thread[thread] = event
        elif event["kind"] == "TARGET_EXCEPTION" and thread:
            # Other JVM threads can log between the check and its throw. The
            # immediately preceding check on *this* thread must be the
            # selected post-fault guard, with the same physical reader.
            target = last_target_by_thread.get(thread)
            if (target is not None and target["seq"] in selected_target_seqs and
                    target["parts"][0] == "missing" and
                    event["parts"][0] == "SOLR-05" and
                    semantic(event) == semantic(target) and
                    all(event["fields"].get(k) == target["fields"].get(k) for k in
                        ("actor", "node", "client_id", "reader_id", "last_fault", "thread"))):
                exceptions.append(event)
    return {"strict": strict, "effective": bool(targets),
            "target_exception": bool(exceptions), "applied": len(applied),
            "target_count": len(targets), "junit_exit": manifest["exit_code"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "trace_sha256": sha(directory / "events.tsv"),
            "junit_sha256": sha(directory / "junit.log"),
            "jacoco_sha256": sha(directory / "jacoco.exec") if
            (directory / "jacoco.exec").is_file() else None}


if __name__ == "__main__":
    rows = [healthy(EVIDENCE / name) for name in
            ("original-001", "original-002", "healthy-001", "healthy-002")]
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
        manifest = json.loads((directory / "manifest.json").read_text())
        rows.append(trial(directory, manifest["faults"].split(";")))
    print(json.dumps(rows, indent=2))
