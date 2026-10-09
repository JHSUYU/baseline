"""JaCoCo feedback from original Solr/Lucene production classes only."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import subprocess

from build import HERE, CASE22, JAVA8, original_classpath

ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')


@lru_cache(maxsize=1)
def production_classes() -> set[str]:
    source = HERE / 'solr-pristine'
    names: set[str] = set()
    for product in ('solr', 'lucene'):
        for path in (source / product).rglob('*.java'):
            parts = path.parts
            if 'src' not in parts or 'java' not in parts:
                continue
            index = parts.index('src')
            if parts[index + 1:index + 3] != ('java', 'org'):
                continue
            names.add('/'.join(parts[index + 2:])[:-5])
    return names


def covered_probes(exec_file: Path) -> set[str]:
    command = [str(JAVA8 / 'java'), '-cp',
               ':'.join((str(HERE / 'classes'), str(CASE22 / 'v5/lib/jacoco-core.jar'), str(ASM_TREE),
                         original_classpath())),
               'research.solrsplit.Coverage', str(exec_file)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    product = production_classes()
    probes: set[str] = set()
    for line in result.stdout.splitlines():
        marker, class_id, name, index = line.split('\t')
        if marker == 'P' and name.split('$', 1)[0] in product:
            probes.add(class_id + ':' + name + ':' + index)
    return probes


def branch_totals(exec_file: Path) -> dict[str, int]:
    jars = []
    for entry in original_classpath().split(':'):
        path = Path(entry)
        if path.name in {'solr-core-8.11.4.jar', 'solr-solrj-8.11.4.jar',
                         'lucene-core-8.11.4.jar'}:
            jars.append(str(path))
    command = [str(JAVA8 / 'java'), '-Xmx2g', '-cp',
               ':'.join((str(HERE / 'classes'), str(CASE22 / 'v5/lib/jacoco-core.jar'), str(ASM_TREE),
                         original_classpath())),
               'research.solrsplit.Coverage', str(exec_file), *sorted(set(jars))]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    product = production_classes()
    covered = total = classes = 0
    for line in result.stdout.splitlines():
        fields = line.split('\t')
        if fields[0] == 'B' and fields[1].split('$', 1)[0] in product:
            covered += int(fields[2]); total += int(fields[3]); classes += 1
    return {'production_branch_covered': covered,
            'production_branch_total': total,
            'production_classes_analyzed': classes}
