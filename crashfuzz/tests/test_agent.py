"""A Java 8 bytecode/trace smoke test; requires the packaged agent jar."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from adhoc_crashfuzz.graph import build_graph, read_events, target_closure
from adhoc_crashfuzz.model import TargetSpec


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent/target/adhoc-crashfuzz-agent-0.1.0.jar"
FIXTURE = ROOT / "tests/fixtures/TinyNode.java"


@unittest.skipUnless(AGENT.exists() and shutil.which("javac")
                     and shutil.which("java"), "build agent and install a JDK")
class AgentTests(unittest.TestCase):
    def test_agent_preserves_execution_and_observes_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            classes = root / "classes"
            classes.mkdir()
            subprocess.run(["javac", "-d", str(classes), str(FIXTURE)],
                           check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)

            def run(label, value, guard="", thrown="", entry="",
                    point_entries=""):
                trace = root / label
                trace.mkdir()
                config = root / (label + ".properties")
                config.write_text("\n".join([
                    "include.prefixes=fixture/", "node.id=fixture-node",
                    "trace.dir=" + str(trace),
                    "io.rules=java/io/FileOutputStream#write",
                    "trace.fields=true", "trace.branches=true",
                    "coverage.blocks=true",
                    "target.guard=" + guard, "target.throw=" + thrown,
                    "target.entry=" + entry,
                    "point.entries=" + point_entries,
                ]) + "\n")
                process = subprocess.run([
                    "java", "-javaagent:{}={}".format(AGENT, config),
                    "-cp", str(classes), "fixture.TinyNode",
                    str(root / (label + ".bin")), str(value),
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, timeout=30)
                return process, read_events(trace)

            healthy, healthy_events = run("discover-healthy", 0)
            repeated, repeated_events = run("discover-repeat", 0)
            fatal, fatal_events = run("discover-fatal", -2)
            self.assertEqual(0, healthy.returncode, healthy.stderr)
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertEqual(
                {e.site for e in healthy_events if e.kind == "BLOCK"},
                {e.site for e in repeated_events if e.kind == "BLOCK"})
            self.assertNotEqual(0, fatal.returncode)
            self.assertIn("target failure", fatal.stderr)
            self.assertEqual(2, sum(event.kind == "FAULT_POINT"
                                    for event in healthy_events))
            self.assertTrue(any(event.kind == "BLOCK"
                                for event in healthy_events))
            self.assertTrue(any(event.kind == "ASYNC_RECV"
                                for event in healthy_events))
            healthy_branches = {event.site: event.outcome
                                for event in healthy_events
                                if event.kind == "BRANCH"}
            changed = [event.site for event in fatal_events
                       if event.kind == "BRANCH"
                       and healthy_branches.get(event.site) != event.outcome]
            self.assertTrue(changed)
            guard = changed[-1]
            throw_sites = [event.site for event in fatal_events
                           if event.kind == "THROW"]
            self.assertTrue(throw_sites)
            thrown = throw_sites[-1]

            _, checked_healthy = run("checked-healthy", 0, guard, thrown)
            _, checked_fatal = run("checked-fatal", -2, guard, thrown)
            healthy_closure = target_closure(
                build_graph(checked_healthy), TargetSpec(guard))
            fatal_graph = build_graph(checked_fatal)
            fatal_closure = target_closure(fatal_graph, TargetSpec(guard))
            self.assertTrue(healthy_closure.reached)
            self.assertFalse(healthy_closure.fatal)
            self.assertTrue(fatal_closure.fatal)
            self.assertTrue(healthy_closure.block_features)
            self.assertTrue(any(edge.kind == "ASYNC"
                                for edge in fatal_graph.edges))
            self.assertTrue(any(edge.kind == "STATE_CANDIDATE"
                                for edge in fatal_closure.edges))

            entry = "fixture/TinyNode#main([Ljava/lang/String;)V"
            _, entry_healthy = run("entry-healthy", 0, thrown=thrown,
                                   entry=entry, point_entries=entry)
            _, entry_fatal = run("entry-fatal", -2, thrown=thrown,
                                 entry=entry)
            self.assertTrue(target_closure(
                build_graph(entry_healthy), TargetSpec(thrown)).reached)
            self.assertTrue(any(event.kind == "FAULT_POINT" and
                                event.site == entry + "#ENTRY"
                                for event in entry_healthy))
            self.assertFalse(target_closure(
                build_graph(entry_healthy), TargetSpec(thrown)).fatal)
            self.assertTrue(target_closure(
                build_graph(entry_fatal), TargetSpec(thrown)).fatal)

            # The worker is covered without creating a traced METHOD_ENTER
            # region when it is outside method.rules.
            global_trace = root / "global-only"
            global_trace.mkdir()
            global_config = root / "global-only.properties"
            global_config.write_text("\n".join([
                "include.prefixes=fixture/", "method.rules=fixture/TinyNode#main",
                "coverage.include.prefixes=fixture/", "coverage.blocks=true",
                "coverage.branches=true", "node.id=fixture-node",
                "trace.dir=" + str(global_trace), "",
            ]))
            global_run = subprocess.run([
                "java", "-javaagent:{}={}".format(AGENT, global_config),
                "-cp", str(classes), "fixture.TinyNode",
                str(root / "global-only.bin"), "0",
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(0, global_run.returncode, global_run.stderr)
            global_events = read_events(global_trace)
            self.assertTrue(any(e.kind == "GLOBAL_BLOCK"
                                for e in global_events))
            self.assertTrue(any(e.kind == "GLOBAL_BRANCH"
                                for e in global_events))
            self.assertTrue(any(e.kind == "BLOCK" for e in global_events))


if __name__ == "__main__":
    unittest.main()
