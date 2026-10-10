"""Offline tests for the SOLR-34 path and exact-target gate."""

import unittest

from audit_healthy import CHECK, THROW, NATIVE, TYPED, SYNTHETIC_STATE, CONFIG, evaluate


def fixture(target=False):
    result = dict(case_id="SOLR-34", status="calibration_complete",
                  cluster_test=CONFIG["cluster_test"], bootstrap_seed_valid=True,
                  runtime_attestation=dict(valid=True, exact_site_catalog_valid=True,
                      observed_target_class_sha256=CONFIG["expected_target_class_sha256"],
                      target_class_loader_ids=["loader"] ))
    pilot = dict(source_revision=CONFIG["mapping"]["source_git_revision"],
                 agent_sha256=CONFIG["mapping"]["agent_sha256"])
    junit = dict(status="passed", tests=1, failures=0, errors=0, skipped=0)
    catalog = [dict(site=NATIVE, resource_argument="first_string_parameter",
                    exception_class=TYPED), dict(site=CHECK), dict(site=THROW)]
    events = [dict(type="DOOR_OBSERVED", site=NATIVE, fault_type="EXCEPTION",
                   exception_class=TYPED, resource=SYNTHETIC_STATE,
                   node="node5", epoch=0, seq=10, door_ordinal=1)]
    if target:
        events.append(dict(type="TARGET_CHECK", site=CHECK, node="node5", epoch=0, seq=11))
    log = "\n".join(f"MALLORY_SOLR_NODE logical=node{i} physical=127.0.0.1:{8000+i}_solr epoch=0"
                    for i in range(1, 6))
    return result, pilot, junit, catalog, events, log


class HealthyGateTest(unittest.TestCase):
    def test_path_bootstrap_without_target_is_explicit(self):
        got = evaluate(*fixture())
        self.assertEqual("passed_path_bootstrap", got["status"])
        self.assertTrue(got["target_absent_bootstrap_only"])
        self.assertFalse(got["full_target_gate_passed"])

    def test_exact_target_after_typed_path_can_pass(self):
        self.assertTrue(evaluate(*fixture(target=True))["full_target_gate_passed"])

    def test_rejects_wrong_path_actor_and_catalog(self):
        args = fixture()
        args[4][0]["resource"] = "/collections/test_coll"
        with self.assertRaisesRegex(ValueError, "synthetic-state"):
            evaluate(*args)
        args = fixture()
        args[4][0]["node"] = "node4"
        with self.assertRaisesRegex(ValueError, "synthetic-state"):
            evaluate(*args)
        args = fixture()
        args[3][0].pop("resource_argument")
        with self.assertRaisesRegex(ValueError, "path-aware"):
            evaluate(*args)


if __name__ == "__main__":
    unittest.main()
