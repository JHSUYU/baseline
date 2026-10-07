#!/usr/bin/env python3
"""Collect two clean original ShardSplitTest runs with the V2 agent."""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "independent"
sys.path.insert(0, str(PARENT))
from run import run  # noqa: E402
from build import SOURCE, SOLR_DIST  # noqa: E402

EXPECTED_REVISION = 'e27f44e3d78dfcec230c97e0a1240e3751daeff9'
SOURCE_FILES = (
    'solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java',
    'solr/core/src/java/org/apache/solr/update/processor/DistributedZkUpdateProcessor.java',
    'solr/core/src/java/org/apache/solr/cloud/ZkController.java',
    'solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java',
    'solr/solrj/src/java/org/apache/solr/common/cloud/SolrZooKeeper.java',
)


@lru_cache(maxsize=1)
def source_provenance() -> dict:
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                       text=True).strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f'unexpected original Solr revision {revision}')
    dirty = subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain',
                                     '--untracked-files=no'], text=True).strip()
    if dirty:
        raise RuntimeError('original Solr tracked source is dirty')
    paths = [SOURCE / name for name in SOURCE_FILES]
    jar = SOLR_DIST / 'dist/solr-core-8.11.4.jar'
    return {'revision': revision,
            'source_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for name, path in zip(SOURCE_FILES, paths)},
            'original_core_jar_sha256': hashlib.sha256(jar.read_bytes()).hexdigest()}


def main() -> None:
    agent = HERE / "solrsubshard-actor-v2-agent.jar"
    if not agent.is_file():
        raise SystemExit("build V2 agent first")
    provenance = source_provenance()
    receipt = HERE / 'source-provenance.json'
    if receipt.is_file() and json.loads(receipt.read_text()) != provenance:
        raise SystemExit('original source or JAR changed since V2 preparation')
    receipt.write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n')
    for number in (1, 2):
        out = HERE / f"healthy-{number:02d}"
        if (out / "run.json").is_file():
            metadata = json.loads((out / "run.json").read_text())
            if metadata["exit_code"] != 0:
                raise SystemExit(f"existing unhealthy seed: {out}")
            if metadata['agent_sha256'] != hashlib.sha256(agent.read_bytes()).hexdigest():
                raise SystemExit(f'existing seed used different V2 agent: {out}')
            if metadata['original_source_revision'] != provenance['revision']:
                raise SystemExit(f'existing seed used different original source: {out}')
            continue
        if run(out, agent_path=agent) != 0:
            raise SystemExit(f"healthy calibration failed: {out}")


if __name__ == "__main__":
    main()
