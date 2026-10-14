"""The optional helper cache keeps pinned sources writable only by default."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_feedback import feedback, region_state_graph
from Mallory.native_graphchecker_feedback.build_cache import ENV, component_root


class FeedbackBuildCacheTest(unittest.TestCase):
    def _run_helpers(self, root: Path, *, cache: Path | None) -> tuple[Path, Path]:
        source = root / "pinned-source"
        source.mkdir()
        bridge = source / "NativeFeedbackMain.java"
        plan_helper = source / "RegionPlanIdsMain.java"
        bridge.write_text("class NativeFeedbackMain {}", encoding="utf-8")
        plan_helper.write_text("class RegionPlanIdsMain {}", encoding="utf-8")
        engine = root / "pinned-engine.jar"
        engine.write_bytes(b"pinned engine")
        dependencies = root / "dependencies.txt"
        dependencies.write_text("pinned dependency", encoding="utf-8")
        plan = root / "original-plan.json"
        plan.write_text("{}", encoding="utf-8")
        environment = {ENV: str(cache)} if cache is not None else {ENV: ""}
        source.chmod(0o555 if cache is not None else 0o755)
        try:
            with (patch.dict(os.environ, environment, clear=False),
                  patch.object(feedback, "HERE", source),
                  patch.object(feedback, "_classpath", return_value="pinned"),
                  patch.object(region_state_graph, "PLAN_ID_SOURCE", plan_helper),
                  patch.object(region_state_graph, "DEPENDENCIES", dependencies),
                  patch.object(feedback.subprocess, "run") as run):
                run.return_value.stdout = "joined"
                bridge_classes = feedback.build(engine_jar=engine)
                self.assertEqual("joined", region_state_graph._plan_helper_output(
                    plan, engine))
                self.assertEqual(3, run.call_count)
                self.assertEqual(["javac", "javac", "java"],
                                 [call.args[0][0] for call in run.call_args_list])
        finally:
            source.chmod(0o755)
        return source, bridge_classes

    def test_read_only_source_uses_task_local_cache_for_both_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "writable-cache"
            source, bridge_classes = self._run_helpers(root, cache=cache)
            self.assertEqual(cache / "native-feedback", bridge_classes.parent)
            self.assertTrue(list((cache / "native-feedback").glob(".build-*.lock")))
            self.assertTrue(list((cache / "region-plan-ids").glob(
                "region-plan-ids-*/.build.lock")))
            self.assertFalse((source / "target").exists())

    def test_unset_override_retains_original_in_tree_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, bridge_classes = self._run_helpers(root, cache=None)
            self.assertEqual(source / "target", bridge_classes.parent)
            self.assertTrue(list((source / "target").glob(".build-*.lock")))
            self.assertTrue(list((source / "target").glob(
                "region-plan-ids-*/.build.lock")))

    def test_relative_override_is_rejected(self) -> None:
        with patch.dict(os.environ, {ENV: "relative-cache"}):
            with self.assertRaisesRegex(ValueError, "absolute path"):
                component_root("native-feedback", Path("original-target"))


if __name__ == "__main__":
    unittest.main()
