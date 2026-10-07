#!/usr/bin/env python3
"""Overlay only the original Solr alias-manager and ZooKeeper-client classes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

from build import ASM, CLASSES, DIST, HERE, JAVA

SOLRJ = DIST / 'dist/solr-solrj-8.11.4.jar'
NAMES = ('org/apache/solr/common/cloud/ZkStateReader$AliasesManager',
         'org/apache/solr/common/cloud/SolrZkClient')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    hashes = {}
    with zipfile.ZipFile(SOLRJ) as jar:
        for name in NAMES:
            original = jar.read(name + '.class')
            source = HERE / 'input' / (name + '.class')
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(original)
            run = subprocess.run([str(JAVA / 'java'), '-cp', str(CLASSES) + ':' + str(ASM),
                                  'research.solr18.PatchSolr18', str(source), name,
                                  str(CLASSES)], capture_output=True, text=True, check=True)
            patched = CLASSES / (name + '.class')
            hashes[name] = {'original_sha256': sha(original),
                            'patched_sha256': sha(patched.read_bytes()),
                            'patch_counts': run.stdout.strip()}
    manifest = {'original_solrj_jar_sha256': sha(SOLRJ.read_bytes()),
                'classes': hashes,
                'probe_class_sha256': sha((CLASSES / 'research/solr18/Solr18Probe.class').read_bytes())}
    output = HERE / 'instrumentation.json'
    temp = output.with_suffix('.json.tmp')
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    os.replace(temp, output)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()
