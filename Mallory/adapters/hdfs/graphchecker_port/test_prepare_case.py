"""Checks that inventory guards, not all method branches, anchor a campaign."""

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).with_name("prepare_case.py")
SPEC = importlib.util.spec_from_file_location("hdfs_prepare_case", MODULE)
prepare_case = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_case)


class PrepareCaseTest(unittest.TestCase):
    def test_keeps_two_inventory_guards_and_ignores_other_branches(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            classes = root / "classes"
            classes.mkdir()
            jars = [root / name for name in ("weaver.jar", "runtime.jar", "graph.jar")]
            for jar in jars:
                jar.write_bytes(b"fixture")
            java = root / "java"
            java.write_text("fixture")
            cp = root / "cp.txt"
            cp.write_text(str(classes))
            deps = root / "weaver-deps.txt"
            deps.write_text(str(jars[0]))
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"cases": [{
                "case_id": "HDFS-X", "system": "hdfs",
                "eligibility": {"may_attempt_seed": True},
                "workload": {"selected_selector": "example.Test#testOriginal"},
                "target": {"function": "example.Target.check()",
                           "source_line": 20,
                           "target_exception": "java.io.IOException",
                           "runtime_mapping": {"check_sites": [
                               "example.Target#check()V@11:branch:1",
                               "example.Target#check()V@12:branch:2"]}}
            }]}))
            scope = root / "scope"
            scope.mkdir()
            ids = {line: f"<example.Target: void check()>#u{line}"
                   for line in (11, 12, 20, 99)}
            targets = [{"siteId": ids[line], "kind": "BRANCH",
                        "clazz": "example.Target", "method": "check", "line": line}
                       for line in (11, 12, 99)]
            targets.append({"siteId": ids[20], "kind": "THROW",
                            "clazz": "example.Target", "method": "check",
                            "line": 20, "exceptionClass": "java.io.IOException"})
            digest = prepare_case.hashlib.sha256(str(classes).encode()).hexdigest()
            (scope / "weave_manifest.json").write_text(json.dumps({
                "targets": targets, "sootDependencyClasspathSha256": digest}))
            (scope / "analysis.json").write_text(json.dumps({
                "targetSiteId": ids[11]}))
            args = argparse.Namespace(
                inventory=inventory, case_id="HDFS-X", scope_output=scope,
                classpath_file=cp, weaver_deps_file=deps,
                weaver_jar=jars[0], runtime_jar=jars[1], graph_jar=jars[2],
                test_classes=classes, hadoop_root=root, java=java,
                out=root / "case.json", fault_trials=64, seconds=1800,
                max_faults_per_trial=4, timeout_seconds=600)
            prepare_case.campaign_config(args)
            config = json.loads(args.out.read_text())
            self.assertEqual([ids[11], ids[12]],
                             config["target"]["all_check_site_ids"])


if __name__ == "__main__":
    unittest.main()
