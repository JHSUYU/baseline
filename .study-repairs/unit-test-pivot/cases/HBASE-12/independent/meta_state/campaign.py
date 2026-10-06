#!/usr/bin/env python3
"""Bounded, resumable original-JUnit audit of TableState meta I/O families."""

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run.sh"
STATE = ROOT / "campaign-state.json"
CHECKPOINTS = ROOT / "checkpoints"
PLANS = ROOT / "plans"
MAX_TRIALS = 12
SELECTED_EXCEPTION = "org.apache.hadoop.hbase.DoNotRetryIOException"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def run_junit(suffix: str, plan: Path | None) -> tuple[int, Path]:
    log = ROOT / (suffix + ".log")
    with log.open("w") as out:
        proc = subprocess.run([str(RUN), "run", suffix, str(plan) if plan else ""],
                              stdout=out, stderr=subprocess.STDOUT, check=False)
    return proc.returncode, log


def coverage(suffix: str) -> tuple[list[str], Path, int]:
    log = ROOT / (suffix + ".coverage.log")
    proc = subprocess.run([str(RUN), "coverage", suffix], text=True,
                          capture_output=True, check=False)
    log.write_text(proc.stdout + proc.stderr)
    probes = sorted(set(re.findall(r"(?m)^PROBE class=(\S+) index=(\d+)$",
                                    proc.stdout)))
    return [name + "#" + index for name, index in probes], log, proc.returncode


def parse_io(lines: list[str]) -> list[dict]:
    points = []
    for index, line in enumerate(lines):
        if not line.startswith("HBASE12META IO "):
            continue
        values = dict(re.findall(r"(\w+)=([^ ]+)", line))
        points.append({"line_index": index, "marker": values.get("marker"),
                       "id": values.get("id"), "family": values.get("family"),
                       "ordinal": int(values.get("ordinal", 0)),
                       "fault": values.get("fault"),
                       "applied": values.get("applied") == "true",
                       "original_exception": values.get("originalException")})
    return points


def target_visits(lines: list[str]) -> list[dict]:
    visits = []
    for index, line in enumerate(lines):
        if not line.startswith("HBASE10 TARGET_EXIT "):
            continue
        values = dict(re.findall(r"(\w+)=([^ ]+)", line))
        exception = values.get("exception")
        visits.append({"line_index": index, "ordinal": int(values.get("ordinal", 0)),
                       "exception": exception,
                       "b3_evaluated": exception in ("none", SELECTED_EXCEPTION),
                       "b3_exception": exception == SELECTED_EXCEPTION})
    return visits


def parse_run(suffix: str, returncode: int, log: Path) -> dict:
    lines = log.read_text(errors="replace").splitlines()
    io = parse_io(lines)
    visits = target_visits(lines)
    plan_line = next((line for line in reversed(lines)
                      if line.startswith("HBASE12META PLAN ")), "")
    plan_counts = dict((key, int(value)) for key, value in
                       re.findall(r"(requested|matched|applied)=(\d+)", plan_line))
    junit = next((line for line in reversed(lines)
                  if line.startswith("HBASE10 JUNIT ")), "missing")
    elapsed_match = re.search(r"ELAPSED_SECONDS=([\d.]+)", "\n".join(lines[-100:]))
    probes, coverage_log, coverage_returncode = coverage(suffix)
    applied = [point for point in io if point["applied"]]
    last_fault_index = applied[-1]["line_index"] if applied else None
    post_fault_visits = [visit for visit in visits
                         if last_fault_index is not None
                         and visit["line_index"] > last_fault_index]
    return {
        "suffix": suffix, "returncode": returncode,
        "elapsed_seconds": float(elapsed_match.group(1)) if elapsed_match else None,
        "junit_result": junit, "log": str(log), "coverage_log": str(coverage_log),
        "plan_counts": plan_counts, "io": io, "target_visits": visits,
        "post_fault_b3_visits": [v for v in post_fault_visits if v["b3_evaluated"]],
        "target_after_fault": any(v["b3_evaluated"] for v in post_fault_visits),
        "selected_exception_after_fault": any(v["b3_exception"] for v in post_fault_visits),
        "production_probes": probes, "coverage_returncode": coverage_returncode,
        "stable_io_families": sorted({point["family"] for point in io}),
    }


def choose_plans(healthy: dict) -> list[dict]:
    io = healthy["io"]
    chosen = []
    read_requests = [p for p in io if p["marker"] == "META_READ_REQUEST"]
    read_responses = [p for p in io if p["marker"] == "META_READ_RESPONSE"]
    for points, kinds in ((read_requests, ("IOException",)),
                          (read_responses, ("IOException", "SocketTimeoutException"))):
        if points:
            representatives = [points[0], points[-1]]
            for point in representatives:
                for kind in kinds:
                    chosen.append({"point": point, "kind": kind})
    for state in ("DISABLING", "DISABLED"):
        for marker in ("META_WRITE_REQUEST", "META_WRITE_RESPONSE"):
            points = [p for p in io if p["marker"] == marker
                      and ("|" + state + "|") in p["family"]]
            if points:
                chosen.append({"point": points[0], "kind": "IOException"})
                if marker == "META_WRITE_RESPONSE":
                    chosen.append({"point": points[0], "kind": "SocketTimeoutException"})
    result = []
    seen = set()
    for choice in chosen:
        key = (choice["point"]["id"], choice["kind"])
        if key in seen:
            continue
        seen.add(key)
        result.append(choice)
    return result[:MAX_TRIALS]


def initialize() -> dict:
    suffix = "meta_healthy_" + str(int(time.time()))
    save(STATE, {"phase": "healthy_running", "inflight": suffix,
                 "created_utc": utc(), "completed": []})
    returncode, log = run_junit(suffix, None)
    healthy = parse_run(suffix, returncode, log)
    if (returncode != 0 or "succeeded=1 failed=0" not in healthy["junit_result"]
            or healthy["coverage_returncode"] != 0 or len(healthy["production_probes"]) < 100):
        save(STATE, {"phase": "healthy_failed", "healthy": healthy,
                     "completed": [], "created_utc": utc()})
        raise SystemExit("Original JUnit healthy run failed; see " + str(log))
    if not any(v["b3_evaluated"] for v in healthy["target_visits"]):
        save(STATE, {"phase": "healthy_no_target", "healthy": healthy,
                     "completed": [], "created_utc": utc()})
        raise SystemExit("Original JUnit did not evaluate B3")
    choices = choose_plans(healthy)
    for index, choice in enumerate(choices, 1):
        choice["name"] = "meta_%04d" % index
        path = PLANS / (choice["name"] + ".plan")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(choice["point"]["id"] + " " + choice["kind"] + "\n")
        choice["plan"] = str(path)
    state = {"schema_version": 1, "phase": "trials", "created_utc": utc(),
             "healthy": healthy, "choices": choices, "completed": [],
             "inflight": None, "attempts": {},
             "coverage_probes": healthy["production_probes"],
             "seen_stable_families": healthy["stable_io_families"],
             "stop_reason": ""}
    save(STATE, state)
    print("HEALTHY",len(healthy["target_visits"]),"target visits",
          len(healthy["io"]),"meta I/O points",len(choices),"plans",
          healthy["elapsed_seconds"],"seconds",flush=True)
    return state


def main() -> None:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    if state["phase"] == "healthy_running":
        state = initialize()
    if state["phase"] != "trials":
        raise SystemExit("Campaign state needs review: " + state["phase"])
    for choice in state["choices"]:
        name = choice["name"]
        if name in state["completed"]:
            continue
        attempt = state["attempts"].get(name, 0) + 1
        state["attempts"][name] = attempt
        suffix = name + "_attempt" + str(attempt)
        state["inflight"] = {"name": name, "suffix": suffix, "started_utc": utc()}
        save(STATE, state)
        print("START", name, choice["point"]["marker"],choice["kind"],flush=True)
        returncode, log = run_junit(suffix, Path(choice["plan"]))
        row = parse_run(suffix, returncode, log)
        row["name"] = name
        row["plan"] = choice["plan"]
        row["requested_point"] = choice["point"]
        row["fault_kind"] = choice["kind"]
        counts = row["plan_counts"]
        row["strict_identity_match"] = (
            counts.get("requested") == counts.get("matched") == counts.get("applied") == 1)
        covered = set(state["coverage_probes"])
        families = set(state["seen_stable_families"])
        row["new_production_probes"] = sorted(set(row["production_probes"]) - covered)
        row["new_stable_io_families"] = sorted(set(row["stable_io_families"]) - families)
        state["coverage_probes"] = sorted(covered | set(row["production_probes"]))
        state["seen_stable_families"] = sorted(families | set(row["stable_io_families"]))
        save(CHECKPOINTS / (name + ".json"), row)
        state["completed"].append(name)
        state["inflight"] = None
        save(STATE, state)
        print("END", name, "exact",row["strict_identity_match"],
              "B3-after",row["target_after_fault"],
              "B3-exception",row["selected_exception_after_fault"],
              "new-probes",len(row["new_production_probes"]),
              "seconds",row["elapsed_seconds"],flush=True)
    state["phase"] = "complete"
    state["stop_reason"] = "bounded_meta_family_plans_exhausted"
    save(STATE, state)
    print("STOP",state["stop_reason"],"trials",len(state["completed"]),flush=True)


if __name__ == "__main__":
    main()
