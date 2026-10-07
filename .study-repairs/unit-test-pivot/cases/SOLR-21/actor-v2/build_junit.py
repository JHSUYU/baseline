#!/usr/bin/env python3
"""Compile the exact original Solr 8.11.4 JUnit into isolated V2 classes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "independent"
sys.path.insert(0, str(PARENT))
from build import CASE22, JAVA8, SOLR_DIST, TEST_CLASS, TEST_METHOD  # noqa: E402

REVISION = "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
LOCAL_SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
PRISTINE_SOURCE = PARENT / "solr-pristine"
SOURCE = PRISTINE_SOURCE if PRISTINE_SOURCE.is_dir() else LOCAL_SOURCE

TEST_SOURCES = tuple(SOURCE / relative for relative in (
    "solr/core/src/test/org/apache/solr/cloud/api/collections/CollectionReloadTest.java",
    "solr/core/src/test/org/apache/solr/schema/MockExchangeRateProvider.java",
    "solr/core/src/test/org/apache/solr/search/similarities/CustomSimilarityFactory.java",
    "solr/core/src/test/org/apache/solr/search/similarities/MockConfigurableSimilarity.java",
    "solr/core/src/test/org/apache/solr/search/function/NvlValueSourceParser.java",
    "solr/core/src/test/org/apache/solr/search/facet/DebugAgg.java",
))


def source_revision() -> str:
    value = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if value != REVISION:
        raise RuntimeError(f"wrong Solr revision {value}; expected {REVISION}")
    return value


def original_classpath() -> str:
    entries = (CASE22 / "classpath.txt").read_text().strip().split(":")
    old_classes = str(CASE22 / "classes")
    old_resources = str(CASE22 / "solr-source/solr/core/src/test-files")
    resource_alias = HERE / "original-test-files"
    resource_target = SOURCE / "solr/core/src/test-files"
    if resource_alias.is_symlink() and resource_alias.resolve() != resource_target.resolve():
        raise RuntimeError("original test resource alias points at another source checkout")
    if not resource_alias.exists():
        resource_alias.symlink_to(resource_target, target_is_directory=True)
    result = []
    for entry in entries:
        if any(token in entry.lower() for token in
               ("graphchecker", "unit-test-core", "causynth")):
            continue
        if entry == old_classes:
            result.append(str(HERE / "classes"))
        elif entry == old_resources:
            result.append(str(resource_alias))
        else:
            result.append(entry)
    extras = [SOLR_DIST / "dist/solr-analysis-extras-8.11.4.jar"]
    extras += sorted((SOLR_DIST / "contrib/analysis-extras/lib").glob("*.jar"))
    extras += sorted((SOLR_DIST / "contrib/analysis-extras/lucene-libs").glob("*.jar"))
    result += [str(path) for path in extras
               if path.is_file() and str(path) not in result]
    return ":".join(result)


def main() -> None:
    revision = source_revision()
    classes = HERE / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    helper = PARENT / "src/research/solrreload/OriginalJUnit.java"
    cp = original_classpath()
    result = subprocess.run(
        [str(JAVA8 / "javac"), "-source", "8", "-target", "8",
         "-cp", cp, "-d", str(classes), str(helper),
         *(str(source) for source in TEST_SOURCES)],
        capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr)
    original_core = SOLR_DIST / "dist/solr-core-8.11.4.jar"
    receipt = {
        "test": TEST_CLASS + "#" + TEST_METHOD,
        "source_revision": revision,
        "source_path": str(SOURCE),
        "source_sha256": {str(source.relative_to(SOURCE)):
                          hashlib.sha256(source.read_bytes()).hexdigest()
                          for source in TEST_SOURCES},
        "original_solr_core_jar_sha256": hashlib.sha256(original_core.read_bytes()).hexdigest(),
        "classpath_contains_graphchecker": "graphchecker" in cp.lower(),
        "classpath_entries": len(cp.split(":")),
        "classes_sha256": {str(path.relative_to(classes)):
                           hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sorted(classes.rglob("*.class"))},
    }
    parent_receipt = json.loads((PARENT / "build.json").read_text())
    for field in ("source_revision", "source_sha256",
                  "original_solr_core_jar_sha256", "classpath_contains_graphchecker",
                  "classpath_entries", "test"):
        if receipt[field] != parent_receipt[field]:
            raise RuntimeError(f"V2 original JUnit differs from pristine prior build: {field}")
    (HERE / "junit-build.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
