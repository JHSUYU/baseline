#!/usr/bin/env python3
"""Build the SOLR-38 diagnostic adapter from pinned Java sources without Maven."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V1 = HERE.parent / "election-value-node1-v1"
BASE_JAR = (HERE.parent / "election-field-healthy-node2-v1/adapter-election-v1/"
            "mallory-solr-election-adapter.jar")
AGENT = (ROOT / "Mallory/instrumentation/releases/"
         "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
         "mallory-agent.jar")
OUT = HERE / "adapter/mallory-solr-adapter-v2.jar"
MANIFEST = HERE / "source-manifest.json"
PACKAGE = "edu/uva/liftlab/mallory/solr/"
SHADED = "edu.uva.liftlab.mallory.solr.shaded.asm."


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight() -> dict:
    pins = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if pins.get("case_id") != "SOLR-38" or pins.get("mode") != "healthy_value_diagnostic_v2":
        raise ValueError("wrong adapter source manifest")
    inputs = {"base_jar": BASE_JAR, "agent_jar": AGENT,
              "solr_hooks": V1 / "adapter/src/main/java/edu/uva/liftlab/mallory/solr/SolrHooks.java",
              "solr_transformer": V1 / "adapter/src/main/java/edu/uva/liftlab/mallory/solr/SolrTransformer.java"}
    for name, path in inputs.items():
        if not path.is_file() or sha(path) != pins["input_sha256"][name]:
            raise ValueError(f"pinned adapter input changed: {name}")
    with zipfile.ZipFile(BASE_JAR) as base:
        names = set(base.namelist())
    if not {PACKAGE + "SolrHooks.class", PACKAGE + "SolrTransformer.class",
            PACKAGE + "shaded/asm/ClassReader.class",
            PACKAGE + "shaded/asm/Opcodes.class"} <= names:
        raise ValueError("base adapter lacks shaded ASM or adapter classes")
    source = inputs["solr_transformer"].read_text(encoding="utf-8")
    if source.count("import org.objectweb.asm.") != 7 or "leaderValue(method, true)" not in source:
        raise ValueError("diagnostic transformer import or hook drift")
    return {"case_id": "SOLR-38", "mode": pins["mode"],
            "base_adapter_sha256": pins["input_sha256"]["base_jar"],
            "agent_sha256": pins["input_sha256"]["agent_jar"],
            "output": str(OUT), "build_tool": "javac+python-zipfile", "maven_required": False}


def build() -> dict:
    report = preflight()
    if OUT.exists():
        raise ValueError("diagnostic adapter output already exists")
    with tempfile.TemporaryDirectory(prefix="solr38-value-v2-", dir=HERE) as scratch:
        work = Path(scratch)
        package = work / PACKAGE
        package.mkdir(parents=True)
        hook = V1 / "adapter/src/main/java/edu/uva/liftlab/mallory/solr/SolrHooks.java"
        transformer = V1 / "adapter/src/main/java/edu/uva/liftlab/mallory/solr/SolrTransformer.java"
        (package / "SolrHooks.java").write_bytes(hook.read_bytes())
        rewritten = transformer.read_text(encoding="utf-8").replace(
            "import org.objectweb.asm.", "import " + SHADED)
        (package / "SolrTransformer.java").write_text(rewritten, encoding="utf-8")
        classes = work / "classes"
        classes.mkdir()
        build_env = os.environ.copy()
        build_env.pop("JAVA_TOOL_OPTIONS", None)
        subprocess.run(["javac", "-source", "8", "-target", "8", "-cp",
                        str(BASE_JAR) + ":" + str(AGENT), "-d", str(classes),
                        str(package / "SolrHooks.java"),
                        str(package / "SolrTransformer.java")], env=build_env, check=True)
        compiled = sorted(classes.rglob("*.class"))
        class_names = {str(path.relative_to(classes)) for path in compiled}
        if not {PACKAGE + "SolrHooks.class", PACKAGE + "SolrTransformer.class"} <= class_names:
            raise ValueError("diagnostic adapter compilation produced no hook classes")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        temporary = OUT.with_suffix(".jar.tmp")
        try:
            with zipfile.ZipFile(BASE_JAR) as base, zipfile.ZipFile(temporary, "w") as output:
                for info in base.infolist():
                    if info.filename.startswith(PACKAGE + "SolrHooks$") or info.filename.startswith(
                            PACKAGE + "SolrTransformer$") or info.filename in {
                            PACKAGE + "SolrHooks.class", PACKAGE + "SolrTransformer.class"}:
                        continue
                    output.writestr(info, base.read(info.filename))
                for path in compiled:
                    name = str(path.relative_to(classes))
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    output.writestr(info, path.read_bytes())
            with zipfile.ZipFile(temporary) as output:
                entries = output.namelist()
                names = set(entries)
            if not class_names <= names or len(entries) != len(names):
                raise ValueError("diagnostic adapter has missing or duplicate classes")
            temporary.replace(OUT)
        finally:
            temporary.unlink(missing_ok=True)
    report.update(adapter_sha256=sha(OUT), compiled_classes=len(compiled))
    (HERE / "adapter/build-receipt.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(preflight() if args.preflight_only else build(), sort_keys=True))
