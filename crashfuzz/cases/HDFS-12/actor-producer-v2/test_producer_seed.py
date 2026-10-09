import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from identity_gate import inspect_seed
from prepare_smoke import prepare


class ProducerSeedTest(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        actor = "episode=2/dn=1/dirs=dfs/data/data1"
        resource = "BP0"
        source = actor + "/resource=" + resource
        target = "BlockTokenSecretManager.retrievePassword#L511"
        site = "BPServiceActor.offerService#keyUpdateResponse/NN0"
        common = dict(faultActor=actor, resource=resource, rawBlockPoolId="BP-raw",
                      nnLogical="NN0", rawNameNodeEndpoint="127.0.0.1:10001",
                      rawDatanodeUuid="DN-raw", dnObjectHash=17, managerObjectHash=19,
                      managerIdentity=1,
                      rawKeyId=101, allKeyIds=[99, 100, 101],
                      commandIdentity=1, commandObjectHash=23,
                      keyRole="ROTATED_CURRENT")
        sasl = dict(event="FAULT_POINT_OBSERVED", seq=4, marker="FAULT:HDFS_SASL:READ",
                    siteId="SaslDataTransferServer.doSaslHandshake#readMagic",
                    sourceKey=source, occurrence=source + "/site=SaslDataTransferServer.doSaslHandshake#readMagic",
                    hitOrdinal=1, actorLocalOrdinal=1, faultActor=actor, resource=resource)
        producer = dict(event="FAULT_POINT_OBSERVED", seq=9,
                        marker="FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE", siteId=site,
                        sourceKey=source, occurrence=source + "/site=" + site,
                        hitOrdinal=1, actorLocalOrdinal=1, **common)
        response = dict(event="KEY_UPDATE_RESPONSE", seq=8, identityBound=True, **common)
        imported = dict(event="KEY_IMPORT_APPLIED", seq=10,
                        responseCommandMatched=True, **common)
        trace = [dict(event="ACTOR_REGISTERED", seq=1, actorKey=actor),
                 dict(event="MANAGER_BOUND", seq=2, actorKey=actor, resource=resource),
                 dict(event="SERVER_BOUND", seq=3, actorKey=actor), sasl,
                 dict(event="TARGET_CHECK", seq=5, caseId="HDFS-12", siteId=target,
                      targetActor=actor, resource=resource, managerObjectHash=19,
                      managerIdentity=1,
                      keyPresent=True, keyId=100),
                 dict(event="TARGET_CHECK", seq=6, caseId="HDFS-12", siteId=target,
                      targetActor=actor, resource=resource, managerObjectHash=19,
                      managerIdentity=1,
                      keyPresent=True, keyId=100),
                 response, producer, imported,
                 dict(event="TARGET_CHECK", seq=11, caseId="HDFS-12", siteId=target,
                      targetActor=actor, resource=resource, managerObjectHash=19,
                      managerIdentity=1,
                      keyPresent=True, keyId=101),
                 dict(event="TARGET_CHECK", seq=12, caseId="HDFS-12", siteId=target,
                      targetActor=actor, resource=resource, managerObjectHash=19,
                      managerIdentity=1,
                      keyPresent=True, keyId=101)]
        run = root / "healthy"
        run.mkdir()
        (run / "manifest.json").write_text(json.dumps(dict(
            test="TestEncryptedTransfer#testLongLivedClient[0]", returncode=0,
            elapsed_seconds=20, instrumentation_digest_sha256="overlay")))
        (run / "runtime_trace.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in trace))
        return run

    def mutate(self, run: Path, event: str, key: str, value) -> None:
        rows = [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()]
        next(row for row in rows if row["event"] == event)[key] = value
        (run / "runtime_trace.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows))

    def test_ordered_same_command_key_and_manager_pass(self):
        with TemporaryDirectory() as temporary:
            receipt = inspect_seed(self.fixture(Path(temporary)), "HDFS-12")
            self.assertEqual(receipt["issues"], [])
            self.assertEqual(len(receipt["rotated_producer_links"]), 1)

    def test_wrong_datanode_uuid_does_not_link(self):
        with TemporaryDirectory() as temporary:
            run = self.fixture(Path(temporary))
            self.mutate(run, "KEY_IMPORT_APPLIED", "rawDatanodeUuid", "OTHER-DN")
            receipt = inspect_seed(run, "HDFS-12")
            self.assertEqual(receipt["rotated_producer_links"], [])

    def test_wrong_imported_key_does_not_link(self):
        with TemporaryDirectory() as temporary:
            run = self.fixture(Path(temporary))
            self.mutate(run, "KEY_IMPORT_APPLIED", "rawKeyId", 102)
            receipt = inspect_seed(run, "HDFS-12")
            self.assertEqual(receipt["rotated_producer_links"], [])

    def test_wrong_target_manager_does_not_link(self):
        with TemporaryDirectory() as temporary:
            run = self.fixture(Path(temporary))
            rows = [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()]
            for row in rows:
                if row["event"] == "TARGET_CHECK":
                    row["managerIdentity"] = 999
            (run / "runtime_trace.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows))
            receipt = inspect_seed(run, "HDFS-12")
            self.assertEqual(receipt["rotated_producer_links"], [])

    def test_first_smoke_uses_stable_response_and_runtime_key_wildcard(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            run = self.fixture(output)
            run.rename(output / "healthy-a")
            seed = inspect_seed(output / "healthy-a", "HDFS-12")
            (output / "healthy_receipt.json").write_text(json.dumps(dict(
                case_id="HDFS-12", **{"pass": True},
                stable_producer_selectors=seed["rotated_producer_selectors"])))
            selected = prepare(output)
            self.assertEqual(selected["runtime_required_raw_key_id"], "*")
            fields = Path(selected["plan"]).read_text().strip().split("\t")
            self.assertEqual(fields[0], "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE")
            self.assertEqual(fields[5], "SocketTimeoutException")
            self.assertEqual(fields[6], "*")
            self.assertEqual(Path(selected["run"]).name, selected["sequence_id"])
            self.assertIn("if [ ! -f", Path(selected["script"]).read_text())


if __name__ == "__main__":
    unittest.main()
