#!/usr/bin/env python3
"""Freeze and verify a byte-for-byte V5 campaign handoff between nodes.

This tool does not stop or start a campaign. The operator must first let the
source campaign finish a trial and exit, then run ``manifest`` there. Copy the
whole actor-v2 directory to an isolated destination and run ``verify`` there.
Only after verification may the destination campaign be resumed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from datetime import datetime, timezone


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "work/solr-source"
CAMPAIGN = CASE / "evidence/campaign-v4"
MANIFEST = CAMPAIGN / "migration-v5-manifest.json"
EXCLUDED = {MANIFEST.relative_to(CASE).as_posix(),
            (CAMPAIGN / "migration-v5-verified.json").relative_to(CASE).as_posix()}
DESTINATION_CALIBRATION = "evidence/campaign-v4/node1-handoff-calibration/"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def checked(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def static_receipt() -> dict:
    """Hash each classpath file plus all files in classpath directories."""
    build_path = CASE / "build-receipt.json"
    build = json.loads(build_path.read_text())
    commit = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    checked(commit == build["source_commit"], "source commit differs from build")
    source = {name: digest(SOURCE / name) for name in build["source_file_sha256"]}
    checked(source == build["source_file_sha256"], "source file differs from build")
    test_class = "org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"
    originals = {which: digest(CASE / which / test_class)
                 for which in ("classes", "classes-original")}
    checked(set(originals.values()) == {build["test_class_sha256"]},
            "original JUnit class differs from build")
    probe = digest(CASE / "classes/baseline/solr103940/FeedbackProbe.class")
    checked(probe == build["actor_probe_class_sha256"], "actor hook differs from build")
    production = {name: digest(CASE / "classes" / name)
                  for name in build["instrumented_production_class_sha256"]}
    checked(production == build["instrumented_production_class_sha256"],
            "instrumented production class differs from build")
    classpaths = {}
    for name in ("classpath.txt", "original-classpath.txt"):
        path = CASE / name
        entries = path.read_text().strip().split(":")
        checked(bool(entries) and all(entries), f"empty entry in {name}")
        files = {}
        for item in entries:
            entry = Path(item)
            checked(entry.exists(), f"missing classpath entry: {item}")
            if entry.is_file():
                files[item] = digest(entry)
            elif entry.is_dir():
                members = sorted(p for p in entry.rglob("*") if p.is_file())
                for member in members:
                    files[str(member)] = digest(member)
            else:
                raise RuntimeError(f"unsupported classpath entry: {item}")
        classpaths[name] = {"sha256": digest(path), "entries": entries,
                            "files": files}
    return {"source_commit": commit, "build_receipt_sha256": digest(build_path),
            "source_file_sha256": source, "original_junit_class_sha256": originals,
            "actor_probe_class_sha256": probe,
            "instrumented_production_class_sha256": production,
            "classpaths": classpaths,
            "port_policy": "unchanged embedded JUnit uses dynamic Jetty/ZK ports",
            "scratch_policy": "each run.py trial uses its own trial-NNN/scratch"}


def active_campaign() -> list[int]:
    found = []
    relative_case = str(CASE.relative_to(Path("/users/ZhenyuLi/baseline")))
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal() or int(proc.name) == os.getpid():
            continue
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace")
        except (OSError, PermissionError):
            continue
        if (str(CASE) in command or relative_case in command) and (
                "probe/campaign.py" in command or "probe/run.py" in command or
                "RunSingleJUnit" in command):
            found.append(int(proc.name))
    return sorted(found)


def file_manifest() -> dict:
    files = {}
    for path in sorted(CASE.rglob("*")):
        name = path.relative_to(CASE).as_posix()
        if (name in EXCLUDED or name.startswith(DESTINATION_CALIBRATION) or
                "__pycache__" in path.parts or path.suffix == ".pyc"):
            continue
        checked(not path.is_symlink(), f"unexpected symlink: {name}")
        if path.is_file():
            files[name] = digest(path)
    return files


def frozen_manifest() -> dict:
    state_path = CAMPAIGN / "state.json"
    state = json.loads(state_path.read_text())
    checked(state["inflight"] is None, "source is inside a trial")
    checked(not active_campaign(), "source campaign/JUnit is still running")
    checked(state["build_receipt_sha256"] == digest(CASE / "build-receipt.json"),
            "checkpoint build receipt differs")
    checked(len(state["seen_plans"]) == len(state["trials"]),
            "seen plans and trial history differ")
    checked(all(t["number"] == index for index, t in enumerate(state["trials"], 1)),
            "trial numbering differs")
    return {"format": 1, "origin": socket.gethostname(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "trial_count": len(state["trials"]), "queue_count": len(state["queue"]),
            "seen_plan_count": len(state["seen_plans"]),
            "effective": {site: progress["effective"]
                          for site, progress in state["site_progress"].items()},
            "state_sha256": digest(state_path), "static": static_receipt(),
            "files": file_manifest()}


def verify_manifest(manifest: dict, *, static: bool = True) -> dict:
    checked(manifest["format"] == 1, "unknown manifest format")
    if static:
        checked(manifest["static"] == static_receipt(),
                "source, hook, JUnit or per-file classpath differs")
    actual = file_manifest()
    expected = manifest["files"]
    checked(set(actual) == set(expected),
            f"file set differs: missing={sorted(set(expected)-set(actual))[:10]}, "
            f"extra={sorted(set(actual)-set(expected))[:10]}")
    bad = [name for name, value in expected.items() if actual[name] != value]
    checked(not bad, f"file SHA differs: {bad[:10]}")
    state = json.loads((CAMPAIGN / "state.json").read_text())
    checked(state["inflight"] is None, "destination checkpoint is inside a trial")
    checked(len(state["trials"]) == manifest["trial_count"], "trial count differs")
    checked(len(state["queue"]) == manifest["queue_count"], "queue count differs")
    checked(len(state["seen_plans"]) == manifest["seen_plan_count"],
            "seen plan count differs")
    checked(digest(CAMPAIGN / "state.json") == manifest["state_sha256"],
            "checkpoint SHA differs")
    return {"verified_host": socket.gethostname(),
            "verified_utc": datetime.now(timezone.utc).isoformat(),
            "manifest_sha256": digest(MANIFEST),
            "trial_count": manifest["trial_count"],
            "effective": manifest["effective"], "file_count": len(actual),
            "classpath_file_count": sum(len(v["files"]) for v in
                                        manifest["static"]["classpaths"].values()),
            "state_sha256": manifest["state_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "manifest", "verify-files",
                                            "verify"))
    args = parser.parse_args()
    if args.command == "preflight":
        receipt = static_receipt()
        receipt_sha = hashlib.sha256(json.dumps(receipt, sort_keys=True,
                                                 separators=(",", ":")).encode()).hexdigest()
        print(json.dumps({"host": socket.gethostname(),
                          "build_receipt_sha256": receipt["build_receipt_sha256"],
                          "static_receipt_sha256": receipt_sha,
                          "source_commit": receipt["source_commit"],
                          "classpath_file_count": sum(len(v["files"]) for v in
                                                      receipt["classpaths"].values()),
                          "active_campaign_pids": active_campaign()}, sort_keys=True))
    elif args.command == "manifest":
        result = frozen_manifest()
        temporary = MANIFEST.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        temporary.replace(MANIFEST)
        print(json.dumps({"host": result["origin"], "trial_count": result["trial_count"],
                          "effective": result["effective"], "file_count": len(result["files"]),
                          "state_sha256": result["state_sha256"],
                          "manifest_sha256": digest(MANIFEST)}, sort_keys=True))
    else:
        print(json.dumps(verify_manifest(json.loads(MANIFEST.read_text()),
                                         static=args.command == "verify"), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"V5 migration refused: {error}", file=sys.stderr)
        sys.exit(1)
