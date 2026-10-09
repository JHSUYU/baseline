#!/usr/bin/env python3
"""Check identity matching before starting any Solr cluster."""

from pathlib import Path
import subprocess

from build import HERE, JAVA8, original_classpath

output = HERE / 'smoke-actor.jsonl'
command = [str(JAVA8 / 'java'),
           '-Dsolrcoord.trace.file=' + str(output),
           '-cp', str(HERE / 'agent-classes') + ':' + original_classpath(),
           'research.solrcoordv2.ActorFixture']
subprocess.run(command, check=True)
