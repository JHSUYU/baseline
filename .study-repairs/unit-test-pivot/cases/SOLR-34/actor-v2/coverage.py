"""JaCoCo probe feedback from original, unmodified Solr/Lucene production classes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import subprocess

from build import CASE22, HERE, JAVA8, SOURCE, original_classpath


ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
JACOCO_CORE = CASE22 / 'v5/lib/jacoco-core.jar'
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
    helper = HERE / 'src/research/solrsplit/Coverage.java'
    helper_class = HERE / 'classes/research/solrsplit/Coverage.class'
    if not helper_class.is_file() or helper_class.stat().st_mtime < helper.stat().st_mtime:
        subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                        '-cp', str(JACOCO_CORE), '-d', str(HERE / 'classes'),
                        str(helper)], capture_output=True, text=True, check=True)
    cp = ':'.join((str(HERE / 'classes'), str(JACOCO_CORE), str(ASM_TREE),
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
