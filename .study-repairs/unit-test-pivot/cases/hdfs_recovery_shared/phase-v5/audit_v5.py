#!/usr/bin/env python3
"""Independent raw-trace audit; does not trust the V5 controller's verdicts."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
STATE = HERE / "campaign-state.json"
REPORT = HERE / "offline-audit.json"
CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
SITES = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
    "HDFS-29": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u12",
    "HDFS-30": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u23",
}
PREFIX = ("marker", "siteId", "sourceKey", "originSourceKey",
          "occurrenceAddress", "hitOrdinal", "requestApi", "faultType")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rows(run: str) -> list[dict]:
    return [json.loads(line) for line in (Path(run) / "runtime_trace.jsonl").read_text().splitlines()
            if line]


def origin(row: dict) -> str:
    return row.get("originSourceKey", row.get("sourceKey", ""))


def root(row: dict) -> str:
    return row.get("occurrenceAddress", "").split("/rpc:", 1)[0].split("/server:", 1)[0]


def parent_key(point: dict) -> tuple:
    return tuple(point.get(field, "") for field in PREFIX)


def raw_matches(io: dict, selected: dict) -> bool:
    return (io.get("event") == "FAULT_POINT_OBSERVED"
            and all((origin(io) if field == "originSourceKey" else io.get(field, ""))
                    == selected.get(field, "") for field in PREFIX[:-1])
            and (not selected.get("filePhase") or not io.get("filePhase")
                 or selected["filePhase"] == io["filePhase"]))


def old_owner(io: dict, target: dict) -> bool:
    return (origin(io) == target.get("sourceKey") and io.get("blockId") == target.get("blockId")
            and root(io) == target.get("occurrenceAddress")
            and origin(io) not in ("", "unregistered", "unknown-origin"))


def new_owner(row: dict) -> tuple:
    return (row.get("clusterEpisode"), origin(row), row.get("bpid"),
            row.get("blockId"), row.get("recoveryId"), root(row),
            row.get("commandToken"))


def known_owner(row: dict) -> bool:
    episode, source, bpid, block, recovery, address, command = new_owner(row)
    return (type(episode) is int and episode > 0 and source not in
            ("", "unregistered", "unknown-origin") and bool(bpid)
            and type(block) is int and block >= 0 and type(recovery) is int
            and recovery >= 0 and bool(address)
            and isinstance(command, str)
            and (command.startswith("command:") or command.startswith("direct:")))


def receipt_verdict(trial: dict) -> dict:
    trace = rows(trial["run"])
    if not trace or any(row.get("schemaVersion") != 4 for row in trace):
        raise RuntimeError("V5 raw trace schema mismatch: " + trial["run"])
    selected = trial["sequence"]
    matched = [r for r in trace if r.get("event") == "FAULT_MATCHED"]
    applied = [r for r in trace if r.get("event") == "FAULT_APPLIED"]
    strict = len(matched) == len(applied) == len(selected)
    episode = selected[0].get("clusterEpisode", trial["last_owner"][0] if trial.get("last_owner") else 1)
    for index, chosen in enumerate(selected):
        if not strict:
            break
        m, a = matched[index], applied[index]
        for event in (m, a):
            if (event.get("planIndex") != index or event.get("clusterEpisode") !=
                    chosen.get("clusterEpisode", episode)
                    or event.get("filePhase", "") != chosen.get("filePhase", "")
                    or origin(event) != chosen.get("originSourceKey", chosen["sourceKey"])
                    or any(event.get(key) != chosen.get(key) for key in
                           ("marker", "siteId", "sourceKey", "occurrenceAddress",
                            "hitOrdinal", "requestApi", "faultType"))):
                strict = False
        if not known_owner(a) or not m["seq"] < a["seq"]:
            strict = False
        if index and not applied[index - 1]["seq"] < m["seq"]:
            strict = False
        if not any(r.get("event") == "DN_REGISTER"
                   and r.get("sourceKey") == a.get("sourceKey")
                   and r.get("clusterEpisode") == a.get("clusterEpisode")
                   and r.get("seq", -1) < a["seq"] for r in trace):
            strict = False
        if a.get("marker") != "FAULT:HDFS_RPC:RECOVERY_COMMAND" and not any(
                r.get("event") == "RECOVERY_BEGIN" and known_owner(r)
                and new_owner(r) == new_owner(a) and r["seq"] < a["seq"] for r in trace):
            strict = False
        if a.get("marker", "").startswith("FAULT:HDFS_FILE:") and not any(
                r.get("event") == "SERVER_RECOVERY_BEGIN"
                and r.get("sourceKey") == a.get("sourceKey")
                and r.get("originSourceKey") == origin(a)
                and all(r.get(k) == a.get(k) for k in
                        ("clusterEpisode", "bpid", "blockId", "recoveryId",
                         "commandToken"))
                and r["seq"] < a["seq"] for r in trace):
            strict = False
        if a.get("marker", "").startswith("FAULT:HDFS_FILE:") and (
                a.get("filePhase") not in ("initReplicaRecovery", "updateReplicaUnderRecovery")
                or (a.get("filePhase") == "updateReplicaUnderRecovery"
                    and a.get("sourceKey") != origin(a))):
            strict = False
    last = applied[-1] if strict else None
    post = {}
    throws = {}
    for case in CASES:
        checks = [r for r in trace if r.get("event") == "TARGET_CHECK"
                  and r.get("caseId") == case and r.get("siteId") == SITES[case]
                  and last is not None and r.get("seq", -1) > last["seq"]
                  and known_owner(r) and new_owner(r) == new_owner(last)]
        post[case] = len(checks)
        throws[case] = sum(r.get("event") == "TARGET_THROW"
                           and r.get("caseId") == case and r.get("siteId") == SITES[case]
                           and r.get("runtimeType") == "java.io.IOException"
                           and last is not None and r.get("seq", -1) > last["seq"]
                           and known_owner(r) and new_owner(r) == new_owner(last)
                           and any(c.get("outcome") is True and c["seq"] < r["seq"]
                                   for c in checks) for r in trace)
    return {"strict": strict, "post": post, "throws": throws,
            "trace_sha256": digest(Path(trial["run"]) / "runtime_trace.jsonl")}


def main() -> None:
    state = json.loads(STATE.read_text())
    v4_dir = Path(state["migration"]["v4_dir"])
    issues = []
    for name, expected in state["migration"]["v4_sha256"].items():
        if digest(v4_dir / name) != expected:
            issues.append("V4 hash changed: " + name)
    v4 = json.loads((v4_dir / "campaign-state.json").read_text())
    archived = state["migration"]["v4_completed_receipts"]
    if len(v4["completed"]) != 128 or len(archived) != 128:
        issues.append("V4 completed ancestry count mismatch")
    for number, (old, retained) in enumerate(zip(v4["completed"], archived), 1):
        if (retained["attempt"] != number or retained["id"] != old["id"]
                or retained["run"] != old["run"]
                or retained["exact_order_applied"] != old["exact_order_applied"]):
            issues.append("V4 receipt changed at attempt " + str(number))
    prior_effective = {case: sum(bool(t["exact_order_applied"] and
                                      t["post_fault_target_checks"][case])
                                 for t in v4["completed"]) for case in CASES}
    if prior_effective != state["migration"]["v4_effective"]:
        issues.append("V4 effective counts changed")
    strict_parents = defaultdict(list)
    for old in v4["completed"]:
        if old["exact_order_applied"]:
            strict_parents[tuple(parent_key(p) for p in old["sequence"])].append(old)
    cache = {}
    old_lane = {}
    by_case = {case: 0 for case in CASES}
    for queued in v4["queue"]:
        eligible = set()
        if len(queued["sequence"]) == 2:
            for parent in strict_parents[tuple(parent_key(p) for p in queued["sequence"][:-1])]:
                if parent["run"] not in cache:
                    cache[parent["run"]] = rows(parent["run"])
                trace = cache[parent["run"]]
                for io in trace:
                    if io.get("seq", -1) <= parent["last_applied_seq"] or not raw_matches(
                            io, queued["sequence"][-1]):
                        continue
                    for case in CASES:
                        if any(t.get("event") == "TARGET_CHECK" and t.get("caseId") == case
                               and t.get("siteId") == SITES[case] and t["seq"] > io["seq"]
                               and old_owner(io, t) for t in trace):
                            eligible.add(case)
        old_lane[queued["id"]] = sorted(eligible)
        for case in eligible:
            by_case[case] += 1
    if (len(v4["queue"]), by_case) != (789, {"HDFS-28": 0, "HDFS-29": 196,
                                             "HDFS-30": 196}):
        issues.append("V4 parent raw classification mismatch")
    if not state["v5_attempts"]:
        for queued in state["queue"]:
            if queued["id"] in old_lane and queued["pre_target_cases"] != old_lane[queued["id"]]:
                issues.append("migrated lane mismatch " + queued["id"])
    recomputed = {case: {"attempts": 128, "effective": prior_effective[case],
                         "throws_v5": 0} for case in CASES}
    audited = []
    v4_strict_ids = {t["id"] for t in v4["completed"] if t["exact_order_applied"]}
    seen_v5_strict = set()
    for index, trial in enumerate(state["completed_v5"], 129):
        directory = Path(trial["run"])
        if directory.name != "trial-%03d" % index:
            issues.append("V5 run numbering mismatch " + trial["id"])
        manifest = json.loads((directory / "manifest.json").read_text())
        if (manifest.get("test") !=
                "org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryTimeout"
                or not manifest.get("instrumented")
                or manifest.get("overlay_digest") != trial["overlay_digest"]
                or not (directory / "jacoco.exec").is_file()):
            issues.append("V5 original-JUnit/overlay/JaCoCo receipt mismatch " + trial["id"])
        verdict = receipt_verdict(trial)
        for case in trial["active_cases_at_selection"]:
            if len(trial["sequence"]) > trial["max_faults_at_selection"][case]:
                issues.append("selected fault depth exceeded " + trial["id"] + " " + case)
            if trial["attempt_caps_at_selection"][case] not in (320, 512):
                issues.append("selected attempt cap invalid " + trial["id"] + " " + case)
        if verdict["strict"]:
            if trial["id"] in v4_strict_ids or trial["id"] in seen_v5_strict:
                issues.append("duplicate strictly injected plan " + trial["id"])
            seen_v5_strict.add(trial["id"])
        if verdict["strict"] != trial["exact_order_applied"]:
            issues.append("strict raw mismatch " + trial["id"])
        for case in CASES:
            if verdict["post"][case] != trial["post_fault_target_checks"][case]:
                issues.append("postfault target raw mismatch " + trial["id"] + " " + case)
            if verdict["throws"][case] != trial["target_exceptions_after_fault"][case]:
                issues.append("target throw raw mismatch " + trial["id"] + " " + case)
            if case in trial["active_cases_at_selection"]:
                recomputed[case]["attempts"] += 1
                if verdict["strict"] and verdict["post"][case]:
                    recomputed[case]["effective"] += 1
                    recomputed[case]["throws_v5"] += bool(verdict["throws"][case])
        audited.append({"id": trial["id"], **verdict})
    if state["v5_attempts"] != len(audited):
        issues.append("V5 completed counter mismatch")
    for case in CASES:
        actual = state["cases"][case]
        if any(actual[key] != recomputed[case][key] for key in ("attempts", "effective")):
            issues.append("case budget counter mismatch " + case)
        if actual["target_exception_trials_v5"] != recomputed[case]["throws_v5"]:
            issues.append("case target exception counter mismatch " + case)
        if actual["attempts"] > actual["attempt_cap"] or actual["attempt_cap"] not in (320, 512):
            issues.append("case attempt cap exceeded " + case)
    report = {"schema": "hdfs-recovery-v5-independent-raw-audit-1",
              "state_sha256": digest(STATE), "v4_state_sha256": digest(v4_dir / "campaign-state.json"),
              "v4_attempts": len(v4["completed"]), "v4_effective": prior_effective,
              "v4_pending": len(v4["queue"]), "parent_raw_pair_pre_target": by_case,
              "v5_completed": len(audited), "v5_trials": audited,
              "recomputed_cases": recomputed, "issues": issues, "passed": not issues}
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"passed": not issues, "issues": issues, "v5_completed": len(audited),
                      "pair_pre_target": by_case}, sort_keys=True))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
