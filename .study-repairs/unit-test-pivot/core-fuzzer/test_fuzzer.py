import json
import sys
import tempfile
import unittest
from pathlib import Path

from fuzzer import (CaseLease, campaign, read_closure, strict_injection,
                    trace_feedback, validate)


TARGET = "<example.Target: void check()>"
SITE = TARGET + "#u8"
DOOR = "<example.Transport: void receive()>#u2"
OCC_TARGET = "node#epoch0/region/REGION.target/ctx:Lost:UNKNOWN/idx:target@0"
OCC_DOOR = "node#epoch0/region/REGION.door/ctx:Lost:UNKNOWN/idx:door@0"
POINT = {"marker": "FAULT:TEST:REQUEST", "siteId": DOOR,
         "occurrenceAddress": OCC_DOOR, "hitOrdinal": 1}


def jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in values))


def seed_files(root, extra=False):
    trace = root / "seed" / "runtime_trace.jsonl"
    plan = root / "seed" / "concolic_region_plan.jsonl"
    jsonl(plan, [
        {"kind": "CONCOLIC_RUNTIME_MODEL_CATALOG", "gaps": []},
        {"kind": "CONCOLIC_REGION_PLAN", "occurrenceId": OCC_DOOR,
         "regionId": "REGION.door",
         "targetMethod": "<example.Transport: void receive()>",
         "targetClosureEvidence": {
             "schemaVersion": 1, "kind": "TARGET_CLOSURE_MEMBERSHIP",
             "occurrence": OCC_DOOR,
             "targetOccurrence": OCC_TARGET, "evidenceTier": "CANDIDATE",
             "edgeEvidence": "UNAVAILABLE"},
         "closureGoals": [{"kind": "REGION_PATH_CLOSURE"}]},
        {"kind": "CONCOLIC_REGION_PLAN", "occurrenceId": OCC_TARGET,
         "regionId": "REGION.target",
         "targetMethod": TARGET,
         "targetClosureEvidence": {
             "schemaVersion": 1, "kind": "TARGET_CLOSURE_MEMBERSHIP",
             "occurrence": OCC_TARGET,
             "targetOccurrence": OCC_TARGET, "evidenceTier": "EXACT",
             "edgeEvidence": "UNAVAILABLE"},
         "closureGoals": [{"kind": "TARGET_REACH_CLOSURE"}]},
    ])
    events = [
        {"schemaVersion": 3, "event": "FAULT_POINT_OBSERVED", "seq": 1,
         **POINT},
        {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 2,
         "method": TARGET, "callId": 10,
         "occurrenceAddress": OCC_TARGET},
        {"schemaVersion": 3, "event": "BRANCH", "seq": 3,
         "method": TARGET, "callId": 10, "siteId": SITE,
         "outcome": False},
    ]
    if extra:
        events.append({"schemaVersion": 3, "event": "FAULT_POINT_OBSERVED",
                       "seq": 4, **{**POINT, "hitOrdinal": 2}})
    jsonl(trace, events)
    return trace, plan


FAKE_RUNNER = '''
import json, os
from pathlib import Path
trial = json.loads(Path(os.environ["CAUSYNTH_FAULT_TRIAL"]).read_text())
fault = trial["faults"][0]
trace = Path(os.environ["CAUSYNTH_TRACE_OUTPUT_DIR"]) / "runtime_trace.jsonl"
trace.parent.mkdir(parents=True, exist_ok=True)
rows = [
    {"schemaVersion":3,"event":"FAULT_POINT_OBSERVED","seq":1,
     **{k:fault[k] for k in ("marker","siteId","occurrence","hitOrdinal")}},
    {"schemaVersion":3,"event":"FAULT_MATCHED","seq":2,"faultId":fault["faultId"],
     "marker":fault["marker"],"siteId":fault["siteId"],
     "occurrenceAddress":fault["occurrence"],"hitOrdinal":fault["hitOrdinal"]},
    {"schemaVersion":3,"event":"FAULT_APPLIED","seq":3,"faultId":fault["faultId"],
     "marker":fault["marker"],"siteId":fault["siteId"],
     "occurrenceAddress":fault["occurrence"],"hitOrdinal":fault["hitOrdinal"]},
    {"schemaVersion":3,"event":"METHOD_ENTER","seq":4,"method":TARGET,
     "callId":10,"occurrenceAddress":OCC_TARGET},
    {"schemaVersion":3,"event":"BRANCH","seq":5,"method":TARGET,
     "callId":10,"siteId":SITE,"outcome":True},
    {"schemaVersion":3,"event":"METHOD_EXIT_THROW","seq":6,"method":TARGET,
     "callId":10,"runtimeType":"example.TargetException"},
]
rows[0]["occurrenceAddress"] = rows[0].pop("occurrence")
trace.write_text("".join(json.dumps(row)+"\\n" for row in rows))
'''


def trial_config(root, trace, plan, runner, max_trials=1, max_seconds=100):
    for name in ("graphchecker", "system", "tmp"):
        (root / name).mkdir(exist_ok=True)
    return {"case_id": "CHECK-01", "system": "example",
            "test_class": "example.OriginalClusterTest",
            "test_method": "testOriginal", "cwd": str(root / "graphchecker"),
            "workspaces": {"graphchecker": str(root / "graphchecker"),
                           "system_test": str(root / "system"),
                           "temp": str(root / "tmp")},
            "shared_readonly_roots": [],
            "target": {"method": TARGET, "site_id": SITE,
                       "region_id": "REGION.target",
                       "fatal_guards": [{"siteId": SITE, "outcome": True}],
                       "exception_type": "example.TargetException"},
            "seed": {"trace": str(trace), "closure_plan": str(plan),
                     "elapsed_seconds": 2.5},
            "trial": {"command": [sys.executable, str(runner)],
                      "aggregate_command": ["/bin/cp", str(plan),
                                            "{aggregate_dir}/plan.jsonl"],
                      "closure_plan": "{aggregate_dir}/plan.jsonl"},
            "budget": {"max_trials": max_trials, "max_faults": 1,
                       "max_seconds": max_seconds},
            "timeout_seconds": 10}


class FuzzerTest(unittest.TestCase):
    def test_strict_requires_applied_identity_and_order(self):
        selector = {"marker": POINT["marker"], "siteId": POINT["siteId"],
                    "occurrence": POINT["occurrenceAddress"], "hitOrdinal": 1}
        self.assertFalse(strict_injection(
            {"matched_count": 1, "applied_count": 1,
             "applied_points": [], "applied_fault_ids": []}, [selector]))
        self.assertTrue(strict_injection(
            {"matched_count": 1, "applied_count": 1,
             "applied_points": [selector],
             "applied_fault_ids": [__import__("fuzzer").fingerprint(selector)]},
            [selector]))

    def test_claim_blocks_second_owner_and_takes_expired_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            case = Path(temp) / "CHECK-01"
            with CaseLease(case, ttl=1, interval=1):
                with self.assertRaisesRegex(RuntimeError, "already claimed"):
                    with CaseLease(case, ttl=1, interval=1):
                        pass
            (case / "claim.d").mkdir()
            (case / "claim.d" / "lease.json").write_text(json.dumps({
                "owner": "dead", "heartbeat": 0}))
            with CaseLease(case, ttl=1, interval=1):
                self.assertTrue((case / "claim.d" / "lease.json").exists())
            self.assertEqual(len(list(case.glob("claim.stale.*.d"))), 1)

    def test_no_membership_proof_means_no_non_target_fault_point(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            lines = [json.loads(line) for line in plan.read_text().splitlines()]
            del lines[1]["targetClosureEvidence"]
            jsonl(plan, lines)
            closure = read_closure(plan, TARGET)
            self.assertEqual(closure["addresses"], [OCC_TARGET])
            self.assertEqual(closure["blocking_gaps"][0]["kind"],
                             "CLOSURE_MEMBER_EVIDENCE_MISSING")
            feedback = trace_feedback(trace, closure,
                                      {"method": TARGET,
                                       "fatal_guards": [{"siteId": SITE,
                                                         "outcome": True}],
                                       "exception_type": "example.TargetException"})
            self.assertEqual(feedback["points"], [])

    def test_blocking_seed_gap_stops_before_fault_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            plan_rows = [json.loads(line) for line in plan.read_text().splitlines()]
            del plan_rows[1]["targetClosureEvidence"]
            jsonl(plan, plan_rows)
            runner = root / "should_not_run.py"
            runner.write_text("raise RuntimeError('fault trial ran despite graph gap')\n")
            state = campaign(trial_config(root, trace, plan, runner),
                             root / "results")
            self.assertEqual(state["status"], "graph_gap")
            self.assertEqual(state["completed"], [])
            self.assertEqual(state["queue"], [])
            item = json.loads((root / "results" / "CHECK-01" /
                               "result.json").read_text())
            self.assertEqual(item["status"], "graph_gap")
            self.assertEqual(item["fault_trials"], 0)

    def test_target_occurrence_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            _, plan = seed_files(Path(temp))
            self.assertEqual(read_closure(plan, TARGET, OCC_TARGET)
                             ["target_addresses"], [OCC_TARGET])
            with self.assertRaisesRegex(ValueError, "no target region"):
                read_closure(plan, TARGET, OCC_DOOR)

    def test_target_request_api_excludes_other_operation(self):
        with tempfile.TemporaryDirectory() as temp:
            _, plan = seed_files(Path(temp))
            plan_rows = [json.loads(line) for line in plan.read_text().splitlines()]
            plan_rows[2]["requestApi"] = "operation-a(arg=false)"
            other = json.loads(json.dumps(plan_rows[2]))
            other["occurrenceId"] = OCC_TARGET + ".other"
            other["requestApi"] = "operation-a(arg=true)"
            other["targetClosureEvidence"]["occurrence"] = other["occurrenceId"]
            other["targetClosureEvidence"]["targetOccurrence"] = other["occurrenceId"]
            jsonl(plan, plan_rows + [other])
            allowed = read_closure(
                plan, TARGET, allowed_target_request_apis={"operation-a(arg=false)"})
            self.assertEqual(allowed["target_addresses"], [OCC_TARGET])
            self.assertEqual(allowed["target_request_apis"],
                             ["operation-a(arg=false)"])
            with self.assertRaisesRegex(ValueError, "no target region"):
                read_closure(plan, TARGET,
                             allowed_target_request_apis={"operation-b"})

    def test_declared_throw_method_cannot_disagree_with_site(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            runner = root / "unused.py"
            runner.write_text("pass\n")
            config = trial_config(root, trace, plan, runner)
            config["target"]["throw_site_id"] = TARGET + "#u8"
            config["target"]["throw_method"] = "<example.Other: void check()>"
            with self.assertRaisesRegex(ValueError, "throw_method differs"):
                validate(config)

    def test_other_target_membership_is_not_a_missing_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            _, plan = seed_files(Path(temp))
            lines = [json.loads(line) for line in plan.read_text().splitlines()]
            other = "node#epoch0/region/REGION.other/ctx:Other/idx:other@0"
            lines.append({"kind": "CONCOLIC_REGION_PLAN", "occurrenceId": other,
                          "targetMethod": "<example.Other: void check()>",
                          "targetClosureEvidence": {
                              "schemaVersion": 1,
                              "kind": "TARGET_CLOSURE_MEMBERSHIP",
                              "occurrence": other, "targetOccurrence": other,
                              "evidenceTier": "EXACT",
                              "edgeEvidence": "UNAVAILABLE"},
                          "closureGoals": [{"kind": "TARGET_REACH_CLOSURE"}]})
            jsonl(plan, lines)
            closure = read_closure(plan, TARGET)
            self.assertNotIn(other, closure["addresses"])
            self.assertEqual(closure["blocking_gaps"], [])

    def test_folded_target_region_is_not_runtime_target_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            _, plan = seed_files(Path(temp))
            lines = [json.loads(line) for line in plan.read_text().splitlines()]
            lines[2]["foldedRegionIds"] = ["REGION.nested.target"]
            jsonl(plan, lines)
            closure = read_closure(plan, TARGET,
                                   target_region_id="REGION.nested.target")
            self.assertFalse(closure["target_region_explicit"])
            self.assertEqual(closure["blocking_gaps"][0]["kind"],
                             "TARGET_REGION_FOLDED_ONLY")

    def test_exact_target_occurrence_and_post_fault_branch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            closure = read_closure(plan, TARGET)
            healthy = trace_feedback(trace, closure,
                                     {"method": TARGET, "site_id": SITE,
                                      "fatal_guards": [{"siteId": SITE,
                                                        "outcome": True}],
                                      "exception_type": "example.TargetException"})
            self.assertTrue(healthy["target_reached"])
            self.assertEqual(len(healthy["points"]), 1)
            self.assertFalse(healthy["oracle"])
            other = root / "other.jsonl"
            jsonl(other, [
                {"schemaVersion": 3, "event": "FAULT_APPLIED", "seq": 1,
                 **POINT},
                {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 2,
                 "method": TARGET, "callId": 99,
                 "occurrenceAddress": OCC_DOOR},
                {"schemaVersion": 3, "event": "BRANCH", "seq": 3,
                 "siteId": SITE, "callId": 99},
                {"schemaVersion": 3, "event": "METHOD_EXIT_THROW", "seq": 4,
                 "method": TARGET, "callId": 99,
                 "runtimeType": "example.TargetException"},
            ])
            verdict = trace_feedback(other, closure,
                                     {"method": TARGET, "site_id": SITE,
                                      "fatal_guards": [{"siteId": SITE,
                                                        "outcome": True}],
                                      "exception_type": "example.TargetException"})
            self.assertFalse(verdict["oracle"])

    def test_target_seen_only_before_fault_is_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            runner = root / "pre_target_runner.py"
            reordered = FAKE_RUNNER.replace(
                "trace.write_text(",
                "rows = [rows[0], rows[3], rows[4], rows[1], rows[2]]\n"
                "for i, row in enumerate(rows, 1): row['seq'] = i\n"
                "trace.write_text(")
            runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                              "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                              reordered)
            state = campaign(trial_config(root, trace, plan, runner),
                             root / "results")
            result = json.loads(Path(state["completed"][0]["result"]).read_text())
            self.assertTrue(result["target_reached"])
            self.assertFalse(result["target_reached_after_fault"])
            self.assertEqual(result["status"], "lost_target")
            self.assertFalse(result["oracle"])
            summary = json.loads((root / "results" / "CHECK-01" /
                                  "result.json").read_text())
            self.assertEqual(summary["bug_mark"], "none")
            self.assertEqual(summary["status"], "no_valid_target_trial")
            self.assertEqual(summary["lost_target_trials"], 1)

    def test_nested_throw_must_descend_from_target_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, plan = seed_files(root)
            closure = read_closure(plan, TARGET)
            child = "<example.Child: void fatalCheck()>"
            guard = child + "#u4"
            faulted = root / "nested.jsonl"
            jsonl(faulted, [
                {"schemaVersion": 3, "event": "FAULT_APPLIED", "seq": 1,
                 "faultId": "f", **POINT},
                {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 2,
                 "method": TARGET, "callId": 10, "parentCallId": 0,
                 "occurrenceAddress": OCC_TARGET},
                {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 3,
                 "method": child, "callId": 11, "parentCallId": 10},
                {"schemaVersion": 3, "event": "BRANCH", "seq": 4,
                 "siteId": guard, "callId": 11, "outcome": True},
                {"schemaVersion": 3, "event": "METHOD_EXIT_THROW", "seq": 5,
                 "method": child, "callId": 11,
                 "runtimeType": "example.TargetException"},
            ])
            target = {"method": TARGET, "throw_method": child,
                      "fatal_guards": [{"siteId": guard, "outcome": True}],
                      "exception_type": "example.TargetException"}
            self.assertTrue(trace_feedback(faulted, closure, target)["oracle"])
            lines = [json.loads(line) for line in faulted.read_text().splitlines()]
            lines[2]["parentCallId"] = 99
            jsonl(faulted, lines)
            self.assertFalse(trace_feedback(faulted, closure, target)["oracle"])
            unrelated = root / "unrelated.jsonl"
            jsonl(unrelated, [
                {"schemaVersion": 3, "event": "FAULT_APPLIED", "seq": 1,
                 **POINT},
                {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 2,
                 "method": TARGET, "callId": 10,
                 "occurrenceAddress": OCC_TARGET},
                {"schemaVersion": 3, "event": "BRANCH", "seq": 3,
                 "siteId": SITE, "callId": 10, "outcome": False},
                {"schemaVersion": 3, "event": "METHOD_EXIT_THROW", "seq": 4,
                 "method": TARGET, "callId": 10,
                 "runtimeType": "example.TargetException"},
            ])
            verdict = trace_feedback(unrelated, closure,
                                     {"method": TARGET,
                                      "fatal_guards": [{"siteId": SITE,
                                                        "outcome": True}],
                                      "exception_type": "example.TargetException"})
            self.assertTrue(verdict["target_after_fault"])
            self.assertFalse(verdict["oracle"])

    def test_alternative_fatal_guard_paths_do_not_require_both_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, plan = seed_files(root)
            closure = read_closure(plan, TARGET)
            a = TARGET + "#u11"
            b = TARGET + "#u20"
            outer = TARGET + "#u2"
            target = {"method": TARGET,
                      "exception_type": "example.TargetException",
                      "fatal_guard_paths": [
                          [{"siteId": outer, "outcome": True},
                           {"siteId": a, "outcome": True}],
                          [{"siteId": outer, "outcome": True},
                           {"siteId": b, "outcome": False}]]}
            for last_site, last_outcome in ((a, True), (b, False)):
                trace = root / ("route-a.jsonl" if last_site == a
                                else "route-b.jsonl")
                jsonl(trace, [
                    {"schemaVersion": 3, "event": "FAULT_APPLIED", "seq": 1,
                     "faultId": "f", **POINT},
                    {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 2,
                     "method": TARGET, "callId": 10,
                     "occurrenceAddress": OCC_TARGET},
                    {"schemaVersion": 3, "event": "BRANCH", "seq": 3,
                     "siteId": outer, "callId": 10, "outcome": True},
                    {"schemaVersion": 3, "event": "BRANCH", "seq": 4,
                     "siteId": last_site, "callId": 10,
                     "outcome": last_outcome},
                    {"schemaVersion": 3, "event": "METHOD_EXIT_THROW",
                     "seq": 5, "method": TARGET, "callId": 10,
                     "runtimeType": "example.TargetException"},
                ])
                feedback = trace_feedback(trace, closure, target)
                self.assertTrue(feedback["oracle"])
                self.assertEqual(feedback["target_fatal_exception_count"], 1)
            # A branch seen only before the fault cannot validate a replay.
            lines = [json.loads(line) for line in trace.read_text().splitlines()]
            lines[0]["seq"] = 4
            jsonl(trace, lines)
            self.assertFalse(trace_feedback(trace, closure, target)["oracle"])
            # Reaching only the common outer condition is not reaching either
            # selected check after the fault.
            jsonl(trace, [
                {"schemaVersion": 3, "event": "FAULT_APPLIED", "seq": 1,
                 "faultId": "f", **POINT},
                {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 2,
                 "method": TARGET, "callId": 10,
                 "occurrenceAddress": OCC_TARGET},
                {"schemaVersion": 3, "event": "BRANCH", "seq": 3,
                 "siteId": outer, "callId": 10, "outcome": True},
            ])
            self.assertFalse(trace_feedback(trace, closure, target)
                             ["target_reached_after_fault"])
            # A fault between an outer guard and the decisive guard still
            # exposes a post-fault fatal check.
            jsonl(trace, [
                {"schemaVersion": 3, "event": "METHOD_ENTER", "seq": 1,
                 "method": TARGET, "callId": 10,
                 "occurrenceAddress": OCC_TARGET},
                {"schemaVersion": 3, "event": "BRANCH", "seq": 2,
                 "siteId": outer, "callId": 10, "outcome": True},
                {"schemaVersion": 3, "event": "FAULT_APPLIED", "seq": 3,
                 "faultId": "f", **POINT},
                {"schemaVersion": 3, "event": "BRANCH", "seq": 4,
                 "siteId": a, "callId": 10, "outcome": True},
                {"schemaVersion": 3, "event": "METHOD_EXIT_THROW", "seq": 5,
                 "method": TARGET, "callId": 10,
                 "runtimeType": "example.TargetException"},
            ])
            self.assertTrue(trace_feedback(trace, closure, target)["oracle"])

    def test_one_trial_persists_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            runner = root / "fake_runner.py"
            runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                              "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                              FAKE_RUNNER)
            config = trial_config(root, trace, plan, runner)
            first = campaign(config, root / "results")
            self.assertEqual(len(first["completed"]), 1)
            self.assertEqual(first["completed"][0]["status"],
                             "target_exception_candidate")
            self.assertFalse((root / "results" / "CHECK-01" /
                              "claim.d").exists())
            second = campaign(config, root / "results")
            self.assertEqual(len(second["completed"]), 1)
            self.assertEqual(second["completed"][0]["result"],
                             first["completed"][0]["result"])
            item = json.loads((root / "results" / "CHECK-01" /
                               "result.json").read_text())
            self.assertGreaterEqual(item["elapsed_seconds"], 2.5)
            self.assertEqual(item["seed_seconds"], 2.5)
            self.assertGreater(item["aggregate_seconds"], 0)

    def test_exact_target_exception_survives_faulted_state_graph_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            faulted_plan = root / "faulted-plan.jsonl"
            plan_rows = [json.loads(line) for line in plan.read_text().splitlines()]
            plan_rows[0]["gaps"] = [{"kind": "STATE_WRITER_MISSING",
                                     "cls": "BLOCKING",
                                     "subject": "missing namespace entry"}]
            jsonl(faulted_plan, plan_rows)
            runner = root / "fake_runner.py"
            runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                              "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                              FAKE_RUNNER)
            config = trial_config(root, trace, plan, runner)
            config["trial"]["aggregate_command"][1] = str(faulted_plan)
            state = campaign(config, root / "results")
            trial = json.loads(Path(state["completed"][0]["result"]).read_text())
            self.assertEqual(trial["status"], "target_exception_candidate")
            self.assertTrue(trial["strict_injection"])
            self.assertFalse(trial["graph_feedback_valid"])
            self.assertTrue(trial["differential_target_exception"])
            self.assertEqual(trial["new_coverage_count"], 0)
            summary = json.loads((root / "results/CHECK-01/result.json").read_text())
            self.assertEqual(summary["status"], "candidate_review")

    def test_trial_environment_and_trace_path_are_case_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            runner = root / "fake_runner.py"
            runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                              "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                              FAKE_RUNNER)
            config = trial_config(root, trace, plan, runner)
            config["trial"]["env"] = {
                "CAUSYNTH_TRACE_OUTPUT_DIR": "{trial_dir}/system-trace"}
            config["trial"]["trace_path"] = (
                "{trial_dir}/system-trace/runtime_trace.jsonl")
            state = campaign(config, root / "results")
            self.assertEqual(state["completed"][0]["status"],
                             "target_exception_candidate")
            result = json.loads(Path(state["completed"][0]["result"]).read_text())
            self.assertIn("system-trace", result["trace"])

    def test_expected_healthy_exception_requires_differential(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root)
            healthy = [json.loads(line) for line in trace.read_text().splitlines()]
            healthy[-1]["outcome"] = True
            healthy.append({"schemaVersion": 3,
                            "event": "METHOD_EXIT_THROW", "seq": 4,
                            "method": TARGET, "callId": 10,
                            "runtimeType": "example.TargetException"})
            jsonl(trace, healthy)
            runner = root / "fake_runner.py"
            runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                              "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                              FAKE_RUNNER)
            state = campaign(trial_config(root, trace, plan, runner),
                             root / "results")
            trial = json.loads(Path(state["completed"][0]["result"]).read_text())
            self.assertTrue(trial["oracle"])
            self.assertFalse(trial["differential_target_exception"])
            self.assertEqual(trial["status"], "baseline_exception_recurrence")
            summary = json.loads((root / "results" / "CHECK-01" /
                                  "result.json").read_text())
            self.assertEqual(summary["bug_mark"], "none")

    def test_resume_budget_ignores_offline_wall_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace, plan = seed_files(root, extra=True)
            runner = root / "fake_runner.py"
            runner.write_text("TARGET=" + repr(TARGET) + "\nSITE=" + repr(SITE) +
                              "\nOCC_TARGET=" + repr(OCC_TARGET) + "\n" +
                              FAKE_RUNNER)
            config = trial_config(root, trace, plan, runner, max_trials=1)
            first = campaign(config, root / "results")
            self.assertEqual(len(first["completed"]), 1)
            self.assertEqual(len(first["queue"]), 1)
            state_path = root / "results" / "CHECK-01" / "state.json"
            state = json.loads(state_path.read_text())
            state["started"] = 1  # simulated long disconnect
            state_path.write_text(json.dumps(state))
            config["budget"]["max_trials"] = 2
            second = campaign(config, root / "results")
            self.assertEqual(len(second["completed"]), 2)


if __name__ == "__main__":
    unittest.main()
