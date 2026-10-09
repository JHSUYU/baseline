#!/usr/bin/env python3
"""Transform original Solr class bytes offline and reject wrong actor/destination."""

from pathlib import Path
import subprocess
import zipfile

from build_v2 import DIST, HERE, JAVA8, asm_jars, classpath


def main() -> None:
    original = HERE / 'original-class-bytes'
    original.mkdir(exist_ok=True)
    choices = (
        ('org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider',
         DIST / 'solr-solrj-8.11.4.jar'),
        ('org/apache/solr/client/solrj/impl/BaseCloudSolrClient',
         DIST / 'solr-solrj-8.11.4.jar'),
        ('org/apache/solr/client/solrj/embedded/JettySolrRunner',
         DIST / 'solr-core-8.11.4.jar'),
    )
    args = []
    for name, jar in choices:
        path = original / (name.replace('/', '_') + '.class')
        with zipfile.ZipFile(jar) as archive:
            path.write_bytes(archive.read(name + '.class'))
        args.extend((name, str(path)))
    test = 'org/apache/solr/client/solrj/impl/CloudHttp2SolrClientTest'
    args.extend((test, str(HERE / 'classes' / (test + '.class'))))
    cp = ':'.join((str(HERE / 'agent-classes'), classpath(),
                   *(str(p) for p in asm_jars())))
    subprocess.run([str(JAVA8 / 'java'), '-cp', cp,
                    'research.solraliasv2.Smoke', *args], check=True)


if __name__ == '__main__':
    main()
