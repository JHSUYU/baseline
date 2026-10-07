#!/usr/bin/env python3
"""Build an isolated agent with original parent-forward add/delete HTTP hooks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build import JAVA8, original_classpath  # noqa: E402


def main() -> None:
    sources = [HERE / 'src/research/solrsubshard/Agent.java',
               HERE / 'src/research/solrsubshard/Probe.java']
    classes = HERE / 'agent-classes'
    classes.mkdir(exist_ok=True)
    cp = original_classpath()
    result = subprocess.run(
        [str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
         '-cp', cp, '-d', str(classes), *(str(source) for source in sources)],
        capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solrsubshard.Agent\n\n')
    agent = HERE / 'solrsubshard-rpc-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), 'research/solrsubshard'], check=True)
    report = {
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'source_sha256': {str(path.relative_to(HERE)):
                          hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
        'hook': ('SolrCmdDistributor.submit L309 Http2SolrClient.request '
                 'for parent-forward add and delete-by-id'),
        'identity_version': 'ROLE_VERIFIED_NONLAZY_V2',
        'leader_binding': ('actual Req.cmd request core, CloudDescriptor leader, '
                           'unique active parent leader from non-lazy in-memory '
                           'ClusterState.CollectionRef, raw sender and node match'),
    }
    (HERE / 'agent-build.json').write_text(json.dumps(report, indent=2,
                                                      sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
