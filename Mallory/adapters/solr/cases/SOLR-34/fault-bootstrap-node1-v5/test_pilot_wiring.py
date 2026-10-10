"""Offline negative controls for the SOLR-34 v3 agent override regression."""

import tempfile
import unittest
from pathlib import Path

from run_pilot import ADAPTER, AGENT, SITES, validate_controller_env


OLD_AGENT = Path("/users/ZhenyuLi/baseline/Mallory/instrumentation/releases/"
                 "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                 "mallory-agent.jar")


class PilotWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trial = Path(self.tmp.name)
        self.properties = self.trial / "agent.properties"
        self.properties.write_text(
            f"site.file={SITES}\nauto.io.doors=false\n"
            "include=org.apache.solr.common.cloud.SolrZkClient\n")
        self.env = {
            "MALLORY_SOLR_AGENT_JAR": str(AGENT),
            "MALLORY_SOLR_ADAPTER_JAR": str(ADAPTER),
            "JAVA_TOOL_OPTIONS": f"-Dsolr.foo=true -javaagent:{AGENT}=config={self.properties}",
            "MALLORY_EVENT_FILE": str(self.trial / "events.jsonl"),
        }

    def test_pinned_path_aware_agent_and_typed_resource_door(self):
        proof = validate_controller_env(self.env)
        self.assertEqual("first_string_parameter", proof["typed_resource_argument"])
        self.assertEqual(str(SITES), proof["site_file"])

    def test_rejects_old_v38_agent_environment(self):
        self.env["MALLORY_SOLR_AGENT_JAR"] = str(OLD_AGENT)
        with self.assertRaisesRegex(ValueError, "controller agent path"):
            validate_controller_env(self.env)

    def test_rejects_old_v38_jvm_agent_even_with_new_env(self):
        self.env["JAVA_TOOL_OPTIONS"] = f"-javaagent:{OLD_AGENT}=config={self.properties}"
        with self.assertRaisesRegex(ValueError, "JVM javaagent path"):
            validate_controller_env(self.env)

    def test_rejects_wrong_resource_catalog_and_auto_door(self):
        self.properties.write_text(
            "site.file=/tmp/unrelated.json\nauto.io.doors=false\n"
            "include=org.apache.solr.common.cloud.SolrZkClient\n")
        with self.assertRaisesRegex(ValueError, "typed SolrZkClient path door"):
            validate_controller_env(self.env)
        self.properties.write_text(
            f"site.file={SITES}\nauto.io.doors=true\n"
            "include=org.apache.solr.common.cloud.SolrZkClient\n")
        with self.assertRaisesRegex(ValueError, "typed SolrZkClient path door"):
            validate_controller_env(self.env)


if __name__ == "__main__":
    unittest.main()
