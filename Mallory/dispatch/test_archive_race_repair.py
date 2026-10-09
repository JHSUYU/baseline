from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from .archive import ensure
from .repair_archive_race import repair
from .verify_sources import sha256_file
from .worker import atomic_json


class ArchiveRaceRepairTest(unittest.TestCase):
    def test_preserves_augmented_result_and_rebinds_verified_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "cases/HBASE-07"
            case.mkdir(parents=True)
            result_path = case / "result.json"
            original = {"case_id": "HBASE-07", "status": "budget_exhausted",
                        "trials": [{"trial_id": "r0001"}]}
            atomic_json(result_path, original)
            original_bytes = result_path.read_bytes()
            first = ensure(root, "campaign", "HBASE-07", reserve_bytes=1)
            augmented = dict(original)
            augmented["evidence_archive"] = {"sha256": first["archive_sha256"]}
            augmented["dispatch_provenance"] = {"attempt_id": "attempt"}
            atomic_json(result_path, augmented)
            before_sha = sha256_file(result_path)
            archive = root / first["archive_relative"]
            manifest_path = root / first["manifest_relative"]
            (case / "additional-evidence.txt").write_text("second pack", encoding="utf-8")
            with tarfile.open(archive, "w:gz") as packed:
                with tempfile.NamedTemporaryFile() as source:
                    source.write(original_bytes)
                    source.flush()
                    packed.add(source.name, arcname="result.json")
                packed.add(case / "additional-evidence.txt", arcname="additional-evidence.txt")
            replacement_sha = sha256_file(archive)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update({
                "archive_sha256": replacement_sha,
                "archive_bytes": archive.stat().st_size,
                "source_result_sha256": hashlib.sha256(original_bytes).hexdigest(),
                "members": ["result.json", "additional-evidence.txt"],
            })
            atomic_json(manifest_path, manifest)
            receipt = repair(root, "HBASE-07", before_sha, replacement_sha)
            self.assertTrue(receipt["scientific_fields_identical"])
            self.assertEqual(before_sha, sha256_file(
                root / receipt["preserved_result_path"]))
            self.assertEqual(replacement_sha, json.loads(result_path.read_text())[
                "evidence_archive"]["sha256"])
            self.assertEqual(replacement_sha, ensure(
                root, "campaign", "HBASE-07", reserve_bytes=1)["archive_sha256"])

    def test_rejects_changed_scientific_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "cases/HBASE-07"
            case.mkdir(parents=True)
            result_path = case / "result.json"
            atomic_json(result_path, {"case_id": "HBASE-07", "status": "budget_exhausted"})
            first = ensure(root, "campaign", "HBASE-07", reserve_bytes=1)
            current = json.loads(result_path.read_text())
            current["scientific_change"] = True
            current["evidence_archive"] = {"sha256": "lost-original-archive"}
            atomic_json(result_path, current)
            with self.assertRaisesRegex(RuntimeError, "different evidence"):
                ensure(root, "campaign", "HBASE-07", reserve_bytes=1)
            with self.assertRaisesRegex(RuntimeError, "scientifically"):
                repair(root, "HBASE-07", sha256_file(result_path),
                       first["archive_sha256"])


if __name__ == "__main__":
    unittest.main()
