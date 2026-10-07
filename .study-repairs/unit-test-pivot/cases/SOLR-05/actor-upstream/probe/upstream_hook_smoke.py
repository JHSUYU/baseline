#!/usr/bin/env python3
"""Check the upstream state-writer hooks without running a cluster."""

import hashlib
import json
from pathlib import Path
import subprocess

from deps import asm_jars

CASE = Path(__file__).resolve().parents[1]
JAVA8 = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    out = CASE / "evidence/offline-upstream-hook"
    classes = CASE / "smoke-classes"
    out.mkdir(parents=True, exist_ok=True)
    classes.mkdir(exist_ok=True)
    asm = str(asm_jars()[0])
    subprocess.run([str(JAVA8 / "javac"), "-cp", asm, "-d", str(classes),
                    str(CASE / "probe/AsmHookAudit.java")], check=True)
    target = CASE / "classes/org/apache/solr/cloud/overseer/ZkStateWriter.class"
    counts = {}
    for hook in ("recordUpstreamUpdate", "upstreamWrite", "upstreamWriteDone"):
        output = subprocess.check_output([str(JAVA8 / "java"), "-cp",
                                          str(classes) + ":" + asm,
                                          "baseline.solr05v2.AsmHookAudit",
                                          str(target), hook, "1"], text=True)
        counts[hook] = int(output.strip())
    source = (CASE / "generated/solr/core/src/java/org/apache/solr/cloud/overseer/ZkStateWriter.java").read_text()
    pre = source.index("FeedbackProbe.upstreamWrite(this, reader.getZkClient()")
    write = source.index("Stat stat = reader.getZkClient().setData(path, data")
    post = source.index("FeedbackProbe.upstreamWriteDone(this, reader.getZkClient()")
    if not pre < write < post:
        raise AssertionError("Pre/write/post source order changed")
    test = Path("org/apache/solr/cloud/AddReplicaTest.class")
    if sha(CASE / "classes" / test) != sha(CASE / "classes-original" / test):
        raise AssertionError("Original JUnit bytecode differs")
    (out / "receipt.json").write_text(json.dumps({
        "hook_counts": counts, "pre_write_post_order": True,
        "unchanged_original_junit": True,
        "writer_class_sha256": sha(target),
        "junit_class_sha256": sha(CASE / "classes" / test),
    }, indent=2, sort_keys=True) + "\n")
    print("SOLR05_UPSTREAM_HOOK_SMOKE_PASS")


if __name__ == "__main__":
    main()
