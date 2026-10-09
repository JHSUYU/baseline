"""Exact JaCoCo probe feedback for original Solr production classes."""

from functools import lru_cache
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build import JAVA, SOURCE, classpath  # noqa: E402

CORE = Path.home() / '.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar'
SOURCE_FILE = HERE / 'src/research/solr13/Coverage.java'
CLASSES = HERE / 'coverage-classes'


def build() -> None:
    target = CLASSES / 'research/solr13/Coverage.class'
    if target.is_file() and target.stat().st_mtime >= SOURCE_FILE.stat().st_mtime:
        return
    CLASSES.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                    '-cp', classpath() + ':' + str(CORE),
                    '-d', str(CLASSES), str(SOURCE_FILE)], check=True)


@lru_cache(maxsize=1)
def production_classes() -> set[str]:
    names = set()
    for path in (SOURCE / 'solr').rglob('*.java'):
        parts = path.parts
        if 'src' not in parts:
            continue
        index = parts.index('src')
        if parts[index:index + 2] != ('src', 'java'):
            continue
        if parts[index + 2:index + 3] != ('org',):
            continue
        names.add('/'.join(parts[index + 2:])[:-5])
    return names


def covered_probes(exec_file: Path) -> set[str]:
    if not exec_file.is_file() or not exec_file.stat().st_size:
        return set()
    build()
    cp = ':'.join((str(CLASSES), str(CORE), classpath()))
    output = subprocess.check_output([str(JAVA / 'java'), '-cp', cp,
                                      'research.solr13.Coverage',
                                      str(exec_file)], text=True)
    production = production_classes()
    probes = set()
    for row in output.splitlines():
        kind, class_id, name, index = row.split('\t')
        if kind == 'P' and name.split('$', 1)[0] in production:
            probes.add(class_id + ':' + name + ':' + index)
    return probes
