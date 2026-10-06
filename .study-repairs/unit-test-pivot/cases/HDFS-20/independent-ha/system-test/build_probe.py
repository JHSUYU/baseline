#!/usr/bin/env python3
"""Compile case-local source probes for the exact guard and observed I/O."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs20haindependent.Probe"
SOURCE = CASE / "source/main"
GENERATED = HERE / "generated"
CLASSES = HERE / "probe-classes"


def override(name: str, replacement: tuple[str, str]) -> Path:
    original = SOURCE / name
    text = original.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise RuntimeError(f"no Java package declaration in {original}")
    text = text[:package.end()] + "\nimport " + PROBE + ";" + text[package.end():]
    before, after = replacement
    if text.count(before) != 1:
        raise RuntimeError(f"expected one probe site in {original}: {text.count(before)}")
    text = text.replace(before, after, 1)
    output = GENERATED / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return output


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    bpos = override(
        "org/apache/hadoop/hdfs/server/datanode/BPOfferService.java",
        ("      if (bpServiceToActive == actor) {\n"
         "        assert txid >= lastActiveClaimTxId;\n"
         "        lastActiveClaimTxId = txid;",
         "      if (bpServiceToActive == actor) {\n"
         "        final boolean hdfs20Allowed = txid >= lastActiveClaimTxId;\n"
         "        Probe.guard(hdfs20Allowed, this, actor, txid,\n"
         "            lastActiveClaimTxId, nnClaimsActive, bposThinksActive);\n"
         "    try {\n"
         "          assert hdfs20Allowed;\n"
         "        } catch (AssertionError hdfs20TargetException) {\n"
         "          Probe.targetException(hdfs20TargetException);\n"
         "          throw hdfs20TargetException;\n"
         "        }\n"
         "        lastActiveClaimTxId = txid;"))
    constructor_end = (
        "      this.bpServices.add(new BPServiceActor(nameserviceId, nnIds.get(i),\n"
        "          nnAddrs.get(i), lifelineNnAddrs.get(i), this));\n"
        "    }\n"
        "  }\n\n"
        "  void refreshNNList")
    generated = bpos.read_text()
    if generated.count(constructor_end) != 1:
        raise RuntimeError("expected one BPOfferService constructor end")
    bpos.write_text(generated.replace(
        constructor_end,
        constructor_end.replace("  }\n\n  void refreshNNList",
                                "    Probe.bposCreated(this, bpServices, nnAddrs);\n"
                                "  }\n\n  void refreshNNList"), 1))
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        ("  private Writable getRpcResponse(final Call call, final Connection connection,\n"
         "      final long timeout, final TimeUnit unit) throws IOException {\n"
         "    synchronized (call) {",
         "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
         "      final long timeout, final TimeUnit unit) throws IOException {\n"
         "    Probe.io(\"RPC_RESPONSE\", connection.getRemoteAddress());\n"
         "    synchronized (call) {"))
    file_io = override(
        "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
        ("  public void flushAndSync(boolean durable) throws IOException {\n"
         "    if (fp == null) {",
         "  public void flushAndSync(boolean durable) throws IOException {\n"
         "    Probe.io(\"FILE_FLUSH\", durable ? \"durable\" : \"buffered\");\n"
         "    if (fp == null) {"))
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), str(HERE / "Probe.java"), str(bpos),
               str(rpc), str(file_io)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream,
                                   stderr=subprocess.STDOUT)
    record = {"exit": completed.returncode, "probe_classes": str(CLASSES),
              "original_sources": [str(SOURCE / path) for path in (
                  "org/apache/hadoop/hdfs/server/datanode/BPOfferService.java",
                  "org/apache/hadoop/ipc/Client.java",
                  "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java")],
              "instrumentation": "isolated source-level probes; no GraphChecker or graph artifacts"}
    (HERE / "build-probe.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
