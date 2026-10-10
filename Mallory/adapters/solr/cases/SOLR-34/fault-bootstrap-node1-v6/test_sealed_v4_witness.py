"""Read-only replay of the sealed v4 healthy trace; never starts Solr."""

import gzip
import hashlib
import json
import tarfile
import unittest
from pathlib import Path

import bootstrap_policy as p

ARCHIVE = Path("/users/ZhenyuLi/baseline/data/mallory/evidence_archives/"
               "SOLR-34-path-healthy-node1-v4.tar.gz")
ARCHIVE_SHA = "b53553289cfeec7c2a575e26e211f3c1c78c23dd49f11f13f118ffc0d4defc96"


class SealedHealthyWitnessTest(unittest.TestCase):
    def test_six_request_thread_doors_and_three_excluded_callbacks(self):
        self.assertTrue(ARCHIVE.is_file())
        self.assertEqual(ARCHIVE_SHA, hashlib.sha256(ARCHIVE.read_bytes()).hexdigest())
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            name = next(name for name in archive.getnames()
                        if name.endswith("/trials/r0000/events.jsonl.gz"))
            rows = [json.loads(line) for line in
                    gzip.decompress(archive.extractfile(name).read()).splitlines()]
        target_path = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
                       and row.get("node") == p.NODE and row.get("resource") == p.RESOURCE]
        selected = [row["door_ordinal"] for row in target_path
                    if p.operation_witness(rows, row)]
        self.assertEqual([5, 15, 16, 18, 19, 20], selected)
        self.assertEqual([17, 22, 23], [row["door_ordinal"] for row in target_path
                                        if not p.operation_witness(rows, row)])


if __name__ == "__main__":
    unittest.main()
