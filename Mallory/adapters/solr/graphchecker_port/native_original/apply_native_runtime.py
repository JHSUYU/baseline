#!/usr/bin/env python3
"""Stage attested Solr protocol sources for the native JUnit trace runtime.

The original GraphChecker source patch remains intact for static analysis.
This second, system-wide port makes its transport hooks and the native weaver
call the same MessageDoors class in a trial JVM. It never edits a JUnit test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from apply_shard_handoff import RECEIPT as SHARD_RECEIPT


HERE = Path(__file__).resolve().parent
BASE_RECEIPT = HERE / "source_receipt.json"
OLD_NAMESPACE = "edu.uva.liftlab.graphchecker.runtime.MessageDoors"
NEW_NAMESPACE = "edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors"
OLD_WORK_IMPORT = "import edu.uva.liftlab.graphchecker.runtime.RowRuntime;"
NEW_WORK_IMPORT = "import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;"
OLD_WORK = '''      // Carry only an exact submit ticket; the worker starts a fresh path.
      final Object malloryTicket = Boolean.getBoolean("causynth.cluster.automatic")
          ? new Object()
          : null;
      if (malloryTicket != null) {
        RowRuntime.startWork("ExecutorUtil.MDCAwareThreadPoolExecutor.execute", malloryTicket);
      }
      final Runnable malloryCommand = malloryTicket == null ? command : () -> {
        long token = RowRuntime.claimStart(malloryTicket);
        try {
          command.run();
        } finally {
          RowRuntime.endClaim(token);
        }
      };'''
NEW_WORK = '''      // Pair an attributed submission with its exact one-time worker claim.
      final Object malloryTicket = Boolean.getBoolean("causynth.cluster.automatic")
          ? MessageDoors.prepareTask("ExecutorUtil.MDCAwareThreadPoolExecutor.execute", command)
          : null;
      final Runnable malloryCommand = malloryTicket == null ? command : () -> {
        long token = MessageDoors.claimTask(malloryTicket,
            "SOLR_EXECUTOR", "ExecutorUtil.MDCAwareThreadPoolExecutor.execute");
        try {
          command.run();
        } finally {
          MessageDoors.endTask(token);
        }
      };'''
OLD_HTTP_OWNER = "MessageDoors.REQUEST, owner, null);"
NEW_HTTP_OWNER = "MessageDoors.REQUEST, null, null);"
OLD_SHARD_SCOPE = "malloryScope = MessageDoors.captureScope();"
NEW_SHARD_SCOPE = "malloryScope = null; // ExecutorUtil supplies the exact task ticket."


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def port_source(relative: str, source: str) -> str:
    result = source.replace(OLD_NAMESPACE, NEW_NAMESPACE)
    if relative.endswith("/ExecutorUtil.java"):
        if source.count(OLD_WORK_IMPORT) != 1 or source.count(OLD_WORK) != 1:
            raise ValueError("ExecutorUtil handoff differs from attested source")
        result = result.replace(OLD_WORK_IMPORT, NEW_WORK_IMPORT)
        result = result.replace(OLD_WORK, NEW_WORK)
    if relative.endswith("/MalloryHttp.java"):
        if result.count(OLD_HTTP_OWNER) != 1:
            raise ValueError("HTTP request owner differs from attested source")
        # SolrJ client objects are shared across nodes and are not source
        # anchors. The sending request/tick supplies the active node identity.
        result = result.replace(OLD_HTTP_OWNER, NEW_HTTP_OWNER)
    if relative.endswith("/ShardRequestor.java"):
        if result.count(OLD_SHARD_SCOPE) != 1:
            raise ValueError("shard task handoff differs from attested source")
        # Every HttpShardHandler shard task goes through the
        # MDCAwareThreadPoolExecutor. Its one-use ticket must not be replaced
        # by a full submitter context snapshot inside Callable.call().
        result = result.replace(OLD_SHARD_SCOPE, NEW_SHARD_SCOPE)
    if OLD_NAMESPACE in result or OLD_WORK_IMPORT in result or "RowRuntime." in result:
        raise ValueError("Solr source still invokes the separate GraphChecker runtime: "
                         + relative)
    return result


def stage(source: Path, output: Path) -> dict:
    base = json.loads(BASE_RECEIPT.read_text())
    shard = json.loads(SHARD_RECEIPT.read_text())
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=source, text=True).strip()
    if revision != base["source_commit"] or revision != shard["source_commit"]:
        raise ValueError("Solr source revision differs from protocol receipts")
    if digest(HERE / "solr-e27f44e-original-engine.patch") != base["patch_sha256"]:
        raise ValueError("Solr original protocol patch changed")
    if digest(HERE / "solr-e27f44e-shard-request-handoff.patch") != shard[
            "overlay_patch_sha256"]:
        raise ValueError("Solr shard handoff patch changed")
    for relative, expected in base["patched_source_sha256"].items():
        if digest(source / relative) != expected:
            raise ValueError("Solr base protocol input changed: " + relative)
    if digest(source / shard["path"]) != shard["patched_source_sha256"]:
        raise ValueError("Solr shard handoff input changed")
    for relative, expected in base["unchanged_junit_source_sha256"].items():
        if digest(source / relative) != expected:
            raise ValueError("original JUnit source changed: " + relative)
    if output.exists():
        raise ValueError("refusing to overwrite native source overlay: " + str(output))
    java_sources = sorted(relative for relative in base["patched_source_sha256"]
                          if relative.endswith(".java"))
    java_sources.append(shard["path"])
    hashes = {}
    for relative in java_sources:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        transformed = port_source(relative, (source / relative).read_text())
        target.write_text(transformed)
        hashes[relative] = digest(target)
    runner = HERE / "NativeSolrJUnitRunner.java"
    native_runner = output / runner.name
    native_runner.write_text(port_source(runner.name, runner.read_text()))
    receipt = {
        "schema_version": 1,
        "source_commit": revision,
        "base_patch_sha256": base["patch_sha256"],
        "shard_patch_sha256": shard["overlay_patch_sha256"],
        "port_source_sha256": digest(Path(__file__)),
        "native_message_doors": NEW_NAMESPACE,
        "native_java_sha256": hashes,
        "original_runner_sha256": digest(runner),
        "native_runner_sha256": digest(native_runner),
        "unchanged_junit_source_sha256": base["unchanged_junit_source_sha256"],
    }
    (output / "native-runtime-port-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = stage(args.source.resolve(strict=True), args.output.resolve())
    print(json.dumps({"source_commit": receipt["source_commit"],
                      "native_sources": len(receipt["native_java_sha256"]),
                      "receipt": str(args.output / "native-runtime-port-receipt.json")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
