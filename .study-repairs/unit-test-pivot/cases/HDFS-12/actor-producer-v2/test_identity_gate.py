import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from identity_gate import SITES, evaluate


class StrictGateTest(unittest.TestCase):
    def fixture(self, root: Path, target_actor: str = "episode=1/dn=1/dirs=dfs/data/data1",
                target_resource: str = "BP0", extra_throw: bool = False,
                case: str = "HDFS-11"):
        actor = "episode=1/dn=1/dirs=dfs/data/data1"
        source = actor + "/resource=BP0"
        site = "SaslDataTransferServer.doSaslHandshake#readMagic"
        common = dict(marker="FAULT:HDFS_SASL:READ", siteId=site, sourceKey=source,
                      occurrence=source + "/site=" + site, hitOrdinal=1,
                      actorLocalOrdinal=1, faultActor=actor, resource="BP0")
        trace = [dict(event="FAULT_POINT_OBSERVED", seq=1, **common),
                 dict(event="FAULT_MATCHED", seq=2, planIndex=0,
                      faultType="IOException", requiredRawKeyId="-", **common),
                 dict(event="FAULT_APPLIED", seq=3, planIndex=0,
                      faultType="IOException", requiredRawKeyId="-", **common),
                 dict(event="TARGET_CHECK", seq=4, caseId=case,
                      siteId=SITES[case][0],
                      targetActor=target_actor, resource=target_resource)]
        if extra_throw:
            trace.append(dict(event="TARGET_THROW", seq=5, caseId=case,
                              siteId=SITES[case][1],
                              targetActor=target_actor, resource=target_resource,
                              exception=SITES[case][2]))
        run = root / "run"
        run.mkdir()
        (run / "manifest.json").write_text(json.dumps(dict(test="original[0]",
                                                          elapsed_seconds=2, returncode=0)))
        (run / "runtime_trace.jsonl").write_text("".join(json.dumps(row) + "\n" for row in trace))
        plan = root / "plan.tsv"
        plan.write_text("\t".join((common["marker"], site, actor, "BP0", "1", "IOException", "-")) + "\n")
        receipt = root / "healthy_receipt.json"
        receipt.write_text(json.dumps(dict(**{"pass": True}, case_id=case,
                                           healthy_target_throw_count=0)))
        return run, plan, receipt

    def test_exact_same_actor_postfault_target(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory), extra_throw=True)
            result = evaluate("HDFS-11", run, plan, receipt)
            self.assertTrue(result["valid_for_feedback"])
            self.assertTrue(result["target_exception_candidate"])

    def test_other_datanode_is_not_postfault_target(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(
                Path(directory), target_actor="episode=1/dn=2/dirs=dfs/data/data3")
            result = evaluate("HDFS-11", run, plan, receipt)
            self.assertFalse(result["valid_for_feedback"])

    def test_other_cluster_incarnation_is_not_postfault_target(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(
                Path(directory), target_actor="episode=2/dn=1/dirs=dfs/data/data1")
            result = evaluate("HDFS-11", run, plan, receipt)
            self.assertFalse(result["valid_for_feedback"])

    def test_other_block_pool_is_not_postfault_target(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory), target_resource="BP1")
            result = evaluate("HDFS-11", run, plan, receipt)
            self.assertFalse(result["valid_for_feedback"])

    def test_missing_applied_receipt_is_not_strict(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory))
            trace = [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()]
            trace = [row for row in trace if row["event"] != "FAULT_APPLIED"]
            (run / "runtime_trace.jsonl").write_text("".join(json.dumps(row) + "\n" for row in trace))
            result = evaluate("HDFS-11", run, plan, receipt)
            self.assertFalse(result["exact_order_applied"])

    def test_hdfs12_selected_null_key_throw_is_candidate(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory), extra_throw=True,
                                              case="HDFS-12")
            result = evaluate("HDFS-12", run, plan, receipt)
            self.assertTrue(result["valid_for_feedback"])
            self.assertTrue(result["target_exception_candidate"])

    def test_hdfs12_earlier_expired_token_throw_is_not_selected(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory), case="HDFS-12")
            with (run / "runtime_trace.jsonl").open("a") as trace:
                trace.write(json.dumps(dict(event="TARGET_THROW", seq=5, caseId="HDFS-12",
                                            siteId="BlockTokenSecretManager.retrievePassword#L504",
                                            targetActor="episode=1/dn=1/dirs=dfs/data/data1",
                                            resource="BP0", exception=SITES["HDFS-12"][2])) + "\n")
            result = evaluate("HDFS-12", run, plan, receipt)
            self.assertTrue(result["valid_for_feedback"])
            self.assertFalse(result["target_exception_candidate"])

    def test_producer_raw_key_mismatch_is_not_strict(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory), case="HDFS-12")
            trace = [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()]
            site = "BPServiceActor.offerService#keyUpdateResponse/NN0"
            for row in trace[:3]:
                row["marker"] = "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE"
                row["siteId"] = site
                row["occurrence"] = row["sourceKey"] + "/site=" + site
                row["rawKeyId"] = 8171
                if row["event"] != "FAULT_POINT_OBSERVED":
                    row["requiredRawKeyId"] = "8172"
            (run / "runtime_trace.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in trace))
            plan.write_text("\t".join(("FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE", site,
                                       trace[0]["faultActor"], "BP0", "1", "IOException",
                                       "8172")) + "\n")
            result = evaluate("HDFS-12", run, plan, receipt)
            self.assertFalse(result["exact_order_applied"])

    def test_producer_matching_raw_key_is_strict(self):
        with TemporaryDirectory() as directory:
            run, plan, receipt = self.fixture(Path(directory), case="HDFS-12")
            trace = [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()]
            site = "BPServiceActor.offerService#keyUpdateResponse/NN0"
            for row in trace[:3]:
                row["marker"] = "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE"
                row["siteId"] = site
                row["occurrence"] = row["sourceKey"] + "/site=" + site
                row["rawKeyId"] = 8171
                if row["event"] != "FAULT_POINT_OBSERVED":
                    row["requiredRawKeyId"] = "8171"
            (run / "runtime_trace.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in trace))
            plan.write_text("\t".join(("FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE", site,
                                       trace[0]["faultActor"], "BP0", "1", "IOException",
                                       "8171")) + "\n")
            result = evaluate("HDFS-12", run, plan, receipt)
            self.assertTrue(result["exact_order_applied"])


if __name__ == "__main__":
    unittest.main()
