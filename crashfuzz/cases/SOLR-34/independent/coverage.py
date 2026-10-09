"""JaCoCo probe feedback from original, unmodified Solr/Lucene production classes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import subprocess

from build import CASE22, HERE, JAVA8, SOURCE, original_classpath


CASE14_CLASSES = HERE.parents[1] / 'SOLR-14/independent/classes'
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
WOVEN = {'org/apache/solr/servlet/CoordinatorHttpSolrCall',
         'org/apache/solr/common/cloud/SolrZkClient'}


@lru_cache(maxsize=1)
def production_classes() -> set[str]:
    names: set[str] = set()
    for product in ('solr', 'lucene'):
        for path in (SOURCE / product).rglob('*.java'):
            parts = path.parts
            if 'src' not in parts or 'java' not in parts:
                continue
            index = parts.index('src')
            if parts[index + 1:index + 3] == ('java', 'org'):
                names.add('/'.join(parts[index + 2:])[:-5])
    return names - WOVEN


def covered_probes(exec_file: Path) -> set[str]:
    cp = ':'.join((str(CASE14_CLASSES), str(HERE / 'classes'),
                   str(CASE22 / 'v5/lib/jacoco-core.jar'), str(ASM_TREE),
                   original_classpath()))
    command = [str(JAVA8 / 'java'), '-cp', cp,
               'research.solrsplit.Coverage', str(exec_file)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    product = production_classes()
    probes: set[str] = set()
    for line in result.stdout.splitlines():
        marker, class_id, name, index = line.split('\t')
        if marker == 'P' and name.split('$', 1)[0] in product:
            probes.add(class_id + ':' + name + ':' + index)
    return probes
