import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).with_name("prepare_case.py")
SPEC = importlib.util.spec_from_file_location("prepare_case", MODULE)
prepare_case = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_case)


class PrepareCaseTest(unittest.TestCase):
    def test_exact_branch_throw_and_classpath_required(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            classes = root / "classes"
            test_classes = root / "tests"
            for base, name in ((classes, "example/Target.class"),
                               (test_classes, "example/OriginalTest.class")):
                path = base / name
                path.parent.mkdir(parents=True)
                path.write_bytes(b"class")
            row = {
                "case_id": "HBASE-TEST", "target_class": "example.Target",
                "target_method": "check(java.lang.String)", "target_line": "12",
                "target_exception": "java.io.IOException",
                "junit_class": "example.OriginalTest", "junit_method": "testOriginal",
            }
            template = {"analysis": {"process_dirs": [str(classes)],
                                      "classpath": [str(test_classes)]}}
            scope_input = prepare_case.target_input(row, template)
            self.assertEqual(scope_input["target"], {
                "class": "example.Target", "method": "check", "line": 12,
                "kind": "THROW", "exception": "java.io.IOException",
            })
            scope_dir = root / "scope"
            scope_dir.mkdir()
            branch, throw = "<example.Target: void check()>#u2", "<example.Target: void check()>#u4"
            digest = prepare_case.exact_cp_digest([str(test_classes)])
            analysis = {"targetSiteId": branch, "throwSiteId": throw,
                        "sootDependencyClasspathSha256": digest}
            identity = {"clazz": "example.Target", "method": "check",
                        "descriptor": "()V"}
            manifest = {"sootDependencyClasspathSha256": digest,
                        "targets": [{"siteId": branch, "kind": "BRANCH", "line": 11,
                                     **identity},
                                    {"siteId": throw, "kind": "THROW", "line": 12,
                                     **identity,
                                     "exceptionClass": "java.io.IOException"}]}
            (scope_dir / "analysis.json").write_text(json.dumps(analysis))
            (scope_dir / "weave_manifest.json").write_text(json.dumps(manifest))
            campaign = {"original_class_dirs": [str(classes)],
                        "test_classpath": [str(test_classes)], "case_id": "old"}
            config = prepare_case.campaign_config(row, scope_input, scope_dir, campaign)
            self.assertEqual(config["target"]["check_site_id"], branch)
            self.assertEqual(config["target"]["throw_site_id"], throw)
            self.assertEqual(config["junit"]["method"], "testOriginal")
            scoped_guard = prepare_case.target_input(row, template, check_line=11)
            self.assertEqual(scoped_guard["target"]["check_line"], 11)
            prepare_case.campaign_config(row, scoped_guard, scope_dir, campaign)
            scoped_guard["target"]["check_line"] = 10
            with self.assertRaisesRegex(ValueError, "selected guard line"):
                prepare_case.campaign_config(row, scoped_guard, scope_dir, campaign)
            manifest["targets"][1]["line"] = 13
            (scope_dir / "weave_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "inventory source line"):
                prepare_case.campaign_config(row, scope_input, scope_dir, campaign)
            manifest["targets"][1]["line"] = 12
            manifest["targets"][0]["clazz"] = "example.WrongTarget"
            (scope_dir / "weave_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "inventory class/method"):
                prepare_case.campaign_config(row, scope_input, scope_dir, campaign)
            manifest["targets"][0]["clazz"] = "example.Target"
            manifest["targets"][0]["kind"] = "THROW"
            (scope_dir / "weave_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "controlling branch"):
                prepare_case.campaign_config(row, scope_input, scope_dir, campaign)


if __name__ == "__main__":
    unittest.main()
