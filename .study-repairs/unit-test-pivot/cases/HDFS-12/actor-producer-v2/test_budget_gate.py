#!/usr/bin/env python3
"""Check that the budget gate only skips a fault-explained lost target."""

import unittest

from run_budget_gate import fault_induced_target_loss


class TargetLossGateTests(unittest.TestCase):
    def test_exact_injected_sasl_failure_with_lost_target(self):
        manifest = {"returncode": 1}
        result = {"classification": "unmatched_or_target_lost",
                  "exact_order_applied": True, "requested_faults": 3,
                  "matched_faults": 3, "applied_faults": 3,
                  "postfault_target_count": 0}
        log = ("IOException: V2 injected I/O at "
               "SaslDataTransferServer.doSaslHandshake#readMagic\n"
               "Fail to get block MD5")
        trace = [item for index in range(3) for item in
                 ({"event": "FAULT_MATCHED", "planIndex": index,
                   "seq": 2 * index + 1},
                  {"event": "FAULT_APPLIED", "planIndex": index,
                   "seq": 2 * index + 2})]
        self.assertTrue(fault_induced_target_loss(manifest, result, log, trace))
        self.assertTrue(fault_induced_target_loss(manifest,
                        dict(result, requested_faults=4, exact_order_applied=False),
                        log, trace))
        self.assertFalse(fault_induced_target_loss(manifest, result,
                         log + "\njava.net.BindException: Address already in use", trace))
        self.assertFalse(fault_induced_target_loss(manifest, result,
                         "Fail to get block MD5 without an injected I/O stack", trace))
        self.assertFalse(fault_induced_target_loss(manifest,
                         dict(result, applied_faults=2), log, trace))
        self.assertFalse(fault_induced_target_loss(manifest,
                         dict(result, postfault_target_count=1), log, trace))
        self.assertFalse(fault_induced_target_loss(manifest, result, log,
                         trace + [{"event": "TARGET_CHECK", "caseId": "HDFS-12",
                                   "seq": 7}]))


if __name__ == "__main__":
    unittest.main()
