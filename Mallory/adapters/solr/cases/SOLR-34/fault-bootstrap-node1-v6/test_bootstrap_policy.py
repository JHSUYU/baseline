"""Offline negative controls for SOLR-34 resource and operation identity."""

import copy
import unittest

import bootstrap_policy as p

ROOT = "r:216"
INNER = "r:230"
PARENT = "node5:0:getCore:r:216:1"
INNER_OCC = "unscoped:node5:0:r:230:thread:281:segment:2"


def row(seq, kind, **extra):
    return {"seq": seq, "id": f"e{seq}", "type": kind, **extra}


def fixture():
    return [
        row(1, "REGION_ENTER", site=p.REGION, node=p.NODE, epoch=0,
            context=ROOT, occurrence=PARENT),
        row(2, "SEND", transport="solr-http", correlation="c"),
        row(3, "RECV", site="SolrDispatchFilter#doFilter", node=p.NODE,
            epoch=0, context=INNER, transport="solr-http", correlation="c"),
        row(4, "DOOR_OBSERVED", site=p.DOOR, resource=p.RESOURCE, node=p.NODE,
            epoch=0, context=INNER, occurrence=INNER_OCC, door_ordinal=5,
            thread="qtp-281", fault_type="EXCEPTION", exception_class=p.TYPED),
        row(9, "REGION_EXIT", site=p.REGION, node=p.NODE, epoch=0,
            context=ROOT, occurrence=PARENT),
    ]


def plan(resource=p.RESOURCE):
    return [{"fault_id": "f0", "point": {"site": p.DOOR, "node": p.NODE,
             "epoch": 0, "door_ordinal": 5, "resource": resource},
             "fault_type": "EXCEPTION", "exception_class": p.TYPED}]


class BootstrapPolicyTest(unittest.TestCase):
    def test_parent_path_http_request_witness(self):
        rows = fixture()
        witness = p.operation_witness(rows, rows[3])
        self.assertEqual(PARENT, witness["parent_getcore_occurrence"])
        self.assertEqual("e2", witness["http_send_id"])
        self.assertEqual("e3", witness["http_recv_id"])

    def test_wrong_resource_callback_and_other_actor_rejected(self):
        for update in ({"resource": "/collections/unrelated/state.json"},
                       {"thread": "zkCallback-1"}, {"node": "node3"},
                       {"context": "other:230"}, {"door_ordinal": None}):
            with self.subTest(update=update):
                rows = fixture()
                rows[3].update(update)
                self.assertIsNone(p.operation_witness(rows, rows[3]))

    def test_scheduler_receives_only_qualified_path_and_resource_is_in_plan(self):
        rows = fixture()
        feedback = {"doors": [{"site": p.DOOR, "event_seq": 4,
                               "point": {"site": p.DOOR, "node": p.NODE,
                                         "epoch": 0, "door_ordinal": 5}}]}
        enriched = p.annotate_feedback(rows, feedback, [])
        def original(parent, chosen, config, *, bootstrap):
            self.assertTrue(bootstrap)
            self.assertEqual(1, len(chosen["doors"]))
            return [{"faults": plan(None), "signature": "old"}]
        candidates = p.mutate([], enriched, {}, original,
                              lambda faults: repr(faults), bootstrap=True)
        self.assertEqual(p.RESOURCE, candidates[0]["faults"][0]["point"]["resource"])
        self.assertNotEqual("old", candidates[0]["signature"])
        bad = copy.deepcopy(enriched)
        bad["doors"][0]["resource"] = "/wrong"
        self.assertEqual([], p.mutate([], bad, {}, lambda *a, **k: [],
                                       repr, bootstrap=True))

    def test_fault_audit_requires_exact_resource_and_parent_target(self):
        rows = fixture()
        rows[4:4] = [row(5, "FAULT_MATCHED", site=p.DOOR, fault_id="f0",
                         resource=p.RESOURCE, node=p.NODE, epoch=0, context=INNER,
                         occurrence=INNER_OCC, door_ordinal=5),
                   row(6, "FAULT_APPLIED", site=p.DOOR, fault_id="f0",
                       resource=p.RESOURCE, node=p.NODE, epoch=0, context=INNER,
                       occurrence=INNER_OCC, door_ordinal=5),
                   row(7, "TARGET_CHECK", site=p.CHECK, node=p.NODE,
                       epoch=0, occurrence=PARENT),
                   row(8, "TARGET_THROW", site=p.NEW_THROW, node=p.NODE,
                       epoch=0, occurrence=PARENT)]
        catalog = [{"site": site} for site in (p.CHECK, p.RETHROW, p.NEW_THROW, p.DOOR)]
        audit = p.audit_trial(rows, plan(), catalog)
        self.assertTrue(audit["valid"])
        self.assertTrue(audit["target_after_fault"])
        self.assertEqual("selected_new_exception", audit["target_outcome"])
        wrong = copy.deepcopy(rows)
        wrong[5]["resource"] = "/wrong"
        self.assertEqual("fault_resource_or_operation_mismatch",
                         p.audit_trial(wrong, plan(), catalog)["status"])
        prior = copy.deepcopy(rows)
        prior[7]["site"] = p.RETHROW
        self.assertEqual("prior_exception_rethrow",
                         p.audit_trial(prior, plan(), catalog)["target_outcome"])
        foreign = copy.deepcopy(rows)
        foreign[6]["occurrence"] = "another-getCore"
        self.assertFalse(p.audit_trial(foreign, plan(), catalog)["target_after_fault"])


if __name__ == "__main__":
    unittest.main()
