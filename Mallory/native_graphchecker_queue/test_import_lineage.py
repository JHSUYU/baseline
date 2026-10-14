"""Small archive fixtures for imported-trial provenance validation."""

import hashlib
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from .import_lineage import (_verify_local_manifest, verify_import_evidence,
                             verify_import_lineage)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    campaign = tmp_path / "current"
    source = tmp_path / "previous" / "trials" / "r0000"
    target = campaign / "trials" / "r0000"
    raw = tmp_path / "raw" / "r0000-attempt-a"
    raw.mkdir(parents=True)
    (raw / "stdout.log").write_bytes(b"original JUnit\n")
    _json(source / "result.json", {"case_id": "HBASE-14"})
    _json(source / "process.json", {"exit": 0})
    digest = hashlib.sha256()
    digest.update(b"stdout.log\0F" + bytes.fromhex(_sha(raw / "stdout.log")))
    local = {"campaign_root": str(source.parent.parent),
             "local_attempt_dir": str(raw), "file_count": 1,
             "total_bytes": (raw / "stdout.log").stat().st_size,
             "tree_sha256": digest.hexdigest(),
             "selected_sha256": {"stdout.log": _sha(raw / "stdout.log")}}
    _json(source / "local-artifacts.json", local)
    target.mkdir(parents=True)
    for name in ("result.json", "local-artifacts.json"):
        (target / name).write_bytes((source / name).read_bytes())
    _json(campaign / "checkpoint.json", {"terminal": True,
        "healthy": {"name": "r0000", "result": "trials/r0000/result.json"},
        "trials": []})
    _json(campaign / "summary.json", {"completed_fault_trials": 0})
    manifest = tmp_path / "raw-manifest.json"
    _json(manifest, {"source": str(raw), "rows": [
        {"kind": "dir", "path": raw.name},
        {"kind": "file", "path": raw.name + "/stdout.log",
         "size": (raw / "stdout.log").stat().st_size,
         "sha256": _sha(raw / "stdout.log")}]})
    uncompressed = tmp_path / "raw.tar"
    with tarfile.open(uncompressed, "w") as tar:
        tar.add(raw, arcname=raw.name)
    archive = tmp_path / "raw.tar.zst"
    with archive.open("wb") as output:
        subprocess.run(["zstd", "-q", "-c", str(uncompressed)],
                       stdout=output, check=True)
    receipt = tmp_path / "receipt.json"
    _json(receipt, {"status": "source_reclaimed_verified",
                    "source": str(raw), "manifest_sha256": _sha(manifest),
                    "archive_sha256": _sha(archive),
                    "result_sha256": _sha(source / "result.json")})
    binding = tmp_path / "lineage.json"
    _json(binding, {"schema_version": 1, "status": "sealed",
                    "campaign_root": str(campaign.resolve()),
                    "checkpoint_sha256": _sha(campaign / "checkpoint.json"),
                    "summary_sha256": _sha(campaign / "summary.json"),
                    "imports": [{"trial": "r0000", "predecessor_trial": str(source),
                                 "copied": {name: _sha(source / name) for name in
                                            ("result.json", "local-artifacts.json")},
                                 "omitted": {"process.json": _sha(source / "process.json")},
                                 "archive": str(archive), "archive_sha256": _sha(archive),
                                 "raw_manifest": str(manifest),
                                 "raw_manifest_sha256": _sha(manifest),
                                 "raw_receipt": str(receipt),
                                 "raw_receipt_sha256": _sha(receipt)}]})
    return campaign, binding


class ImportLineageTest(unittest.TestCase):
    def _evidence(self, tmp_path: Path, *, relocate: bool) -> tuple[Path, dict]:
        campaign, prior = _fixture(tmp_path)
        prior_sha = _sha(prior)
        source = campaign.parent / "previous/trials/r0000"
        verified = tmp_path / "verified.json"
        _json(verified, verify_import_lineage(campaign, prior, prior_sha))
        helper = tmp_path / "RegionPlanIdsMain.java"
        helper.write_text("class RegionPlanIdsMain {}\n")
        current = prior
        graph = {"schema_version": 1, "lineage_sha256": prior_sha,
                 "graph_receipts": {}}
        if relocate:
            old = json.loads(prior.read_text())
            old_archive = Path(old["imports"][0]["archive"])
            new_archive = tmp_path / "durable.tar.zst"
            new_archive.write_bytes(old_archive.read_bytes())
            updated = json.loads(prior.read_text())
            updated["imports"][0]["archive"] = str(new_archive)
            current = tmp_path / "lineage-v2.json"
            _json(current, updated)
            verified = tmp_path / "verified-v2.json"
            _json(verified, verify_import_lineage(campaign, current, _sha(current)))
            relocation = tmp_path / "relocation.json"
            _json(relocation, {
                "method": "byte_identical_combined_archive_relocation",
                "source": str(old_archive), "destination": str(new_archive),
                "sha256": _sha(new_archive)})
            graph.update(lineage_sha256=_sha(current),
                         prior_lineage_path=str(prior),
                         prior_lineage_sha256=prior_sha,
                         relocation_receipt_path=str(relocation),
                         relocation_receipt_sha256=_sha(relocation))
        graph_receipt = tmp_path / "r0000-graph.json"
        _json(graph_receipt, {"trial": "r0000", "status": "no_graph_unmatched",
                              "lineage_sha256": prior_sha,
                              "result_sha256": _sha(source / "result.json")})
        graph["graph_receipts"] = {
            "r0000": {"path": str(graph_receipt), "sha256": _sha(graph_receipt)}}
        graph_path = tmp_path / "graph-index.json"
        _json(graph_path, graph)
        descriptor = tmp_path / "descriptor.json"
        _json(descriptor, {"schema_version": 1, "case_id": "HBASE-14",
                           "native_root": str(campaign.resolve()),
                           "lineage_path": str(current),
                           "lineage_sha256": _sha(current),
                           "verified_path": str(verified),
                           "verified_sha256": _sha(verified),
                           "graph_path": str(graph_path),
                           "graph_sha256": _sha(graph_path),
                           "auxiliary_java_path": str(helper),
                           "auxiliary_java_sha256": _sha(helper),
                           "auxiliary_java_commit": "870be2202bb4e0da2ce9c4df9fa8c845fa83c61b"})
        return campaign, {"path": str(descriptor), "sha256": _sha(descriptor)}

    def test_sealed_imported_graph_receipt_is_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign, pin = self._evidence(Path(temp), relocate=False)
            self.assertEqual(verify_import_evidence(
                campaign, pin, "HBASE-14")["imported_trials"], ["r0000"])

    def test_byte_identical_archive_relocation_preserves_graph_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign, pin = self._evidence(Path(temp), relocate=True)
            receipt = verify_import_evidence(campaign, pin, "HBASE-14")
            self.assertEqual(receipt["imported_trials"], ["r0000"])
            descriptor = json.loads(Path(pin["path"]).read_text())
            graph = Path(descriptor["graph_path"])
            changed = json.loads(graph.read_text())
            changed["prior_lineage_sha256"] = "0" * 64
            _json(graph, changed)
            with self.assertRaisesRegex(ValueError, "graph receipt index"):
                verify_import_evidence(campaign, pin, "HBASE-14")

    def test_imported_trial_verifies_every_archive_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign, binding = _fixture(Path(temp))
            receipt = verify_import_lineage(campaign, binding, _sha(binding))
            self.assertEqual(receipt["imports"]["r0000"]["raw_archive"]["file_count"], 1)

    def test_imported_trial_rejects_changed_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign, binding = _fixture(Path(temp))
            (campaign / "trials/r0000/result.json").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "imported sidecar"):
                verify_import_lineage(campaign, binding, _sha(binding))

    def test_imported_trial_rejects_changed_tree_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign, _ = _fixture(Path(temp))
            local = json.loads((campaign / "trials/r0000/local-artifacts.json").read_text())
            raw = {"source": local["local_attempt_dir"], "rows": [
                {"kind": "file", "path": "r0000-attempt-a/stdout.log",
                 "size": 15, "sha256": "0" * 64}]}
            with self.assertRaisesRegex(ValueError, "archived raw tree"):
                _verify_local_manifest(local, raw)
