import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("solr37_full_v6", HERE / "run_campaign.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ContinuationTest(unittest.TestCase):
    def test_sealed_import_does_not_requeue_valid_faults(self):
        config = runner.read(HERE / "config-full-node0.json")
        summary = runner.reconstruct_parent(config, dry_run=True)
        self.assertEqual([0, 1, 2], summary["imported_trials"])
        self.assertEqual([3, 4, 5, 6], summary["excluded_unmatched_parent_trials"])
        self.assertEqual([1, 2], summary["valid_v5_fault_trials_not_requeued"])
        self.assertEqual(7, summary["next_trial"])
        self.assertEqual(9, len(summary["queued_signatures"]))
        self.assertEqual(9, len(set(summary["queued_signatures"])))
        self.assertEqual(5, sum(row["node"] == "shard-2"
                                for row in summary["new_frontier"]))

    def test_actual_actor_is_not_blinded_by_v5_healthy_binding(self):
        original_apply = runner.campaign._apply_result
        original_mutate = runner.campaign.mutate
        original_replay = runner.scheduler._replay_point
        original_run = runner.campaign._run_trial
        seen = []
        try:
            runner.campaign._run_trial = lambda *args: seen.append(args[-1]) or {}
            runner.install_v6_runtime()
            runner.campaign._run_trial({}, Path("/tmp"), 7, [], lambda _: None,
                                       {"nodes": ["shard-4"]})
            self.assertEqual([None], seen)
        finally:
            runner.campaign._apply_result = original_apply
            runner.campaign.mutate = original_mutate
            runner.scheduler._replay_point = original_replay
            runner.campaign._run_trial = original_run
            runner.pilot.audit_trial = runner.audit_trial

    def test_sealed_fault_has_postfault_exact_reference_path(self):
        source = (runner.ROOT / "data/mallory/solr37_target_actor_fault_pilot_v5_node0/"
                  "SOLR-37/pilot/trials/r0001")
        plan = json.loads((source / "plan.json").read_text())["faults"]
        with gzip.open(source / "events.jsonl.gz", "rt") as stream:
            events = tuple(json.loads(line) for line in stream)
        strict = runner.audit_trial(events, plan)
        self.assertTrue(strict["valid"])
        last = max(row["seq"] for row in events
                   if row.get("type") == "FAULT_APPLIED"
                   and row.get("fault_id") == plan[-1]["fault_id"])
        proof = runner.evaluate(events, min_target_seq=last,
                                actor=(plan[-1]["point"]["node"], 0),
                                reader_ref=strict["fault_receipts"][-1]["reader_ref"])
        self.assertEqual(100, proof["strict_witness_count"])
        self.assertEqual({"shard-4"}, {row["node"] for row in proof["qualified_points"]})

    def test_unmatched_fault_cannot_seed_novelty_or_candidate(self):
        original_apply = runner.campaign._apply_result
        original_mutate = runner.campaign.mutate
        original_replay = runner.scheduler._replay_point
        original_run = runner.campaign._run_trial
        captured = []
        try:
            runner.campaign._apply_result = lambda state, config, result, item: captured.append(result)
            runner.install_v6_runtime()
            with tempfile.TemporaryDirectory() as directory:
                trial = Path(directory) / "trials/r0007"
                trial.mkdir(parents=True)
                with gzip.open(trial / "events.jsonl.gz", "wt") as stream:
                    stream.write("{}\n")
                result = {"trial_id": 7, "plan": [runner.candidate(
                    "shard-2", 33, 54, "test")["faults"][0]],
                    "feedback": {"status": "observed", "target_reached": True,
                                 "all_faults_effective": True,
                                 "target_exception_candidate": True,
                                 "doors": [{"site": runner.DOOR}],
                                 "coverage_ids": ["bad"],
                                 "closure_coverage_ids": ["bad"],
                                 "closure_edges": [{"kind": "state"}]}}
                runner.campaign._apply_result({"out": directory}, {}, result, None)
            feedback = captured[0]["feedback"]
            self.assertFalse(feedback["all_faults_effective"])
            self.assertFalse(feedback["target_reached"])
            self.assertFalse(feedback["target_exception_candidate"])
            for key in ("doors", "coverage_ids", "closure_coverage_ids", "closure_edges"):
                self.assertEqual([], feedback[key])
        finally:
            runner.campaign._apply_result = original_apply
            runner.campaign.mutate = original_mutate
            runner.scheduler._replay_point = original_replay
            runner.campaign._run_trial = original_run
            runner.pilot.audit_trial = runner.audit_trial


if __name__ == "__main__":
    unittest.main()
