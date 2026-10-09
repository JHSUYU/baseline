"""Contract tests for causal evidence, target oracle, and resumability."""

from __future__ import annotations

import json
import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

from .campaign import (_run_trial, _validate_site_catalog, run,
                       verify_validated_recovery_sites)
from .events import Trace, _encoded_address, event_address
from .feedback import analyze
from .graph import OccurrenceGraph
from .scheduler import mutate, pick_next, score


def event(kind: str, index: int, node: str, occurrence: str, **fields):
    return {"type": kind, "id": f"e{index}", "seq": index, "node": node,
            "epoch": 0, "occurrence": occurrence, "region": occurrence, **fields}


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.target = {"site": "Target#throw:10", "exception_class": "java.io.IOException",
                       "node": "B"}
        self.events = (
            event("REGION_ENTER", 1, "A", "a"),
            event("DOOR_OBSERVED", 2, "A", "a", site="Door#read:2", hit=1,
                  fault_type="EXCEPTION", exception_class="java.io.IOException"),
            event("SEND", 3, "A", "a", transport="rpc", correlation="c1",
                  attempt=0, half="request", port="p"),
            event("REGION_ENTER", 4, "B", "b"),
            event("RECV", 5, "B", "b", transport="rpc", correlation="c1",
                  attempt=0, half="request", port="p"),
            event("TARGET_CHECK", 6, "B", "b", site="Target#throw:10", outcome=False),
        )

    def test_occurrence_address_cache_preserves_json_encoding_and_identity_gate(self):
        for node, epoch, occurrence in (
            ("zk\"\\0", 2, "region/α\n1"),
            ("hdfs-client", {"restart": 3}, "ctx:17"),
            ("solr-1", None, "handler"),
            ("unknown", 0, "unbound"),
            ("zk0", 0, ""),
        ):
            row = {"node": node, "epoch": epoch, "occurrence": occurrence}
            expected = (json.dumps([str(node), str(epoch), occurrence],
                                   separators=(",", ":"))
                        if node not in ("", "unknown", "null", "None")
                        and epoch is not None and occurrence else None)
            self.assertEqual(event_address(row), expected)
            self.assertEqual(event_address(row), expected)
        self.assertEqual(_encoded_address.cache_info().maxsize, 8192)

    def test_exact_rpc_edge_and_target_closure(self):
        feedback = analyze(Trace(self.events), self.target, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "observed")
        self.assertEqual(feedback["graph"]["edges_by_kind"]["rpc"], 1)
        self.assertEqual(len(feedback["closure_occurrences"]), 2)
        self.assertTrue(feedback["doors"][0]["in_closure"])

    def test_ambiguous_rpc_never_creates_an_edge(self):
        duplicate = event("SEND", 7, "A", "other", transport="rpc", correlation="c1",
                          attempt=0, half="request", port="p")
        graph = OccurrenceGraph(self.events + (duplicate,))
        self.assertEqual(graph.summary()["edges"], 0)
        self.assertEqual(graph.gaps["rpc_ambiguous"], 1)

    def test_unknown_actor_cannot_produce_observed_causal_rpc_edge(self):
        events = (
            event("DOOR_OBSERVED", 0, "unknown", "http:unbound", site="HTTP#read:door:1",
                  hit=1, door_ordinal=1, fault_type="EXCEPTION",
                  exception_class="java.io.IOException"),
            event("SEND", 1, "unknown", "http:unbound", transport="http",
                  correlation="req-1", port="request"),
            event("RECV", 2, "solr-1", "handler:1", transport="http",
                  correlation="req-1", port="request"),
            event("TARGET_CHECK", 3, "solr-1", "handler:1", site="T#guard"),
        )
        target = {"check_sites": ["T#guard"], "throw_site": "T#throw",
                  "exception_class": "java.io.IOException"}
        feedback = analyze(Trace(events), target, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["graph"]["edges"], 0)
        self.assertEqual(feedback["graph"]["gaps"]["rpc_missing_occurrence"], 1)
        self.assertEqual(feedback["graph"]["gaps"]["door_unknown_actor"], 1)
        self.assertEqual(feedback["observed_door_events"], 1)
        self.assertEqual(feedback["doors"], [])
        self.assertEqual(len(feedback["closure_occurrences"]), 1)

    def test_sampled_state_version_is_only_a_candidate_edge(self):
        sampled = (
            event("STATE_WRITE", 1, "A", "a", object="o1", key="k", version=1,
                  version_confidence="sampled"),
            event("STATE_READ", 2, "B", "b", object="o1", key="k", version=1,
                  version_confidence="sampled"),
        )
        graph = OccurrenceGraph(sampled)
        self.assertEqual(graph.summary()["edges"], 0)
        self.assertEqual(graph.summary()["candidate_edges"], 1)
        self.assertEqual(next(iter(graph.candidate_edges)).certainty, "candidate")
        target_address = '["B","0","b"]'
        self.assertEqual(len(graph.backward_closure(target_address)), 2)
        self.assertEqual(len(graph.backward_closure(target_address,
                                                    include_candidates=False)), 1)

    def test_direct_region_parent_rejects_cross_epoch_or_future_identity(self):
        events = (
            event("REGION_ENTER", 1, "zk2", "old", epoch=0),
            event("REGION_ENTER", 2, "zk2", "new", epoch=1, parent_id="old"),
            event("REGION_ENTER", 3, "zk2", "newer", epoch=1, parent_id="e1"),
            event("REGION_ENTER", 4, "zk2", "later", epoch=1),
            event("REGION_ENTER", 0, "zk2", "earlier", epoch=1, parent_id="later"),
        )
        graph = OccurrenceGraph(events)
        self.assertEqual(graph.summary()["edges"], 0)
        self.assertEqual(graph.gaps["unmatched_parent"], 3)

    def test_duplicate_event_id_cannot_prove_region_parent(self):
        first = event("REGION_ENTER", 1, "zk2", "parent-a")
        second = event("REGION_ENTER", 2, "zk2", "parent-b")
        second["id"] = first["id"]
        child = event("REGION_ENTER", 3, "zk2", "child", parent_id=first["id"])
        graph = OccurrenceGraph((first, second, child))
        self.assertEqual(graph.summary()["edges"], 0)
        self.assertEqual(graph.gaps["duplicate_event_id"], 1)
        self.assertEqual(graph.gaps["unmatched_parent"], 1)

    def test_handoff_token_connects_unscoped_receive_to_region(self):
        events = (
            event("SEND", 1, "A", "a", transport="rpc", correlation="c1", port="p"),
            event("RECV", 2, "B", "unscoped:B:0:c1", transport="rpc",
                  correlation="c1", port="p"),
            event("REGION_ENTER", 3, "B", "b", parent_id="c1"),
            event("TARGET_CHECK", 4, "B", "b", site="Target#throw:10"),
        )
        feedback = analyze(Trace(events), self.target, [], return_code=0, timed_out=False)
        self.assertEqual(len(feedback["closure_occurrences"]), 3)
        self.assertEqual(feedback["graph"]["edges_by_kind"]["rpc"], 1)
        self.assertEqual(feedback["graph"]["edges_by_kind"]["region_parent"], 1)

    def test_request_region_does_not_attach_to_response_receive(self):
        events = (
            event("RECV", 1, "NN", "unscoped:NN:0:c1", correlation="c1", port="request"),
            event("REGION_ENTER", 2, "NN", "nn-call", parent_id="c1"),
            event("RECV", 3, "client", "unscoped:client:0:c1",
                  correlation="c1", port="response"),
        )
        graph = OccurrenceGraph(events)
        parents = [edge for edge in graph.edges if edge.kind == "region_parent"]
        self.assertEqual(len(parents), 1)
        self.assertIn("NN", parents[0].source)
        self.assertEqual(graph.gaps.get("unmatched_parent", 0), 0)

    def test_check_and_throw_can_have_distinct_sites(self):
        target = {"check_sites": ["Target#guard:9"],
                  "throw_site": "Target#throw:10",
                  "exception_class": "java.io.IOException", "node": "B"}
        events = (event("TARGET_CHECK", 1, "B", "b", site="Target#guard:9"),)
        feedback = analyze(Trace(events), target, [], return_code=0, timed_out=False)
        self.assertTrue(feedback["target_reached"])

    def test_same_actor_multiple_target_epochs_keep_separate_closures(self):
        second = event("TARGET_CHECK", 10, "B", "b2", site="Target#throw:10", epoch=1)
        feedback = analyze(Trace(self.events + (second,)), self.target, [],
                           return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "observed")
        self.assertFalse(feedback["target_identity_ambiguous"])
        self.assertEqual(len(feedback["target_closures"]), 2)
        self.assertEqual(len(feedback["closure_occurrences"]), 3)

    def test_multiple_named_target_actors_and_unknown_startup_gap(self):
        target = {"check_sites": ["C#guard"], "throw_site": "C#throw",
                  "exception_class": "java.io.IOException"}
        events = (
            event("TARGET_CHECK", 1, "unknown", "startup", site="C#guard"),
            event("TARGET_CHECK", 2, "solr-1", "r1", site="C#guard"),
            event("TARGET_CHECK", 3, "solr-2", "r2", site="C#guard"),
        )
        healthy = analyze(Trace(events), target, [], return_code=0, timed_out=False)
        self.assertEqual(healthy["status"], "observed")
        self.assertEqual(len(healthy["target_identity_gaps"]), 1)
        self.assertEqual({row["node"] for row in healthy["target_closures"]},
                         {"solr-1", "solr-2"})
        self.assertFalse(healthy["target_identity_ambiguous"])

        plan = [{"fault_id": "f1", "point": {"site": "D", "node": "solr-1",
                 "epoch": 0, "occurrence": "r1", "hit": 1}, "fault_type": "EXCEPTION"}]
        prefix = (event("FAULT_MATCHED", 4, "solr-1", "r1", fault_id="f1"),
                  event("FAULT_APPLIED", 5, "solr-1", "r1", fault_id="f1"),
                  event("TARGET_CHECK", 6, "solr-2", "r2", site="C#guard"))
        target["nodes"] = ["solr-1", "solr-2"]
        wrong = analyze(Trace(events + prefix + (
            event("TARGET_THROW", 7, "unknown", "startup", site="C#throw",
                  exception_class="java.io.IOException"),)),
            target, plan, return_code=1, timed_out=False)
        self.assertFalse(wrong["target_exception_candidate"])
        right = analyze(Trace(events + prefix + (
            event("TARGET_THROW", 7, "solr-2", "r2", site="C#throw",
                  exception_class="java.io.IOException"),)),
            target, plan, return_code=1, timed_out=False)
        self.assertTrue(right["target_exception_candidate"])

    def test_loaded_target_class_hash_and_loader_are_attested(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "sites.jsonl"
            target = {"check_sites": ["pkg.C#run()V@1:branch:1"],
                      "throw_site": "pkg.C#run()V@2:throw:1"}
            rows = [{"type": kind, "site": site, "class_name": "pkg.C",
                     "bytecode_sha256": "a" * 64, "class_loader_id": "Loader@1"}
                    for kind, site in (("TARGET_CHECK", target["check_sites"][0]),
                                       ("TARGET_THROW", target["throw_site"]))]
            catalog.write_text("".join(json.dumps(row) + "\n" for row in rows))
            valid = _validate_site_catalog(catalog, target, True, "a" * 64)
            self.assertTrue(valid["valid"])
            self.assertTrue(valid["class_hash_match"])
            self.assertFalse(_validate_site_catalog(catalog, target, True, "b" * 64)["valid"])
            rows[1]["class_loader_id"] = "Loader@2"
            catalog.write_text("".join(json.dumps(row) + "\n" for row in rows))
            self.assertFalse(_validate_site_catalog(catalog, target, True, "a" * 64)["valid"])

    def test_throw_requires_guard_in_same_post_fault_occurrence(self):
        plan = [{"fault_id": "f1", "point": {"site": "Door#read:2", "node": "A",
                  "epoch": 0, "occurrence": "a", "hit": 1}, "fault_type": "EXCEPTION"}]
        events = self.events[:2] + (
            event("FAULT_MATCHED", 20, "A", "a", fault_id="f1"),
            event("FAULT_APPLIED", 21, "A", "a", fault_id="f1"),
        ) + self.events[2:] + (
            event("TARGET_THROW", 22, "B", "other", site="Target#throw:10",
                  exception_class="java.io.IOException"),)
        feedback = analyze(Trace(events), self.target, plan,
                           return_code=1, timed_out=False)
        self.assertFalse(feedback["target_exception_candidate"])

    def test_target_exception_requires_matched_applied_fault_and_exact_site(self):
        plan = [{"fault_id": "f1", "point": {"site": "Door#read:2", "node": "A",
                  "epoch": 0, "occurrence": "a", "hit": 1},
                 "fault_type": "EXCEPTION", "exception_class": "java.io.IOException"}]
        injected = self.events[:2] + (
            event("FAULT_MATCHED", 3, "A", "a", fault_id="f1"),
            event("FAULT_APPLIED", 4, "A", "a", fault_id="f1"),
            event("SEND", 5, "A", "a", transport="rpc", correlation="c1",
                  attempt=0, half="request", port="p"),
            event("REGION_ENTER", 6, "B", "b"),
            event("RECV", 7, "B", "b", transport="rpc", correlation="c1",
                  attempt=0, half="request", port="p"),
            event("TARGET_CHECK", 8, "B", "b", site="Target#throw:10"),
            event("TARGET_THROW", 9, "B", "b", site="Target#throw:10",
                  exception_class="java.io.IOException"),)
        feedback = analyze(Trace(injected), self.target, plan, return_code=1, timed_out=False)
        self.assertTrue(feedback["target_exception_candidate"])
        wrong = injected[:-1] + (event("TARGET_THROW", 9, "B", "b", site="Other#throw:10",
                                      exception_class="java.io.IOException"),)
        self.assertFalse(analyze(Trace(wrong), self.target, plan,
                                 return_code=1, timed_out=False)["target_exception_candidate"])
        unmatched = tuple(e for e in injected if e["type"] != "FAULT_MATCHED")
        self.assertFalse(analyze(Trace(unmatched), self.target, plan,
                                 return_code=1, timed_out=False)["target_exception_candidate"])

    def test_mutation_stays_in_target_closure(self):
        feedback = analyze(Trace(self.events), self.target, [], return_code=0, timed_out=False)
        config = {"budget": {"max_faults_per_trial": 8},
                  "fault_types": ["EXCEPTION"], "exception_class": "java.io.IOException"}
        plans = mutate([], feedback, config)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["selection_reason"], "dynamic_closure")

    def test_door_ordinal_replays_without_volatile_occurrence(self):
        healthy = (
            event("DOOR_OBSERVED", 1, "nn0", "rpc:random-client-id-1", site="NN#rpc:door:1",
                  hit=1, door_ordinal=3, fault_type="EXCEPTION",
                  exception_class="java.io.IOException"),
            event("TARGET_CHECK", 2, "client", "target:1", site="T#guard"),
        )
        target = {"check_sites": ["T#guard"], "throw_site": "T#throw",
                  "exception_class": "java.io.IOException", "nodes": ["client"]}
        feedback = analyze(Trace(healthy), target, [], return_code=0, timed_out=False)
        door = feedback["doors"][0]
        self.assertEqual(door["point"], {"site": "NN#rpc:door:1", "node": "nn0",
                                          "epoch": 0, "door_ordinal": 3})
        self.assertNotIn("occurrence", door["point"])
        config = {"budget": {"max_faults_per_trial": 2},
                  "fault_types": ["EXCEPTION"], "exception_class": "java.io.IOException"}
        plan = mutate([], feedback, config)[0]["faults"]
        self.assertNotIn("occurrence", plan[0]["point"])
        self.assertNotIn("hit", plan[0]["point"])
        faulted = (
            event("DOOR_OBSERVED", 1, "nn0", "rpc:random-client-id-2", site="NN#rpc:door:1",
                  hit=1, door_ordinal=3),
            event("FAULT_MATCHED", 2, "nn0", "rpc:random-client-id-2",
                  site="NN#rpc:door:1", door_ordinal=3, fault_id=plan[0]["fault_id"]),
            event("FAULT_APPLIED", 3, "nn0", "rpc:random-client-id-2",
                  site="NN#rpc:door:1", door_ordinal=3, fault_id=plan[0]["fault_id"]),
            event("TARGET_CHECK", 4, "client", "target:1", site="T#guard"),
            event("TARGET_THROW", 5, "client", "target:1", site="T#throw",
                  exception_class="java.io.IOException"),
        )
        replay = analyze(Trace(faulted), target, plan, return_code=1, timed_out=False)
        self.assertTrue(replay["all_faults_effective"])
        self.assertTrue(replay["target_exception_candidate"])
        bad_receipt = dict(faulted[2], door_ordinal=4)
        mismatch = analyze(Trace(faulted[:2] + (bad_receipt,) + faulted[3:]),
                           target, plan, return_code=1, timed_out=False)
        self.assertEqual(mismatch["status"], "fault_identity_mismatch")
        self.assertFalse(mismatch["target_exception_candidate"])

    def test_local_timeline_door_requires_strict_same_actor_occurrence_order(self):
        target = {"check_sites": ["C#guard"], "throw_site": "C#throw",
                  "exception_class": "java.io.IOException"}
        check = event("TARGET_CHECK", 10, "zk0", "load-db", site="C#guard")
        def door(seq, node="zk0", occurrence="load-db", epoch=0):
            return event("DOOR_OBSERVED", seq, node, occurrence, epoch=epoch,
                         site="C#read:door:1", hit=1, door_ordinal=1,
                         fault_type="EXCEPTION", exception_class="java.io.IOException")
        valid = analyze(Trace((door(9), check)), target, [], return_code=0,
                        timed_out=False, allow_local_timeline_doors=True)
        self.assertEqual(valid["local_timeline_doors"], 1)
        proof = valid["doors"][0]["local_timeline_evidence"]
        self.assertEqual(proof["kind"], "observed_local_timeline")
        self.assertEqual((proof["door_seq"], proof["target_check_seq"]), (9, 10))
        default = analyze(Trace((door(9), check)), target, [], return_code=0,
                          timed_out=False)
        self.assertNotIn("local_timeline_doors", default)
        self.assertNotIn("local_timeline_evidence", default["doors"][0])
        for invalid in (door(11), door(9, node="zk1"), door(9, epoch=1),
                        door(9, occurrence="other"), door(9, node="unknown")):
            observed = analyze(Trace((invalid, check)), target, [], return_code=0,
                               timed_out=False, allow_local_timeline_doors=True)
            self.assertEqual(observed["local_timeline_doors"], 0)

    def test_static_frontier_location_can_seed_dormant_door(self):
        feedback = {"doors": [{"point": {"site": "pkg.C#work()V@42:door:1",
                                         "node": "A", "epoch": 0, "occurrence": "a", "hit": 1},
                              "site": "pkg.C#work()V@42:door:1", "event_seq": 1,
                              "fault_type": "EXCEPTION", "in_closure": False}],
                    "last_fault_seq": -1, "target_reached": True,
                    "all_faults_effective": False}
        config = {"budget": {"max_faults_per_trial": 8},
                  "fault_types": ["EXCEPTION"], "exception_class": "java.io.IOException",
                  "static_fault_locations": [{"class": "pkg.C", "method": "<pkg.C: void work()>",
                                              "line": 42}]}
        plans = mutate([], feedback, config)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["selection_reason"], "static_candidate")

    def test_validated_recovery_priority_retains_periodic_exploration(self):
        def door(site, ordinal, closure):
            return {"point": {"site": site, "node": "N", "epoch": 0,
                              "door_ordinal": ordinal},
                    "site": site, "event_seq": ordinal,
                    "fault_type": "EXCEPTION", "exception_class": "java.io.IOException",
                    "in_closure": closure}
        feedback = {"doors": [door("C#validated:door:1", 1, False),
                               door("C#closure:door:1", 2, True),
                               door("C#outside:door:1", 3, False)],
                    "last_fault_seq": -1, "target_reached": True,
                    "all_faults_effective": False}
        config = {"budget": {"max_faults_per_trial": 2},
                  "fault_types": ["EXCEPTION"],
                  "validated_recovery_sites": [{"site": "C#validated:door:1",
                                                 "evidence": [{"trial_result": "pilot",
                                                               "sha256": "a" * 64}]}]}
        plans = mutate([], feedback, config)
        self.assertEqual({p["selection_reason"] for p in plans},
                         {"validated_recovery", "dynamic_closure", "bounded_exploration"})
        for plan in plans:
            plan["priority"] = score(plan, {**feedback, "novelty": {}}, set(), 0)
            plan["queued_at"] = 0
        validated = next(p for p in plans if p["selection_reason"] == "validated_recovery")
        closure = next(p for p in plans if p["selection_reason"] == "dynamic_closure")
        self.assertGreater(validated["priority"], closure["priority"])
        normal = pick_next([dict(p) for p in plans], 1, 0, config)
        self.assertEqual(normal["selection_reason"], "validated_recovery")
        exploration = pick_next([dict(p) for p in plans], 5, 4, config)
        self.assertNotEqual(exploration["selection_reason"], "validated_recovery")

    def test_validated_recovery_evidence_requires_pinned_target_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "trial.json"
            result = {"case_id": "TEST-PILOT", "plan": [{"point": {"site": "C#door"}}],
                      "feedback": {"all_faults_effective": True,
                                   "fault_identity_valid": True, "target_reached": True},
                      "site_catalog_validation": {"observed_target_class_sha256": "b" * 64}}
            receipt.write_text(json.dumps(result))
            config = {"case_id": "TEST-PILOT", "expected_target_class_sha256": "b" * 64,
                      "validated_recovery_sites": [{"site": "C#door", "evidence": [{
                          "trial_result": str(receipt),
                          "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}]}]}
            verify_validated_recovery_sites(config)
            result["feedback"]["target_reached"] = False
            receipt.write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                verify_validated_recovery_sites(config)

    def test_campaign_resumes_without_repeating_completed_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake.py"
            fake.write_text('''import json, os\nfrom pathlib import Path\np=json.loads(Path(os.environ["MALLORY_PLAN_FILE"]).read_text())\ncount=Path("count");count.write_text(str(int(count.read_text())+1 if count.exists() else 1))\ne=[]\ndef add(t,i,node,occ,**kw):e.append(dict(type=t,id="e"+str(i),seq=i,node=node,epoch=0,occurrence=occ,**kw))\nadd("DOOR_OBSERVED",1,"A","a",site="Door#read:2",hit=1,fault_type="EXCEPTION",exception_class="java.io.IOException")\nadd("SEND",2,"A","a",transport="rpc",correlation="c1",attempt=0,half="request",port="p")\nadd("RECV",3,"B","b",transport="rpc",correlation="c1",attempt=0,half="request",port="p")\nfor f in p["faults"]:\n add("FAULT_MATCHED",4,"A","a",fault_id=f["fault_id"])\n add("FAULT_APPLIED",5,"A","a",fault_id=f["fault_id"])\nadd("TARGET_CHECK",6,"B","b",site="Target#throw:10",region="b",outcome=bool(p["faults"]))\nif p["faults"]:add("TARGET_THROW",7,"B","b",site="Target#throw:10",region="b",exception_class="java.io.IOException")\nPath(os.environ["MALLORY_EVENT_FILE"]).write_text("".join(json.dumps(x)+"\\n" for x in e))\n''', encoding="utf-8")
            config = {"case_id": "TEST-01", "system": "test",
                      "cluster_test": "Fake#test", "command": ["python3", str(fake)],
                      "cwd": str(root), "target": self.target,
                      "budget": {"trials": 1, "seconds": 30,
                                 "max_faults_per_trial": 2, "trial_timeout_seconds": 5},
                      "fault_types": ["EXCEPTION"],
                      "exception_class": "java.io.IOException",
                      "candidate_replays": 0}
            config_path = root / "case.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            out = root / "out"
            result = run(config_path, out)
            self.assertEqual(result["status"], "budget_exhausted")
            self.assertEqual(result["completed_trials"], [0, 1])
            self.assertEqual((root / "count").read_text(), "2")
            self.assertEqual(run(config_path, out)["completed_trials"], [0, 1])
            self.assertEqual((root / "count").read_text(), "2")
            summary = json.loads((out / "result.json").read_text())
            self.assertEqual(summary["strict_injected_trials"], 1)
            self.assertEqual(summary["exact_exception_trials"], 1)
            self.assertIsNone(summary["new_bug"])
            for trial_id in (0, 1):
                trial = out / "trials" / f"r{trial_id:04d}"
                row = json.loads((trial / "result.json").read_text())
                self.assertFalse((trial / "events.jsonl").exists())
                compressed = trial / "events.jsonl.gz"
                self.assertTrue(compressed.is_file())
                with gzip.open(compressed, "rb") as restored:
                    self.assertEqual(hashlib.sha256(restored.read()).hexdigest(),
                                     row["events_sha256"])
            calibration = run(config_path, root / "calibration", calibration_only=True)
            self.assertEqual(calibration["status"], "calibration_complete")
            self.assertEqual(calibration["completed_trials"], [0])
            self.assertEqual((root / "count").read_text(), "3")
            self.assertEqual(run(config_path, root / "calibration", calibration_only=True)
                             ["completed_trials"], [0])
            self.assertEqual((root / "count").read_text(), "3")

    def test_surefire_argline_avoids_maven_launcher_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_jar = root / "agent.jar"
            fake_jar.write_bytes(b"placeholder")
            script = root / "fake.py"
            script.write_text('''import json, os, sys\nfrom pathlib import Path\nPath("argv.json").write_text(json.dumps(sys.argv[1:]))\nPath("java_options.txt").write_text(os.environ.get("JAVA_TOOL_OPTIONS", ""))\ne=dict(type="TARGET_CHECK",id="e1",seq=1,node="B",epoch=0,occurrence="b",region="b",site="Target#throw:10")\nPath(os.environ["MALLORY_EVENT_FILE"]).write_text(json.dumps(e)+"\\n")\n''')
            config = {"case_id": "TEST-SUREFIRE", "system": "test",
                      "cluster_test": "Fake#test", "command": ["python3", str(script)],
                      "cwd": str(root), "target": self.target,
                      "budget": {"trials": 1, "seconds": 10,
                                 "max_faults_per_trial": 2, "trial_timeout_seconds": 5},
                      "agent_jar": str(fake_jar),
                      "agent_transport": "surefire_argline"}
            result = _run_trial(config, root / "out", 0, [], lambda _pid: None, None)
            self.assertTrue(result["feedback"]["target_reached"])
            args = json.loads((root / "argv.json").read_text())
            self.assertEqual(len(args), 1)
            self.assertTrue(args[0].startswith("-DargLine=-javaagent:"))
            self.assertNotIn(str(fake_jar), (root / "java_options.txt").read_text())
            config["agent_arg_property"] = "mallory.agent.arg"
            _run_trial(config, root / "out2", 0, [], lambda _pid: None, None)
            args = json.loads((root / "argv.json").read_text())
            self.assertTrue(args[0].startswith("-Dmallory.agent.arg=-javaagent:"))

    def test_calibration_requires_pinned_runtime_class_before_fault_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / "agent.jar"
            agent.write_bytes(b"placeholder")
            script = root / "fake.py"
            script.write_text('''import json, os
from pathlib import Path
p=json.loads(Path(os.environ["MALLORY_PLAN_FILE"]).read_text())["faults"]
c="pkg.C"; check="pkg.C#run()V@1:branch:1"; throw="pkg.C#run()V@2:throw:1"
rows=[dict(type=t,site=s,class_name=c,bytecode_sha256="a"*64,class_loader_id="Loader@1") for t,s in (("TARGET_CHECK",check),("TARGET_THROW",throw))]
Path(os.environ["MALLORY_SITE_CATALOG"]).write_text("".join(json.dumps(x)+"\\n" for x in rows))
e=[]
def add(t,i,node,occ,**kw):e.append(dict(type=t,id="e"+str(i),seq=i,node=node,epoch=0,occurrence=occ,region=occ,**kw))
add("DOOR_OBSERVED",1,"node-a","r1",site="pkg.C#run()V@0:door:1",hit=1,fault_type="EXCEPTION",exception_class="java.io.IOException")
for f in p:
 add("FAULT_MATCHED",2,"node-a","r1",fault_id=f["fault_id"])
 add("FAULT_APPLIED",3,"node-a","r1",fault_id=f["fault_id"])
add("TARGET_CHECK",4,"unknown","startup",site=check)
add("TARGET_CHECK",5,"node-a","r1",site=check)
add("TARGET_CHECK",6,"node-b","r2",site=check)
if p:add("TARGET_THROW",7,"node-b","r2",site=throw,exception_class="java.io.IOException")
Path(os.environ["MALLORY_EVENT_FILE"]).write_text("".join(json.dumps(x)+"\\n" for x in e))
''')
            config = {"case_id": "TEST-ATTEST", "system": "test", "cluster_test": "Fake#test",
                      "command": ["python3", str(script), "--output", "{trial_dir}"],
                      "cwd": str(root), "agent_jar": str(agent),
                      "calibration_only": True,
                      "target": {"check_sites": ["pkg.C#run()V@1:branch:1"],
                                 "throw_site": "pkg.C#run()V@2:throw:1",
                                 "exception_class": "java.io.IOException"},
                      "budget": {"trials": 1, "seconds": 30,
                                 "max_faults_per_trial": 2, "trial_timeout_seconds": 5},
                      "fault_types": ["EXCEPTION"], "candidate_replays": 0}
            config_path = root / "preliminary.json"
            config_path.write_text(json.dumps(config))
            calibration = run(config_path, root / "calibration")
            self.assertEqual(calibration["status"], "calibration_complete")
            self.assertEqual(calibration["completed_trials"], [0])
            self.assertEqual(calibration["target_binding"],
                             {"nodes": ["node-a", "node-b"]})
            receipt = json.loads((root / "calibration/result.json").read_text())
            self.assertEqual(len(receipt["target_identity_gaps"]), 1)
            self.assertIn("target_class_hash_unpinned",
                          receipt["runtime_attestation"]["reasons"])
            config.update({"calibration_only": False, "auto_promote_if_healthy": True})
            unpinned_path = root / "unpinned.json"
            unpinned_path.write_text(json.dumps(config))
            unpinned = run(unpinned_path, root / "unpinned")
            self.assertEqual(unpinned["status"], "healthy_attestation_failed")
            self.assertEqual(unpinned["completed_trials"], [0])
            config.update({"calibration_only": False,
                           "auto_promote_if_healthy": True,
                           "expected_target_class_sha256": "a" * 64})
            promoted_path = root / "promoted.json"
            promoted_path.write_text(json.dumps(config))
            promoted = run(promoted_path, root / "campaign")
            self.assertEqual(promoted["completed_trials"], [0, 1])
            self.assertTrue(promoted["runtime_attestation"]["valid"])
            final = json.loads((root / "campaign/result.json").read_text())
            self.assertEqual(final["strict_injected_trials"], 1)
            self.assertEqual(final["exact_exception_trials"], 1)


if __name__ == "__main__":
    unittest.main()
