"""The source-built original engine must retain truthful vendor provenance."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.instrumentation.graphchecker_port import native_original_weave


class OriginalVendorProvenanceTest(unittest.TestCase):
    def test_adaptation_flag_matches_upstream_and_copied_hashes(self):
        provenance = native_original_weave.verified_vendor()
        row = next(source for source in provenance["sources"]
                   if source["path"].endswith("/ReturnOnlyFormals.java"))
        self.assertTrue(row["changed"])
        self.assertNotEqual(row["upstreamSha256"], row["copiedSha256"])

        with tempfile.TemporaryDirectory() as temporary:
            engine = Path(temporary)
            source_engine = native_original_weave.ENGINE
            shutil.copytree(source_engine / "vendor" / "src" / "main" / "java",
                            engine / "vendor" / "src" / "main" / "java")
            resources = source_engine / "src" / "main" / "resources"
            if resources.exists():
                shutil.copytree(resources, engine / "src" / "main" / "resources")
            altered = json.loads((source_engine / "UPSTREAM_SOURCES.json").read_text())
            altered_row = next(source for source in altered["sources"]
                               if source["path"].endswith("/ReturnOnlyFormals.java"))
            altered_row["changed"] = False
            (engine / "UPSTREAM_SOURCES.json").write_text(json.dumps(altered))
            with patch.object(native_original_weave, "ENGINE", engine):
                with self.assertRaisesRegex(ValueError, "adaptation flag differs"):
                    native_original_weave.verified_vendor()


if __name__ == "__main__":
    unittest.main()
