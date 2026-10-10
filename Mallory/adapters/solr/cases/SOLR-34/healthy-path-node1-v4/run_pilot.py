#!/usr/bin/env python3
"""Run the selected Solr JUnit with the pinned path-aware agent, without v38 overrides."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOLR_ADAPTER = HERE.parents[2]
ROOT = HERE.parents[5]
sys.path.insert(0, str(SOLR_ADAPTER))
import solr_junit_runner_v14 as runner  # noqa: E402

AGENT_SHA = "b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4"
AGENT = ROOT / "Mallory/instrumentation/releases" / AGENT_SHA / "mallory-agent.jar"
AGENT_MANIFEST = AGENT.parent / "manifest.json"
ADAPTER = SOLR_ADAPTER / "target/mallory-solr-adapter-v38.jar"
INVENTORY = SOLR_ADAPTER / "releases/v20/inventory.json"
SITES = HERE / "sites.json"
DOOR_METHOD = "lambda$getData$6"
DOOR_EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"
PATH_FEATURE = "SolrZkClient.lambda$getData$6 first String path in DOOR_OBSERVED"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_controller_env(env: dict[str, str], *, require_trial: bool = True) -> dict:
    """Fail before javac/Java if the controller and pilot disagree about the agent."""
    manifest = json.loads(AGENT_MANIFEST.read_text(encoding="utf-8"))
    if (not AGENT.is_file() or sha(AGENT) != AGENT_SHA
            or manifest.get("agent_sha256") != AGENT_SHA
            or PATH_FEATURE not in manifest.get("features", [])):
        raise ValueError("path-aware agent release or feature is not pinned")
    configured = env.get("MALLORY_SOLR_AGENT_JAR")
    if configured is None or Path(configured).resolve() != AGENT.resolve():
        raise ValueError("controller agent path differs from pinned path-aware agent")
    if env.get("MALLORY_SOLR_ADAPTER_JAR") != str(ADAPTER):
        raise ValueError("controller adapter path differs from pinned adapter")
    options = [part for part in shlex.split(env.get("JAVA_TOOL_OPTIONS", ""))
               if part.startswith("-javaagent:")]
    if len(options) != 1 or "=config=" not in options[0]:
        raise ValueError("controller must provide exactly one configured javaagent")
    agent_path, properties_path = options[0][len("-javaagent:"):].split("=config=", 1)
    if Path(agent_path).resolve() != AGENT.resolve():
        raise ValueError("JVM javaagent path differs from pinned path-aware agent")
    properties = Path(properties_path)
    if not properties.is_file():
        raise ValueError("controller agent.properties is absent")
    rows = dict(line.split("=", 1) for line in properties.read_text().splitlines()
                if line and "=" in line)
    if (rows.get("site.file") != str(SITES)
            or rows.get("auto.io.doors") != "false"
            or "org.apache.solr.common.cloud.SolrZkClient" not in
            rows.get("include", "").split(",")):
        raise ValueError("controller did not configure the typed SolrZkClient path door")
    doors = json.loads(SITES.read_text(encoding="utf-8")).get("doors", [])
    if (len(doors) != 1 or doors[0].get("method") != DOOR_METHOD
            or doors[0].get("exception_class") != DOOR_EXCEPTION
            or doors[0].get("line") != 349):
        raise ValueError("typed getData path door changed")
    if require_trial and (not env.get("MALLORY_EVENT_FILE") or
                          Path(env["MALLORY_EVENT_FILE"]).parent != properties.parent):
        raise ValueError("controller event file is outside this trial")
    return {"agent_sha256": AGENT_SHA, "agent_path": str(AGENT),
            "site_file": str(SITES), "typed_resource_argument": "first_string_parameter"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", choices=("SOLR-34",))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true", required=True)
    args = parser.parse_args()
    proof = validate_controller_env(os.environ)
    runner.AGENT = AGENT
    runner.ADAPTER = ADAPTER
    runner.INVENTORY = INVENTORY
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign, False)
    if result.get("agent_sha256") != AGENT_SHA:
        raise ValueError("JUnit runner used a different agent")
    result["path_agent_preflight"] = proof
    (args.output / "pilot-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
