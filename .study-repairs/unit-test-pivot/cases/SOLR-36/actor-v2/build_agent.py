#!/usr/bin/env python3
"""Build isolated Solr 36/37 ZooKeeper actor-aware ASM agent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "independent"
sys.path.insert(0, str(PARENT))
from build import JAVA8, original_classpath  # noqa: E402


def main() -> None:
    source_dir = HERE / "src/research/solrsubshardv2"
    sources = [source_dir / "Agent.java", source_dir / "Probe.java"]
    classes = HERE / "agent-classes"
    classes.mkdir(parents=True, exist_ok=True)
    cp = original_classpath()
    result = subprocess.run(
        [str(JAVA8 / "javac"), "-source", "8", "-target", "8",
         "-cp", cp, "-d", str(classes), *(str(source) for source in sources)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    manifest = HERE / "agent.mf"
    manifest.write_text("Manifest-Version: 1.0\n"
                        "Premain-Class: research.solrsubshardv2.Agent\n\n")
    agent = HERE / "solrsubshard-actor-v2-agent.jar"
    subprocess.run([str(JAVA8 / "jar"), "cfm", str(agent), str(manifest),
                    "-C", str(classes), "research/solrsubshardv2"], check=True)
    receipt = {
        "agent_sha256": hashlib.sha256(agent.read_bytes()).hexdigest(),
        "source_sha256": {str(source.relative_to(HERE)):
                          hashlib.sha256(source.read_bytes()).hexdigest()
                          for source in sources},
        "parent_runner": str(PARENT / "run.py"),
        "classpath_contains_graphchecker": "graphchecker" in cp.lower(),
    }
    (HERE / "agent-build.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
