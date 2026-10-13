import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.dispatch.graphchecker_port.lane import (
    classfile_major, prepare_workspace, run_lane, verify_input_classfiles,
    verify_inputs, verify_java8,
)
from Mallory.dispatch.graphchecker_port.launcher import selected_for_wave
from Mallory.dispatch.graphchecker_port.plan import sha256


def source_digest(relative: str, content: bytes) -> str:
    file_hash = hashlib.sha256(content).digest()
    return hashlib.sha256(relative.encode() + b"\0F" + file_hash + b"\0").hexdigest()


class LauncherTest(unittest.TestCase):
    def make_fixture(self, temporary: Path):
        release = temporary / "release"
        source = temporary / "source"
        state = temporary / "state"
        release.mkdir()
        source.mkdir()
        state.mkdir()
        (source / "Original.java").write_bytes(b"original source")
        (source / "Original.java").chmod(0o444)
        config = {"case_id": "HDFS-01", "cwd": str(source)}
        (release / "HDFS-01.json").write_text(json.dumps(config), encoding="utf-8")
        files = {"HDFS-01.json": sha256(release / "HDFS-01.json")}
        (release / "HDFS-01.json").chmod(0o444)
        release.chmod(0o555)
        source.chmod(0o555)
        doc = {"schema_version": 1, "release_root": str(release),
               "release_files": files, "state_root": str(state),
               "sources": {"hdfs": {"root": str(source),
                                    "paths": ["Original.java"],
                                    "digest": source_digest("Original.java", b"original source")}},
               "assignments": {"hdfs": "node0", "hbase": "node1",
                               "solr": "node2", "zookeeper": "node0"},
               "configs": {"HDFS-01": "HDFS-01.json"},
               "min_disk_free_bytes": 0, "min_shm_free_bytes": 0}
        return doc

    def test_verified_fixture_and_resume_selection(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            doc = self.make_fixture(Path(directory))
            receipt = verify_inputs(doc, "node0", "hdfs", validate_core=False,
                                    verify_runtime_files=False)
            self.assertEqual(1, receipt["release"]["files"])
            self.assertEqual(["HDFS-01"], selected_for_wave(doc, 0, 1)[0]["case_ids"])
            state = Path(doc["state_root"]) / "HDFS-01"
            state.mkdir()
            config_hash = sha256(Path(doc["release_root"]) / "HDFS-01.json")
            (state / "checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-01",
                "config_sha256": config_hash, "status": "running",
                "terminal": False}), encoding="utf-8")
            self.assertEqual(["HDFS-01"], selected_for_wave(doc, 0, 1)[0]["case_ids"])
            (state / "checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-01",
                "config_sha256": config_hash, "status": "complete_queue",
                "terminal": True}), encoding="utf-8")
            (state / "summary.json").write_text(json.dumps({
                "case_id": "HDFS-01", "config_sha256": config_hash,
                "status": "complete_queue", "terminal": True}), encoding="utf-8")
            self.assertEqual([], selected_for_wave(doc, 0, 1))

    def test_modified_release_refused_and_lane_writes_durable_receipt(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory, \
                tempfile.TemporaryDirectory() as durable:
            doc = self.make_fixture(Path(directory))
            doc["state_root"] = durable
            with patch("Mallory.dispatch.graphchecker_port.lane.subprocess.run") as process:
                process.return_value.returncode = 0
                result = run_lane(doc, "node0", "hdfs", ["HDFS-01"], 1,
                                  validate_core=False, verify_runtime_files=False)
            self.assertEqual(0, result["outcomes"][0]["returncode"])
            case_dir = Path(doc["state_root"]) / "HDFS-01"
            self.assertTrue((case_dir / "dispatch.json").is_file())
            config_hash = sha256(Path(doc["release_root"]) / "HDFS-01.json")
            (case_dir / "checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-01",
                "config_sha256": config_hash, "status": "running",
                "terminal": False}), encoding="utf-8")
            with patch("Mallory.dispatch.graphchecker_port.lane.subprocess.run") as process:
                process.return_value.returncode = 0
                run_lane(doc, "node0", "hdfs", ["HDFS-01"], 1,
                         validate_core=False, verify_runtime_files=False)
            dispatch = json.loads((case_dir / "dispatch.json").read_text())
            self.assertEqual(2, len(dispatch["attempts"]))
            path = Path(doc["release_root"]) / "HDFS-01.json"
            path.chmod(0o644)
            path.write_text('{"case_id":"HDFS-01","cwd":"/tmp"}')
            path.chmod(0o444)
            with self.assertRaisesRegex(ValueError, "release hash mismatch"):
                verify_inputs(doc, "node0", "hdfs", validate_core=False,
                              verify_runtime_files=False)

    def test_unpinned_input_path_refused(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            doc = self.make_fixture(Path(directory))
            release = Path(doc["release_root"])
            release.chmod(0o755)
            config = release / "HDFS-01.json"
            config.chmod(0o644)
            config.write_text(json.dumps({"case_id": "HDFS-01", "cwd": "/tmp"}),
                              encoding="utf-8")
            config.chmod(0o444)
            doc["release_files"]["HDFS-01.json"] = sha256(config)
            release.chmod(0o555)
            with self.assertRaisesRegex(ValueError, "unpinned input path"):
                verify_inputs(doc, "node0", "hdfs", validate_core=False,
                              verify_runtime_files=False)

    def test_writable_case_cwd_is_seeded_from_pinned_fixture(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            doc = self.make_fixture(Path(directory))
            release = Path(doc["release_root"])
            release.chmod(0o755)
            fixture = release / "fixture"
            fixture.mkdir()
            (fixture / "input.txt").write_text("initial data", encoding="utf-8")
            (fixture / "input.txt").chmod(0o444)
            fixture.chmod(0o555)
            workspace_parent = Path("/dev/shm/mallory-gc/workspaces") / Path(directory).name
            workspace_parent.mkdir(parents=True, exist_ok=True)
            cwd = workspace_parent / "HDFS-01"
            config_path = release / "HDFS-01.json"
            config_path.chmod(0o644)
            raw = {"case_id": "HDFS-01", "cwd": str(cwd),
                   "cwd_template": str(fixture)}
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            config_path.chmod(0o444)
            release.chmod(0o555)
            doc["release_files"] = {"HDFS-01.json": sha256(config_path),
                                    "fixture/input.txt": sha256(fixture / "input.txt")}
            try:
                verify_inputs(doc, "node0", "hdfs", validate_core=False,
                              verify_runtime_files=False)
                prepare_workspace(raw, config_path, "HDFS-01")
                self.assertEqual("initial data", (cwd / "input.txt").read_text())
                self.assertTrue(os.access(cwd, os.W_OK))
                prepare_workspace(raw, config_path, "HDFS-01")
                (cwd / ".mallory-workspace.json").write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "receipt mismatch"):
                    prepare_workspace(raw, config_path, "HDFS-01")
            finally:
                shutil.rmtree(workspace_parent)

    def test_remote_host_makes_its_own_checkpoint_decision(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            doc = self.make_fixture(Path(directory))
            doc["configs"]["HBASE-01"] = "HBASE-01.json"
            doc["configs"]["HBASE-02"] = "HBASE-02.json"
            # node0's view must not decide whether a node1 case is complete.
            remote_lane = [row for row in selected_for_wave(doc, 0, 1)
                           if row["host"] == "node1"][0]
            self.assertEqual(["HBASE-01", "HBASE-02"], remote_lane["case_ids"])
            self.assertEqual(1, remote_lane["max_run_cases"])

    def test_cli_dry_run_with_local_snapshot_does_not_launch(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            doc = self.make_fixture(Path(directory))
            release = Path(doc["release_root"])
            release.chmod(0o755)
            for relative in ("Mallory/core/graphchecker_fuzzer.py",
                             "Mallory/core/graphchecker_campaign.py",
                             "Mallory/dispatch/graphchecker_port/lane.py"):
                path = release / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# pinned fixture\n", encoding="utf-8")
                path.chmod(0o444)
                doc["release_files"][relative] = sha256(path)
            for path in release.rglob("*"):
                if path.is_dir():
                    path.chmod(0o555)
            release.chmod(0o555)
            deployment = Path(directory) / "deployment.json"
            deployment.write_text(json.dumps(doc), encoding="utf-8")
            output = subprocess.run([sys.executable, "-m",
                "Mallory.dispatch.graphchecker_port.launcher", "--deployment",
                str(deployment)], cwd=Path(__file__).parents[3],
                text=True, capture_output=True, check=True)
            plan = json.loads(output.stdout)
            self.assertEqual("dry_run", plan["mode"])
            self.assertEqual(3, plan["max_concurrent_jobs"])
            self.assertEqual("HDFS-01", plan["lanes"][0]["case_ids"][0])

    def test_configured_java_version_and_selected_class_major(self):
        verify_java8.cache_clear()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "java"
            executable.write_bytes(b"java fixture")
            with patch("Mallory.dispatch.graphchecker_port.lane.shutil.which",
                       return_value=str(executable)), \
                    patch("Mallory.dispatch.graphchecker_port.lane.subprocess.run") as process:
                process.return_value.returncode = 0
                process.return_value.stdout = ""
                process.return_value.stderr = 'openjdk version "11.0.1"\n'
                with self.assertRaisesRegex(ValueError, "must be Java 8"):
                    verify_java8("java")
                process.return_value.stderr = 'openjdk version "1.8.0_492"\n'
                self.assertEqual(str(executable), verify_java8("java")["java_path"])
            classes = root / "classes"
            (classes / "org/example").mkdir(parents=True)
            original = classes / "org/example/Target.class"
            junit = classes / "org/example/Test.class"
            original.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")
            junit.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"regions": [{"clazz": "org.example.Target"}]}),
                                encoding="utf-8")
            config = {"weave_manifest": manifest, "original_class_dirs": [classes],
                      "test_classpath": [], "junit": {"class": "org.example.Test"}}
            self.assertEqual(52, verify_input_classfiles(config)["junit_class_major"])
            self.assertEqual(52, classfile_major(original.read_bytes()))
            original.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x37")
            with self.assertRaisesRegex(ValueError, "requires Java >8"):
                verify_input_classfiles(config)


if __name__ == "__main__":
    unittest.main()
