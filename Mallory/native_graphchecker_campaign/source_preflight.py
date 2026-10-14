"""Validate the frozen native feedback source before launching a JUnit JVM."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feedback_bridge(root: Path, engine_jar: Path) -> dict[str, str]:
    """Pin and compile the bridge from the exact campaign source snapshot.

    This runs once at admission. It catches incomplete source archives before
    the much slower unchanged cluster JUnit starts.
    """
    root = root.resolve(strict=True)
    source = root / "Mallory/native_graphchecker_feedback/NativeFeedbackMain.java"
    dependencies = (root / "Mallory/static_scope_port/original_engine/target/"
                    "native-original-dependencies.txt")
    if not source.is_file() or source.is_symlink():
        raise ValueError("frozen campaign lacks NativeFeedbackMain.java")
    if not dependencies.is_file() or dependencies.is_symlink():
        raise ValueError("frozen campaign lacks native-original-dependencies.txt")
    engine_jar = engine_jar.resolve(strict=True)
    entries = dependencies.read_text(encoding="utf-8").strip().split(os.pathsep)
    if not entries or any(not Path(entry).is_absolute() or
                          not Path(entry).is_file() for entry in entries):
        raise ValueError("frozen feedback dependency classpath is incomplete")
    with tempfile.TemporaryDirectory(prefix=".feedback-preflight-") as temporary:
        output = Path(temporary)
        result = subprocess.run(
            ["javac", "-cp", os.pathsep.join((str(engine_jar), *entries)),
             "-d", str(output), str(source)], capture_output=True,
            text=True, timeout=120)
        clazz = (output / "edu/uva/liftlab/mallory/nativefeedback/"
                 "NativeFeedbackMain.class")
        if result.returncode != 0 or not clazz.is_file():
            raise ValueError("frozen native feedback bridge does not compile: " +
                             result.stderr[-1200:])
        class_sha = _sha(clazz)
    return {"source_sha256": _sha(source),
            "dependencies_sha256": _sha(dependencies),
            "engine_jar_sha256": _sha(engine_jar),
            "compiled_class_sha256": class_sha}
