"""Tree mode: a checklist row whose workload runs on a built source tree.

A row normally runs its system's Apache release (``settings.DEPS``). A row
with a ``tree`` field runs a built checkout instead -- an old bug put back
by hand on today's code, whose fix the releases already hold::

    "tree": {"path": "/.../hadoop-hdfs-bug-11741",
             "jvm_properties": ["-Dtest.build.data={data}"],   # optional
             "report": "<path of the test's JUnit XML report>"}  # optional

Everything the run needs comes from the tree's own build:

* the test's JUnit XML report (Surefire's, or Ant's) states the test JVM's
  ``java.class.path``; that is the workload's classpath, with every jar of a
  tree module replaced by the module's compiled classes (the code the tree
  holds now, not a copy installed into a Maven repository);
* an entry holding GraphChecker's classes (``edu/uva/liftlab/graphchecker``)
  is dropped: CrashFuzz never runs GraphChecker;
* a tree whose code calls an adapter API it builds against as a provided
  dependency (GraphChecker's doors) gets a neutral stand-in for exactly the
  classes it references and nothing provides (``runtime-agent``'s
  ``NeutralAdapter``: no answer records, holds or defers anything);
* the Soot selection analyses the tree's classes of the modules the release
  analysis uses (``SystemSpec.analysis_jars``), so a tree row and a release
  row of one system see the same code base;
* the test's JUnit flavour (Jupiter or JUnit 4) is read off its class.

``jvm_properties`` are the workload JVM's system properties; ``{tmp}``,
``{data}``, ``{scratch}``, ``{tree}``, ``{test_classes}`` and ``{systems}``
name the run's scratch directories, the tree, its test classes and
``crashfuzz/systems/``. The result is ``<case>/tree-workload.json``,
which the runner (``runners/tree.py``) executes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from . import settings
from .trace import atomic_json

GRAPHCHECKER_PACKAGE = "edu/uva/liftlab/graphchecker/"
# Classes a tree's adapter code may call without holding them: GraphChecker's
# runtime and its shims (``Causynth*`` classes, e.g. Hadoop's
# ``org.apache.hadoop.ipc.CausynthMessagePropagation``). A class of this
# namespace the tree does hold is never replaced.
ADAPTER_NAMESPACE = r"^edu/uva/liftlab/graphchecker/|(^|/)Causynth[^/$]*(\$[^/]*)?$"
ADAPTER_HINTS = ("edu/uva/liftlab/graphchecker/", "Causynth")
ADAPTER_MAIN = "edu.uva.liftlab.crashfuzz.runtime.NeutralAdapter"
_JAR_VERSION = re.compile(r"^(?P<artifact>.+?)-(?P<version>\d[^/]*?)(?P<tests>-tests)?\.jar$")


def tree_of(row: dict[str, Any]) -> Path | None:
    """The built tree a row runs on, or None for a release row."""
    tree = row.get("tree")
    return Path(tree["path"]) if tree else None


def source_root(row: dict[str, Any], release_source: Path) -> Path:
    """Where the row's source files are: its tree, else the release source."""
    tree = tree_of(row)
    return tree if tree is not None else release_source


# --- the test's report ------------------------------------------------------------

def report_path(tree: Path, test_class: str, declared: str | None = None) -> Path:
    """The JUnit XML report of the test's run in the tree's build."""
    if declared:
        path = Path(declared)
        return path if path.is_absolute() else tree / path
    name = f"TEST-{test_class}.xml"
    patterns = [f"{'*/' * depth}target/surefire-reports/{name}" for depth in range(4)]
    patterns += [f"{'*/' * depth}build/*/test/{name}" for depth in range(3)]
    for pattern in patterns:
        found = sorted(tree.glob(pattern))
        if found:
            return found[0]
    raise FileNotFoundError(f"no JUnit report of {test_class} under {tree} (build the tree's test)")


def report_properties(report: Path) -> dict[str, str]:
    root = ET.parse(report).getroot()
    return {item.get("name", ""): item.get("value", "")
            for item in root.iter("property")}


# --- classpath entries -----------------------------------------------------------

def holds_package(entry: Path, package: str) -> bool:
    """A directory or jar holding classes of ``package`` (``a/b/``)."""
    if entry.is_dir():
        return (entry / package).is_dir()
    if entry.is_file() and entry.suffix in {".jar", ".zip"}:
        try:
            with zipfile.ZipFile(entry) as archive:
                return any(name.startswith(package) for name in archive.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
    return False


def _pom_identity(pom: Path) -> tuple[str | None, str | None]:
    try:
        root = ET.parse(pom).getroot()
    except (OSError, ET.ParseError):
        return None, None
    namespace = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    artifact = root.findtext(namespace + "artifactId")
    version = (root.findtext(namespace + "version") or
               root.findtext(f"{namespace}parent/{namespace}version"))
    return artifact, version


def tree_modules(tree: Path) -> dict[str, tuple[Path, str | None]]:
    """The tree's Maven modules with compiled classes: artifactId -> (module, version)."""
    modules = {}
    for depth in range(4):
        for pom in sorted(tree.glob("*/" * depth + "pom.xml")):
            module = pom.parent
            if not (module / "target" / "classes").is_dir():
                continue
            artifact, version = _pom_identity(pom)
            if artifact and artifact not in modules:
                modules[artifact] = (module, version)
    return modules


def tree_entry(entry: str, modules: dict[str, tuple[Path, str | None]]) -> str | None:
    """The tree module's compiled classes standing for a jar of it, or None."""
    match = _JAR_VERSION.match(Path(entry).name)
    if not match or match.group("artifact") not in modules:
        return None
    module, version = modules[match.group("artifact")]
    jar_version = match.group("version")
    if version and "$" not in version:
        if version != jar_version:
            return None
    elif not jar_version.endswith("-SNAPSHOT"):
        return None
    classes = module / "target" / ("test-classes" if match.group("tests") else "classes")
    return str(classes) if classes.is_dir() else None


def is_test_entry(entry: str) -> bool:
    path = Path(entry)
    return (path.name == "test-classes" or path.parts[-2:] == ("classes", "test") or
            path.name.endswith("-tests.jar"))


def entry_artifact(entry: str, tree: Path) -> str | None:
    """The artifact a tree classpath entry is the code of, or None."""
    path = Path(entry)
    try:
        path.relative_to(tree)
    except ValueError:
        return None
    if path.parts[-2:] == ("target", "classes"):
        return _pom_identity(path.parent.parent / "pom.xml")[0]
    if path.parts[-2:] == ("classes", "java") and path.parts[-4] == "build":
        return path.parts[-3]          # Ant: <project>/build/<artifact>/classes/java
    match = _JAR_VERSION.match(path.name)
    return match.group("artifact") if match and not match.group("tests") else None


def release_artifacts(analysis_jars: tuple[str, ...]) -> set[str]:
    """The artifacts the release analysis reads (``hadoop-hdfs-3.4.3.jar`` -> ``hadoop-hdfs``)."""
    names = set()
    for jar in analysis_jars:
        match = _JAR_VERSION.match(Path(jar).name)
        if match:
            names.add(match.group("artifact"))
    return names


def _commit(tree: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def launcher_kind(classpath: list[str], test_class: str) -> str:
    """``jupiter`` or ``junit4``: what the test class is annotated with."""
    relative = Path(*test_class.split(".")).with_suffix(".class")
    for entry in classpath:
        path = Path(entry) / relative
        if path.is_file():
            data = path.read_bytes()
            if b"org/junit/jupiter/api/" in data:
                return "jupiter"
            if b"Lorg/junit/Test;" in data or b"org/junit/runner/RunWith" in data:
                return "junit4"
            break
    return ("jupiter" if any("/junit-jupiter-engine-" in entry for entry in classpath)
            else "junit4")


# --- the workload -----------------------------------------------------------------

def resolve(row: dict[str, Any], test_class: str, test_method: str,
            analysis_jars: tuple[str, ...], heap: str) -> dict[str, Any]:
    """The workload of a tree row: classpath, analysis directories, launcher."""
    tree = Path(row["tree"]["path"]).resolve()
    if not tree.is_dir():
        raise FileNotFoundError(f"tree missing: {tree}")
    report = report_path(tree, test_class, row["tree"].get("report"))
    properties = report_properties(report)
    recorded = [entry for entry in properties.get("java.class.path", "").split(os.pathsep) if entry]
    if not recorded:
        raise ValueError(f"report states no java.class.path: {report}")
    modules = tree_modules(tree)
    classpath: list[str] = []
    dropped: list[str] = []
    replaced: dict[str, str] = {}
    for entry in recorded:
        if holds_package(Path(entry), GRAPHCHECKER_PACKAGE):
            dropped.append(entry)
            continue
        local = tree_entry(entry, modules)
        if local:
            replaced[entry] = local
            entry = local
        if Path(entry).exists() and entry not in classpath:
            classpath.append(entry)
    wanted = release_artifacts(analysis_jars)
    analysis_dirs = [entry for entry in classpath
                     if not is_test_entry(entry) and entry_artifact(entry, tree) in wanted]
    if not analysis_dirs:
        raise ValueError(f"no tree classes of {sorted(wanted)} on the workload classpath")
    test_classes = next((entry for entry in classpath if is_test_entry(entry) and
                         Path(entry).is_dir() and
                         (Path(entry) / Path(*test_class.split(".")).with_suffix(".class"))
                         .is_file()), None)
    return {"schema_version": 1, "tree": str(tree), "commit": _commit(tree),
            "report": str(report), "test_class": test_class, "test_method": test_method,
            "classpath": classpath, "dropped": dropped, "replaced": replaced,
            "analysis_dirs": analysis_dirs, "test_classes": test_classes,
            "launcher": launcher_kind(classpath, test_class),
            "jvm_properties": list(row["tree"].get("jvm_properties", [])),
            "heap": row["tree"].get("heap", heap)}


def generate_adapter(workload: dict[str, Any], directory: Path) -> dict[str, Any]:
    """The neutral stand-in classes the tree's code needs (cached by its inputs)."""
    tree = Path(workload["tree"])
    scanned = [entry for entry in workload["classpath"] if _under(Path(entry), tree)]
    key = {"commit": workload["commit"], "classpath": workload["classpath"],
           "namespace": ADAPTER_NAMESPACE, "tool": _identity(settings.AGENT_JAR),
           "scanned": {entry: _identity(Path(entry)) for entry in scanned}}
    classes = directory / "classes"
    manifest = directory / "neutral-adapter.json"
    key_path = directory / "key.json"
    if not (key_path.is_file() and json.loads(key_path.read_text()) == key and
            manifest.is_file()):
        if not settings.AGENT_JAR.is_file():
            raise FileNotFoundError(f"build the runtime agent first: {settings.AGENT_JAR}")
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rm", "-rf", "--", str(classes)], check=True)
        classes.mkdir()
        subprocess.run([str(settings.JAVA_BIN / "java"), "-cp", str(settings.AGENT_JAR),
                        ADAPTER_MAIN, str(classes), str(manifest), ADAPTER_NAMESPACE,
                        ",".join(ADAPTER_HINTS),
                        *("+" + entry for entry in scanned),
                        *(entry for entry in workload["classpath"] if entry not in scanned)],
                       check=True)
        atomic_json(key_path, key)
    record = json.loads(manifest.read_text())
    return {"directory": str(classes), "manifest": str(manifest),
            "classes": [item["class"] for item in record.get("classes", [])]}


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _identity(path: Path) -> list[Any]:
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def prepare(row: dict[str, Any], test_class: str, test_method: str,
            analysis_jars: tuple[str, ...], heap: str, base: Path) -> tuple[dict[str, Any], Path]:
    """Resolve the row's workload, add its adapter, and write ``<base>/tree-workload.json``."""
    workload = resolve(row, test_class, test_method, analysis_jars, heap)
    adapter = generate_adapter(workload, base / "tree-adapter")
    workload["adapter"] = adapter
    if adapter["classes"]:
        workload["classpath"] = workload["classpath"] + [adapter["directory"]]
    workload["classpath_sha256"] = hashlib.sha256(
        os.pathsep.join(workload["classpath"]).encode()).hexdigest()
    path = base / "tree-workload.json"
    atomic_json(path, workload)
    return workload, path


def analysis(workload: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """The Soot selector's input: the release analysis's options over the tree's classes.

    The rest of the workload's main classpath is Soot's classpath: it selects
    nothing from it (only the analysed classes are application classes), but
    types against it, so a check throwing a library's exception (HBase's
    ``InvalidToken`` is Hadoop's) gets its type rather than a phantom
    ``Throwable``.
    """
    analysed = set(workload["analysis_dirs"])
    return {"process_dirs": list(workload["analysis_dirs"]),
            "classpath": [entry for entry in workload["classpath"]
                          if entry not in analysed and not is_test_entry(entry)],
            **options}
