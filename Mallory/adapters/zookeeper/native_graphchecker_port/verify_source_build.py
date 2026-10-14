"""Rebuild the native ZooKeeper GraphChecker port and compare class bytes.

Example:
  python3 verify_source_build.py --profile PROFILE.json --engine-jar ENGINE.jar \
      --reference-classes PINNED_PROTOCOL_CLASSES --javac /path/to/javac
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root, suffix):
    return {str(path.relative_to(root)): sha(path)
            for path in sorted(root.rglob("*" + suffix))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--engine-jar", type=Path, required=True)
    parser.add_argument("--reference-classes", type=Path, required=True)
    parser.add_argument("--javac", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "source-provenance.json").read_text())
    sources = files(root / "src/main/java", ".java")
    sources = {"src/main/java/" + name: digest
               for name, digest in sources.items()}
    if sources != manifest["source_files_sha256"]:
        raise ValueError("protocol source files differ from provenance")
    if sha(args.profile) != manifest["pinned_profile_sha256"]:
        raise ValueError("classpath profile differs from provenance")
    if sha(args.engine_jar) != manifest["pinned_engine_jar_sha256"]:
        raise ValueError("GraphChecker engine differs from provenance")
    reference = files(args.reference_classes, ".class")
    if reference != manifest["compiled_class_sha256"]:
        raise ValueError("reference class tree differs from provenance")
    profile = json.loads(args.profile.read_text())
    classpath = [str(args.engine_jar)]
    for key in ("scope_planner_classpath", "runner_classpath",
                "post_weave_classpath", "analysis_classpath",
                "runtime_classpath"):
        classpath.extend(profile.get(key, []))
    classpath = list(dict.fromkeys(classpath))
    with tempfile.TemporaryDirectory(prefix="zk-native-protocol-build-") as temp:
        output = Path(temp)
        command = [str(args.javac), "-source", "8", "-target", "8",
                   "-cp", ":".join(classpath), "-d", str(output)]
        command.extend(str(root / name) for name in sources)
        subprocess.run(command, check=True)
        built = files(output, ".class")
    if built != reference:
        raise ValueError("source rebuild differs from pinned protocol classes")
    print(json.dumps({"status": "byte_exact", "sources": len(sources),
                      "classes": len(built)}, sort_keys=True))


if __name__ == "__main__":
    main()
