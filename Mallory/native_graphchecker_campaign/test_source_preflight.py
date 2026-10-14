"""Frozen campaign source admission, before an expensive cluster JUnit."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from Mallory.native_graphchecker_campaign.source_preflight import feedback_bridge


class FeedbackSourcePreflightTest(unittest.TestCase):
    def test_rejects_incomplete_archive_before_junit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine.jar"
            with zipfile.ZipFile(engine, "w"):
                pass
            with self.assertRaisesRegex(ValueError, "NativeFeedbackMain.java"):
                feedback_bridge(root, engine)
            source = (root / "Mallory/native_graphchecker_feedback/"
                      "NativeFeedbackMain.java")
            source.parent.mkdir(parents=True)
            source.write_text("class NativeFeedbackMain {}\n")
            with self.assertRaisesRegex(ValueError, "native-original-dependencies.txt"):
                feedback_bridge(root, engine)

    def test_compiles_complete_frozen_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine.jar"
            dependency = root / "dependency.jar"
            for jar in (engine, dependency):
                with zipfile.ZipFile(jar, "w"):
                    pass
            source = (root / "Mallory/native_graphchecker_feedback/"
                      "NativeFeedbackMain.java")
            source.parent.mkdir(parents=True)
            source.write_text(
                "package edu.uva.liftlab.mallory.nativefeedback; "
                "public class NativeFeedbackMain {}\n")
            deps = (root / "Mallory/static_scope_port/original_engine/target/"
                    "native-original-dependencies.txt")
            deps.parent.mkdir(parents=True)
            deps.write_text(str(dependency) + "\n")
            receipt = feedback_bridge(root, engine)
            self.assertEqual(64, len(receipt["compiled_class_sha256"]))
            self.assertEqual(64, len(receipt["source_sha256"]))
            dependency.unlink()
            with self.assertRaisesRegex(ValueError, "classpath is incomplete"):
                feedback_bridge(root, engine)


if __name__ == "__main__":
    unittest.main()
