"""Summarize target reachability separately from injected faults and findings."""

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    selection = json.loads((HERE / "selected20.json").read_text())["sites"]
    root = HERE / "out_batch"
    progress = json.loads((root / "progress.json").read_text())["targets"]
    rows = []
    all_attempts = 0
    all_fault_trials = 0
    all_matched_injections = 0
    for index, site in enumerate(selection, 1):
        name = "candidate-{:03d}".format(index)
        state = progress.get(name, {})
        attempts = list(state.get("previous_attempts") or []) + ([state] if state else [])
        all_attempts += len(attempts)
        for recorded in attempts:
            for trial in recorded.get("trials", []):
                if trial["run_id"].startswith("run-"):
                    all_fault_trials += 1
                    all_matched_injections += trial["injected"]
        prior = (state.get("previous_attempts") or [])[-1:]
        use_prior = state.get("status") != "complete" and bool(prior)
        attempt = prior[0] if use_prior else state
        attempt_dir = (root / attempt["archived_dir"] if use_prior
                       and attempt.get("archived_dir") else root / name)
        trials = attempt.get("trials", [])
        seed = next((t for t in trials if t["run_id"].startswith("seed-")), None)
        faults = [t for t in trials if t["run_id"].startswith("run-")]
        finding_path = attempt_dir / "findings.jsonl"
        replayed = (sum(json.loads(line).get("confirmation", {}).get(
            "reproduced", False) for line in finding_path.read_text().splitlines())
                    if finding_path.is_file() else 0)
        baseline_fatal = bool(seed and seed["target_fatal"])
        seed_healthy = bool(seed and seed["workload_returncode"] == 0
                            and seed["checker_returncode"] == 0
                            and seed["target_reached"]
                            and not baseline_fatal)
        rows.append({
            "id": name, "site_id": site["site_id"],
            "class": site["class"], "line": site["line"],
            "exception": site["exception"],
            "status": state.get("status", "pending"),
            "reported_from": "previous_attempt" if use_prior else "current",
            "reported_complete": (bool(attempt.get("summary"))
                                  if use_prior else
                                  state.get("status") == "complete"),
            "seed_healthy": seed_healthy,
            "baseline_fatal": baseline_fatal,
            "fault_trials": len(faults),
            "matched_injections": sum(t["injected"] for t in faults),
            "exact_injections": sum(
                sum(mode == "exact" for mode in
                    t.get("injection_modes", ["exact"] * t["injected"]))
                for t in faults),
            "site_occurrence_injections": sum(
                sum(mode == "site_occurrence" for mode in
                    t.get("injection_modes", [])) for t in faults),
            "fault_target_reached": sum(bool(t["target_reached"]) for t in faults),
            "fatal_target_trials": sum(bool(t["target_fatal"]) for t in faults),
            "fault_workload_failures": sum(t["workload_returncode"] != 0
                                           for t in faults),
            "replayed_witnesses": replayed if seed_healthy else 0,
            "raw_replayed_exceptions": replayed,
        })
    totals = {"selected": len(rows),
              "completed": sum(r["reported_complete"] for r in rows),
              "active_retries": sum(r["status"] == "running" for r in rows),
              "healthy_seeds": sum(r["seed_healthy"] for r in rows),
              "baseline_fatal": sum(r["baseline_fatal"] for r in rows),
              "fault_trials": sum(r["fault_trials"] for r in rows),
              "matched_injections": sum(r["matched_injections"] for r in rows),
              "exact_injections": sum(r["exact_injections"] for r in rows),
              "site_occurrence_injections": sum(
                  r["site_occurrence_injections"] for r in rows),
              "fault_target_reached": sum(r["fault_target_reached"] for r in rows),
              "fatal_target_trials": sum(r["fatal_target_trials"] for r in rows),
              "fault_workload_failures": sum(r["fault_workload_failures"] for r in rows),
              "replayed_witnesses": sum(r["replayed_witnesses"] for r in rows)}
    totals["raw_replayed_exceptions"] = sum(
        r["raw_replayed_exceptions"] for r in rows)
    totals["all_attempts"] = all_attempts
    totals["all_fault_trials"] = all_fault_trials
    totals["all_matched_injections"] = all_matched_injections
    report = {"totals": totals, "targets": rows}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# HBase 3.0.0 twenty-check pilot", "",
             "The per-target rows and the unprefixed trial totals describe each "
             "target's latest complete attempt. The all_* totals include archived "
             "attempts. Each attempt has a separate fault-free seed and fault trial. "
             "A matched injection is distinct from target reachability; "
             "a fatal target is a candidate witness, not a validated bug. "
             "A target exception already thrown in the seed is a baseline "
             "exception, not a fault-induced witness. Site-occurrence "
             "matching can select a different request when ordering changes.", "",
             "Totals: " + ", ".join(f"{k}={v}" for k, v in totals.items()), "",
             "| ID | Check | Exception | Status | Seed healthy | Baseline fatal | Faults | Injected | Exact | Site nth | Reached | Fatal | Workload failures |",
             "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        check = row["class"].split("org.apache.hadoop.hbase.")[-1]
        status = (row["status"] + " (prior complete)"
                  if row["reported_from"] == "previous_attempt"
                  else row["status"])
        label = dict(row, check=check, status=status,
                     seed="yes" if row["seed_healthy"] else "no",
                     baseline="yes" if row["baseline_fatal"] else "no")
        lines.append("| {id} | {check}:{line} | {exception} | {status} | "
                     "{seed} | {baseline} | {fault_trials} | "
                     "{matched_injections} | {exact_injections} | "
                     "{site_occurrence_injections} | {fault_target_reached} | "
                     "{fatal_target_trials} | {fault_workload_failures} |".format(
                         **label))
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
