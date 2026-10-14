#!/usr/bin/env python3
"""Prepare original GraphChecker Solr runs from the 102-case inventory.

Preparation is split at the actual evidence boundaries: static selection,
REGION_STATE weaving, then an unchanged JUnit recording plus the original
Recorder/Scheduler. This module never chooses a case-specific I/O site.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import zipfile


MALLORY = Path(__file__).resolve().parents[3]
INVENTORY = MALLORY / "cases/inventory.json"
NATIVE_WEAVER = MALLORY / "instrumentation/graphchecker_port/native_original_weave.py"
NATIVE_PROTOCOL = MALLORY / "adapters/solr/graphchecker_port/native_original"
COMMUNICATION_MAPPINGS = NATIVE_PROTOCOL / "communication-mappings.jsonl"
RUNNER = "edu.uva.liftlab.mallory.solr.NativeSolrJUnitRunner"
# One Solr-wide policy. The static GraphChecker-selected methods, not this
# list, determine which call sites become typed fault doors.
SOLR_IO_METHODS = [
    r"^<org\.apache\.solr\.client\.solrj\.(?:SolrClient|impl\.(?:Cloud)?Http2SolrClient|impl\.HttpSolrClient): .* (?:request|executeMethod)\(",
    r"^<org\.apache\.solr\.common\.cloud\.SolrZkClient: .* (?:getData|setData|create|delete|exists|getChildren|multi|sync)\(",
    r"^<org\.eclipse\.jetty\.client\.api\.Request: .* send\(",
]
SIDECARS = ("candidate_dataflow_edges.jsonl.gz", "static_scope_map.jsonl",
            "region_skeletons.jsonl.gz")


def region_plan_path(recorded: Path) -> Path:
    """Accept the current compressed Recorder plan and older plaintext runs."""
    compressed = recorded / "concolic_region_plan.jsonl.gz"
    return compressed if compressed.is_file() else recorded / "concolic_region_plan.jsonl"


def sha256(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            hash_.update(block)
    return hash_.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".native-solr-prep-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise FileExistsError(f"pinned output differs: {path}")
    finally:
        temporary.unlink(missing_ok=True)


def emit_json(path: Path, value: dict) -> None:
    write_once(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def emit_script(path: Path, argv: list[str], env: dict[str, str] | None = None) -> None:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    lines += [f"export {name}={shlex.quote(value)}" for name, value in (env or {}).items()]
    lines.append(" ".join(map(shlex.quote, argv)))
    write_once(path, ("\n".join(lines) + "\n").encode())
    path.chmod(0o755)


def verified_eligibility_supersession(row: dict, inventory: Path,
                                      state_root: Path | None) -> dict | None:
    """Use the queue's exact verifier to reopen a source-only skipped test.

    This is admission to a fresh native healthy run, never a substitute for
    that run or for the generated GraphChecker scope.
    """
    if row.get("eligibility", {}).get("may_dispatch_healthy_seed"):
        return None
    if (state_root is None or not state_root.is_absolute() or
            state_root.is_symlink() or not state_root.is_dir()):
        raise ValueError("skipped original JUnit requires an explicit eligibility state root")
    from Mallory.native_graphchecker_queue.results import (
        _eligibility_note, _eligibility_supersession,
    )
    old = _eligibility_note(row, inventory, state_root)
    current = _eligibility_supersession(row, state_root, old)
    if old is None or current is None:
        raise ValueError("skipped original JUnit lacks a verified healthy supersession")
    return {"path": current["preparation_review_path"],
            "sha256": current["preparation_review_sha256"],
            "old_note_path": old["preparation_note_pin_path"],
            "old_note_sha256": old["preparation_note_pin_sha256"],
            "inventory_sha256": sha256(inventory)}


def inventory_row(case_id: str, inventory: Path = INVENTORY,
                  eligibility_state_root: Path | None = None) -> dict:
    rows = [row for row in read_json(inventory)["cases"]
            if row.get("case_id") == case_id and row.get("system") == "solr"]
    if len(rows) != 1:
        raise ValueError(f"expected one Solr inventory row: {case_id}")
    row = rows[0]
    verified_eligibility_supersession(row, inventory, eligibility_state_root)
    selector = row["workload"]["selected_selector"]
    matches = [candidate for candidate in row["workload"]["candidates"]
               if candidate.get("selector") == selector and
               candidate.get("source_path") == row["workload"]["test_source_path"]]
    if len(matches) != 1 or not matches[0].get("source_sha256"):
        raise ValueError(f"selected original JUnit lacks one source receipt: {selector}")
    return row


def require_static_eligibility_pin(row: dict, inventory: Path,
                                   state_root: Path | None,
                                   static_input_path: Path) -> dict | None:
    """Keep the verified eligibility receipt identical across all phases."""
    proof = verified_eligibility_supersession(row, inventory, state_root)
    if proof is not None:
        receipt_path = static_input_path.parent / "source-receipt.json"
        receipt = read_json(receipt_path)
        if (receipt.get("case_id") != row["case_id"] or
                receipt.get("selected_junit") != row["workload"]["selected_selector"] or
                receipt.get("eligibility_supersession") != proof):
            raise ValueError("static eligibility supersession pin differs")
    return proof


def target_from_inventory(row: dict) -> dict:
    target = row["target"]
    owner, method = target["function"].split("(", 1)[0].rsplit(".", 1)
    check_sites = target["runtime_mapping"]["check_sites"]
    lines = {int(match.group(1)) for site in check_sites
             for match in re.finditer(r"@(\d+):branch(?::\d+)?$", site)}
    if len(lines) != 1 or not target["runtime_mapping"].get("throw_site"):
        raise ValueError(f"target branch/throw is not unique: {row['case_id']}")
    return {"class": owner, "method": method, "line": lines.pop(),
            "throw_line": int(target["source_line"]), "kind": "BRANCH",
            "exception": target["target_exception"]}


def original_junit_jvm_args(row: dict) -> list[str]:
    """Enable an inventoried inherited @AwaitsFix on the original test."""
    selected = next(candidate for candidate in row["workload"]["candidates"]
                    if candidate["selector"] == row["workload"]["selected_selector"])
    return (["-Dtests.awaitsfix=true"]
            if selected.get("inherited_awaits_fix_sources") else [])


def attest_source(row: dict, source: Path) -> dict:
    target = row["target"]
    workload = row["workload"]
    selected = next(candidate for candidate in workload["candidates"]
                    if candidate.get("selector") == workload["selected_selector"]
                    and candidate.get("source_path") == workload["test_source_path"])
    files = {target["source_path"]: target["source_sha256"],
             workload["test_source_path"]: selected["source_sha256"]}
    for rel, expected in files.items():
        path = source / rel
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"inventoried original source differs: {rel}")
    return {"source_commit": row["provenance"]["source_commit"],
            "source_files_sha256": files}


def attest_native_protocol(row: dict, source: Path, receipt_path: Path,
                           patch_path: Path) -> dict:
    receipt = read_json(receipt_path)
    if (receipt.get("source_commit") != row["provenance"]["source_commit"] or
            receipt.get("patch_sha256") != sha256(patch_path)):
        raise ValueError("native Solr protocol patch/source pin differs")
    for rel, expected in receipt.get("patched_source_sha256", {}).items():
        path = source / rel
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"native Solr protocol source differs: {rel}")
    if not receipt.get("patched_source_sha256"):
        raise ValueError("native Solr protocol receipt has no patched sources")
    return {"native_protocol_receipt_sha256": sha256(receipt_path),
            "native_protocol_patch_sha256": receipt["patch_sha256"]}


def read_classpath(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").strip()
    entries = text.split(os.pathsep)
    if not text or any(not part or not Path(part).is_absolute() for part in entries):
        raise ValueError("ordered classpath must contain absolute entries")
    if len(set(entries)) != len(entries):
        raise ValueError("ordered classpath contains duplicate entries")
    return entries


def class_in(entries: list[str], clazz: str) -> bool:
    return class_artifact(entries, clazz) is not None


def class_artifact(entries: list[str], clazz: str) -> dict | None:
    """Fingerprint the first class that the ordered runtime classpath loads."""
    relative = clazz.replace(".", "/") + ".class"
    for item in entries:
        path = Path(item)
        if path.is_dir() and (path / relative).is_file():
            return {"origin": item, "sha256": sha256(path / relative)}
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                try:
                    body = archive.read(relative)
                except KeyError:
                    continue
                return {"origin": item, "sha256": hashlib.sha256(body).hexdigest()}
    return None


def static_input(row: dict, class_tree: Path, ordered: list[str], original_out: Path) -> dict:
    if ordered[0] != str(class_tree):
        raise ValueError("class tree must be first in the exact ordered classpath")
    target = target_from_inventory(row)
    if not (class_tree / (target["class"].replace(".", "/") + ".class")).is_file():
        raise ValueError("target class is absent from the selected process tree")
    junit_class = class_artifact(ordered, row["workload"]["test_class"])
    if junit_class is None:
        raise ValueError("selected original JUnit class is absent from classpath")
    target_class = class_artifact(ordered, target["class"])
    return {"case_id": row["case_id"], "target": target,
            "compiled_classes": {"target": target_class, "junit": junit_class},
            "analysis": {"process_dirs": [str(class_tree)], "classpath": ordered,
                         "original_graphchecker_seed": True,
                         "original_loop_default_bound": "3",
                         "original_typed_io_frontier": True,
                         "original_engine_output_dir": str(original_out),
                         "io_door_mappings": SOLR_IO_METHODS}}


def validate_static(row: dict, static_input_path: Path, static_output: Path,
                    sidecars: Path) -> dict:
    config = read_json(static_input_path)
    if config.get("case_id") != row["case_id"] or config.get("target") != target_from_inventory(row):
        raise ValueError("static input target differs from inventory")
    analysis = config.get("analysis", {})
    if (analysis.get("original_graphchecker_seed") is not True or
            analysis.get("original_typed_io_frontier") is not True):
        raise ValueError("static input did not request original GraphChecker selection")
    if "compiled_classes" in config:
        ordered = analysis.get("classpath", [])
        target = target_from_inventory(row)
        expected = config["compiled_classes"]
        actual = {"target": class_artifact(ordered, target["class"]),
                  "junit": class_artifact(ordered, row["workload"]["test_class"])}
        if expected != actual or any(value is None for value in actual.values()):
            raise ValueError("compiled target or JUnit class differs from static input")
    manifest_path = static_output / "weave_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("caseId") != row["case_id"]:
        raise ValueError("static manifest belongs to another case")
    target = target_from_inventory(row)
    branch = [site for site in manifest.get("targets", []) if site.get("kind") == "BRANCH"
              and site.get("clazz") == target["class"] and site.get("method") == target["method"]
              and site.get("line") == target["line"]]
    throw = [site for site in manifest.get("targets", []) if site.get("kind") == "THROW"
             and site.get("clazz") == target["class"] and site.get("method") == target["method"]
             and site.get("line") == target["throw_line"]
             and site.get("exceptionClass") == target["exception"]]
    if len(branch) != 1 or len(throw) != 1 or branch[0]["siteId"] == throw[0]["siteId"]:
        raise ValueError("static target branch/throw does not resolve uniquely")
    doors = manifest.get("doors", [])
    if not doors or any(not door.get("siteId") or not door.get("exceptionClass") for door in doors):
        raise ValueError("static manifest has no complete typed fault doors")
    if len({(door["siteId"], door["exceptionClass"]) for door in doors}) != len(doors):
        raise ValueError("static typed fault doors are duplicated")
    if not manifest.get("regions") or not manifest.get("coverage"):
        raise ValueError("original static region or coverage set is empty")
    sidecar_hashes = {}
    for name in SIDECARS:
        path = sidecars / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"missing original GraphChecker sidecar: {path}")
        sidecar_hashes[name] = sha256(path)
    return {"target_site": branch[0]["siteId"],
            "target_throw": {"siteId": throw[0]["siteId"],
                             "exceptionClass": target["exception"]},
            "typed_fault_doors": len(doors), "regions": len(manifest["regions"]),
            "coverage_sites": len(manifest["coverage"]),
            "manifest_sha256": sha256(manifest_path), "sidecars_sha256": sidecar_hashes}


def validate_recording(trace_dir: Path, target_site: str) -> dict:
    manifest_path = trace_dir / "streaming_trace_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "CLOSED":
        raise ValueError("healthy original REGION_STATE trace is not closed")
    checks = 0
    trace = trace_dir / "runtime_trace.jsonl"
    with trace.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("event") == "BRANCH" and row.get("siteId") == target_site:
                checks += 1
    if not checks:
        raise ValueError("unchanged JUnit did not reach target branch")
    return {"target_checks": checks, "trace_manifest_sha256": sha256(manifest_path)}


def validate_junit_result(path: Path) -> str:
    pattern = re.compile(r"^NATIVE_SOLR_JUNIT_RESULT run=(\d+) failures=(\d+) "
                         r"ignored=(\d+) expected=(\d+)$")
    matches = [pattern.fullmatch(line) for line in
               path.read_text(encoding="utf-8").splitlines()
               if line.startswith("NATIVE_SOLR_JUNIT_RESULT")]
    if (len(matches) != 1 or matches[0] is None or
            int(matches[0].group(1)) < 1 or
            int(matches[0].group(1)) != int(matches[0].group(4)) or
            int(matches[0].group(2)) != 0 or int(matches[0].group(3)) != 0):
        raise ValueError("original JUnit run count/failure receipt is invalid")
    return sha256(path)


def validate_schedule(index_path: Path, plan_path: Path) -> dict:
    index = read_json(index_path)
    targets = [row for row in index.get("members", [])
               if row.get("role") == "TARGET" and row.get("targetReachGoal") is True]
    if len(targets) != 1 or not targets[0].get("taskId"):
        raise ValueError("original Recorder/Scheduler has no unique target task")
    task_id = targets[0]["taskId"]
    with plan_path.open(encoding="utf-8") as stream:
        if not any(json.loads(line).get("taskId") == task_id for line in stream):
            raise ValueError("original Scheduler target task is absent from plan")
    return {"target_task_id": task_id, "schedule_index_sha256": sha256(index_path),
            "schedule_plan_sha256": sha256(plan_path)}


def prepare_scope(args: argparse.Namespace) -> dict:
    state_root = getattr(args, "eligibility_state_root", None)
    row = inventory_row(args.case_id, args.inventory, state_root)
    eligibility = verified_eligibility_supersession(row, args.inventory, state_root)
    source = args.source.resolve(strict=True)
    proof = attest_source(row, source)
    proof.update(attest_native_protocol(row, source, args.protocol_receipt,
                                        args.protocol_patch))
    class_tree = args.class_tree.resolve(strict=True)
    ordered = read_classpath(args.classpath_file)
    for entry in ordered:
        if not Path(entry).exists():
            raise FileNotFoundError(entry)
    output = args.output.resolve()
    scope = static_input(row, class_tree, ordered, output / "original")
    planner = args.planner_jar.resolve(strict=True)
    deps = args.planner_deps.read_text().strip()
    if not deps:
        raise ValueError("empty static planner dependency classpath")
    emit_json(output / "static-input.json", scope)
    mapping = args.communication_mappings.resolve(strict=True)
    emit_json(output / "source-receipt.json", {"case_id": row["case_id"],
              **proof, "selected_junit": row["workload"]["selected_selector"],
              **({"eligibility_supersession": eligibility} if eligibility else {}),
              "planner_jar_sha256": sha256(planner),
              "planner_dependencies_sha256": sha256(args.planner_deps),
              "ordered_classpath_sha256": sha256(args.classpath_file),
              "communication_mappings_sha256": sha256(mapping)})
    java_args = [str(args.java), "-Xmx8g",
                 "-Dcausynth.communication.mappings=" + str(mapping)]
    emit_script(output / "run_static.sh", [*java_args, "-cp",
                str(planner) + os.pathsep + deps,
                "edu.uva.liftlab.mallory.scope.ScopePlanner",
                str(output / "static-input.json"), str(output / "static")])
    return {"case_id": row["case_id"], "phase": "static_prepared",
            "target": scope["target"], "output": str(output)}


def prepare_weave(args: argparse.Namespace) -> dict:
    state_root = getattr(args, "eligibility_state_root", None)
    row = inventory_row(args.case_id, args.inventory, state_root)
    source_root = args.source.resolve(strict=True)
    source_proof = attest_source(row, source_root)
    source_proof.update(attest_native_protocol(row, source_root,
                                               args.protocol_receipt,
                                               args.protocol_patch))
    static_path = args.static_input.resolve(strict=True)
    require_static_eligibility_pin(row, args.inventory, state_root, static_path)
    static_output = args.static_output.resolve(strict=True)
    sidecars = args.sidecars.resolve(strict=True)
    receipt = validate_static(row, static_path, static_output, sidecars)
    config = read_json(static_path)
    classes = Path(config["analysis"]["process_dirs"][0])
    ordered = config["analysis"]["classpath"]
    if ordered[0] != str(classes) or not classes.is_dir():
        raise ValueError("static class tree is no longer available")
    adapter = args.adapter_jar.resolve(strict=True)
    engine_root = args.engine_root.resolve(strict=True)
    engine_jar = engine_root / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
    engine_deps = engine_root / "target/native-original-dependencies.txt"
    if not engine_jar.is_file():
        raise FileNotFoundError(engine_jar)
    if not engine_deps.is_file() or not engine_deps.read_text().strip():
        raise FileNotFoundError(engine_deps)
    output = args.output.resolve()
    runner_cp = read_classpath(args.runner_classpath_file)
    if (runner_cp[0] != str(output / "woven") or
            not class_in(runner_cp[1:], RUNNER) or
            not class_in(runner_cp[1:], row["workload"]["test_class"])):
        raise ValueError("healthy classpath must start with woven classes and include original runner/JUnit")
    artifacts = output / "recording-artifacts"
    for name in SIDECARS:
        source = sidecars / name
        destination = artifacts / name
        if destination.exists() and sha256(destination) != receipt["sidecars_sha256"][name]:
            raise FileExistsError(f"recording sidecar differs: {destination}")
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    weave = {"weave_mode": "region_state", "java": str(args.java),
             "jvm_args": ["-Xmx12g"], "input_classes": str(classes),
             "output_classes": str(output / "woven"),
             "dependency_classpath": os.pathsep.join(ordered[1:]),
             "tool_classpath": str(adapter),
             "native_fault_manifest": str(static_output / "weave_manifest.json"),
             "recording_artifacts": str(artifacts),
             "region_skeletons": str(artifacts / "region_skeletons.jsonl.gz"),
             "timeout_seconds": args.timeout}
    mapping = args.communication_mappings.resolve(strict=True)
    weave["communication_mappings"] = str(mapping)
    emit_json(output / "native-weave-config.json", weave)
    emit_json(output / "static-receipt.json", {"case_id": row["case_id"], **receipt,
              "source": source_proof,
              "adapter_jar_sha256": sha256(adapter),
              "original_engine_jar_sha256": sha256(engine_jar),
              "communication_mappings_sha256": sha256(mapping),
              "runner_classpath_sha256": sha256(args.runner_classpath_file)})
    emit_script(output / "run_region_state_weave.sh", ["python3", str(NATIVE_WEAVER),
                "--config", str(output / "native-weave-config.json")],
                {"MALLORY_NATIVE_ENGINE_ROOT": str(engine_root)})
    healthy = output / "healthy"
    test_home = source_root / "solr" / row["workload"]["test_source_path"].split("/")[1]
    emit_json(healthy / "no-fault-plan.json", {"faults": []})
    environment = {"MALLORY_NATIVE_FAULT_PLAN": str(healthy / "no-fault-plan.json"),
                   "MALLORY_NATIVE_FAULT_EVENTS": str(healthy / "fault-events.jsonl"),
                   "CAUSYNTH_CONCOLIC_SESSIONS": str(healthy / "sessions"),
                   "CAUSYNTH_TRACE_OUTPUT_DIR": str(healthy / "trace"),
                   "CAUSYNTH_STATIC_SCOPE_MAP": str(artifacts / "static_scope_map.jsonl"),
                   "CAUSYNTH_TRACE_TEST": row["workload"]["selected_selector"]}
    command = [str(args.java), "-ea", "-Xmx6g",
               "-Dcausynth.cluster.automatic=true",
               "-Dcausynth.trace.mode=region-state",
               "-Dcausynth.trace.test=" + row["workload"]["selected_selector"],
               "-Dtests.luceneMatchVersion=8.11.4",
               "-Djava.io.tmpdir=" + str(healthy / "tmp"),
               "-Dsolr.log.dir=" + str(healthy / "tmp"),
               "-Dtest.solr.allowed.securerandom=NativePRNG",
               "-Dtests.src.home=" + str(test_home),
               *original_junit_jvm_args(row),
               "-cp", os.pathsep.join(runner_cp), RUNNER,
               row["workload"]["test_class"], row["workload"]["test_method"]]
    script = ["#!/usr/bin/env bash", "set -euo pipefail",
              "mkdir -p " + " ".join(shlex.quote(str(healthy / name))
                                      for name in ("tmp", "sessions", "trace")),
              "cd " + shlex.quote(str(healthy / "tmp"))]
    script += [f"export {key}={shlex.quote(value)}" for key, value in environment.items()]
    script += [" ".join(map(shlex.quote, command)) + " >" +
               shlex.quote(str(healthy / "junit.stdout.log")) + " 2>" +
               shlex.quote(str(healthy / "junit.stderr.log"))]
    script_path = output / "run_healthy_original_junit.sh"
    write_once(script_path, ("\n".join(script) + "\n").encode())
    script_path.chmod(0o755)
    original_cp = str(engine_jar) + os.pathsep + engine_deps.read_text().strip()
    target_arg = row["case_id"].replace("-", "") + "=" + ",".join(
        str(artifacts / name) for name in SIDECARS if name != "region_skeletons.jsonl.gz")
    target_arg += ("," + str(artifacts / "region_skeletons.jsonl.gz") +
                   "," + str(healthy / "recorded"))
    analysis_heap = f"-Xmx{args.analysis_heap_mb}m"
    recorder = [str(args.java), analysis_heap, "-Dcausynth.loop.default.bound=3",
                "-cp", original_cp,
                "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
                "--trace-dir", str(healthy / "trace"), "--test",
                row["workload"]["selected_selector"], "--target", target_arg,
                "--target-occurrence", "first"]
    scheduler = [str(args.java), analysis_heap, "-Dcausynth.loop.default.bound=3",
                 "-cp", original_cp,
                 "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
                 "--region-plan", str(region_plan_path(healthy / "recorded")),
                 "--candidate-graph", str(artifacts / "candidate_dataflow_edges.jsonl.gz"),
                 "--static-scope-map", str(artifacts / "static_scope_map.jsonl"),
                 "--output-dir", str(healthy / "scheduled"),
                 "--max-jobs", str(args.max_jobs), "--target-occurrence", "first"]
    plan_path = output / "run_original_recorder_scheduler.sh"
    command_runner = MALLORY / "native_graphchecker_campaign/record_command.py"
    recorder_receipt = healthy / "recorder-command.json"
    scheduler_receipt = healthy / "scheduler-command.json"

    def executed(command: list[str], stage: str, receipt: Path) -> str:
        runner = [sys.executable, str(command_runner),
                  "--script", str(plan_path), "--receipt", str(receipt),
                  "--stdout", str(healthy / f"{stage}.stdout.log"),
                  "--stderr", str(healthy / f"{stage}.stderr.log"),
                  "--", *command]
        return " ".join(map(shlex.quote, runner))

    plan_script = ["#!/usr/bin/env bash", "set -euo pipefail",
                   "mkdir -p " + " ".join(shlex.quote(str(healthy / name))
                                           for name in ("recorded", "scheduled")),
                   "rm -f " + " ".join(map(shlex.quote,
                                          (str(recorder_receipt), str(scheduler_receipt)))),
                   executed(recorder, "recorder", recorder_receipt),
                   executed(scheduler, "scheduler", scheduler_receipt)]
    write_once(plan_path, ("\n".join(plan_script) + "\n").encode())
    plan_path.chmod(0o755)
    return {"case_id": row["case_id"], "phase": "region_state_prepared",
            "typed_fault_doors": receipt["typed_fault_doors"], "output": str(output)}


def bind_executed_schedule(campaign: dict, trace_dir: Path,
                           schedule_index: Path, schedule_plan: Path,
                           engine_jar: Path) -> bool:
    """Seal only a successful original Solr plan from this exact preparation."""
    healthy_root = trace_dir.resolve(strict=True).parent
    recorder_receipt = healthy_root / "recorder-command.json"
    scheduler_receipt = healthy_root / "scheduler-command.json"
    if not recorder_receipt.exists() and not scheduler_receipt.exists():
        return False
    from Mallory.native_graphchecker_campaign import campaign as native

    script = healthy_root.parent / "run_original_recorder_scheduler.sh"
    command_runner = MALLORY / "native_graphchecker_campaign/record_command.py"
    for receipt, stage in ((recorder_receipt, "recorder"),
                           (scheduler_receipt, "scheduler")):
        evidence = read_json(receipt)
        if (evidence.get("schema_version") != 1 or
                evidence.get("returncode") != 0 or
                evidence.get("script") != str(script.resolve(strict=True)) or
                evidence.get("script_sha256") != sha256(script) or
                evidence.get("command_runner_sha256") != sha256(command_runner) or
                evidence.get("stdout_sha256") != sha256(healthy_root /
                                                        f"{stage}.stdout.log") or
                evidence.get("stderr_sha256") != sha256(healthy_root /
                                                        f"{stage}.stderr.log")):
            raise ValueError("original Solr command execution receipt changed")
    if (schedule_index.resolve(strict=True) !=
            healthy_root / "scheduled/runtime_workflow_schedule_index.json" or
            schedule_plan.resolve(strict=True) !=
            healthy_root / "scheduled/execution_task_plan.jsonl"):
        raise ValueError("original Solr schedule is outside recorded preparation")
    if native.JAR.resolve(strict=True) != engine_jar.resolve(strict=True):
        raise ValueError("original Solr preparation and campaign engine differ")
    receipt = healthy_root / "precomputed-schedule.json"
    native.seal_precomputed_schedule(
        campaign, healthy_root / "recorded", healthy_root / "scheduled",
        recorder_receipt, scheduler_receipt, receipt)
    campaign["recording"]["precomputed_schedule"] = str(receipt)
    return True


def prepare_campaign(args: argparse.Namespace) -> dict:
    state_root = getattr(args, "eligibility_state_root", None)
    row = inventory_row(args.case_id, args.inventory, state_root)
    require_static_eligibility_pin(row, args.inventory, state_root,
                                   args.static_input.resolve(strict=True))
    source = args.source.resolve(strict=True)
    source_proof = attest_source(row, source)
    source_proof.update(attest_native_protocol(row, source,
                                               args.protocol_receipt,
                                               args.protocol_patch))
    static = validate_static(row, args.static_input.resolve(strict=True),
                             args.static_output.resolve(strict=True),
                             args.sidecars.resolve(strict=True))
    healthy = validate_recording(args.trace_dir.resolve(strict=True), static["target_site"])
    healthy["junit_result_sha256"] = validate_junit_result(args.junit_result_log.resolve(strict=True))
    admission_mode = getattr(args, "admission_mode", "scheduled")
    if admission_mode == "scheduled":
        if args.schedule_index is None or args.schedule_plan is None:
            raise ValueError("scheduled admission requires original Scheduler outputs")
        schedule = validate_schedule(args.schedule_index.resolve(strict=True),
                                     args.schedule_plan.resolve(strict=True))
    elif admission_mode == "region_state_no_schedule":
        if args.schedule_index is not None or args.schedule_plan is not None:
            raise ValueError("no-schedule admission must not bind a task plan")
        schedule = {"admission_mode": admission_mode}
    else:
        raise ValueError("unknown original recording admission mode")
    weave_path = args.weave_config.resolve(strict=True)
    weave = read_json(weave_path)
    engine_root = args.engine_root.resolve(strict=True)
    engine_jar = engine_root / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
    if not engine_jar.is_file():
        raise FileNotFoundError(engine_jar)
    if (weave.get("weave_mode") != "region_state" or
            Path(weave.get("native_fault_manifest", "")).resolve() !=
            (args.static_output.resolve(strict=True) / "weave_manifest.json") or
            Path(weave.get("region_skeletons", "")).resolve() !=
            (args.sidecars.resolve(strict=True) / "region_skeletons.jsonl.gz")):
        raise ValueError("REGION_STATE weave does not bind the selected static artifacts")
    if admission_mode == "region_state_no_schedule" and (
            weave.get("task_plan") or weave.get("task_id")):
        raise ValueError("no-schedule admission requires a task-free REGION_STATE weave")
    woven = Path(weave["output_classes"]).resolve(strict=True)
    if not (woven / "native-original-weave-receipt.json").is_file():
        raise ValueError("original REGION_STATE weave receipt is absent")
    runner_cp = read_classpath(args.runner_classpath_file)
    if runner_cp[0] != str(woven) or not class_in(runner_cp, RUNNER):
        raise ValueError("runtime classpath omits woven classes or native Solr runner")
    if not class_in(runner_cp, row["workload"]["test_class"]):
        raise ValueError("runtime classpath omits original JUnit class")
    module = row["workload"]["test_source_path"].split("/")[1]
    test_home = source / "solr" / module
    output = args.output.resolve()
    campaign = {"case_id": row["case_id"], "target_site": static["target_site"],
                "target_throw": static["target_throw"], "target_actor_names": [],
                "native_weave_config": str(weave_path),
                "recording": {"trace_dir": str(args.trace_dir.resolve(strict=True)),
                              "test_id": row["workload"]["selected_selector"],
                              "target_name": row["case_id"].replace("-", ""),
                              "candidate_graph": str(args.sidecars.resolve(strict=True) /
                                                     "candidate_dataflow_edges.jsonl.gz"),
                              "static_scope_map": str(args.sidecars.resolve(strict=True) /
                                                      "static_scope_map.jsonl"),
                              "region_skeletons": str(args.sidecars.resolve(strict=True) /
                                                      "region_skeletons.jsonl.gz"),
                              "max_jobs": args.max_jobs,
                              "graph_analysis_heap_mb": args.analysis_heap_mb,
                              "target_occurrence": "first",
                              "recorder_jvm_args": ["-Dcausynth.loop.default.bound=3"],
                              "scheduler_jvm_args": ["-Dcausynth.loop.default.bound=3"]},
                "junit": {"class": row["workload"]["test_class"],
                          "method": row["workload"]["test_method"]},
                "runner": {"mode": "region_state", "zero_vm_java": str(args.java),
                           "main_class": RUNNER, "classpath": runner_cp,
                           "result_marker": "NATIVE_SOLR_JUNIT_RESULT",
                           "jvm_args": ["-ea", "-Xmx6g", "-Dcausynth.cluster.automatic=true",
                                        "-Dtests.luceneMatchVersion=8.11.4",
                                        "-Djava.io.tmpdir={trial_workdir}",
                                        "-Dsolr.log.dir={trial_workdir}",
                                        "-Dtest.solr.allowed.securerandom=NativePRNG",
                                        "-Dtests.src.home=" + str(test_home),
                                        *original_junit_jvm_args(row)],
                           "args_before_test": []},
                "budget": {"fault_trials": args.trials, "seconds": args.seconds,
                           "max_faults_per_trial": args.max_faults},
                "timeout_seconds": args.timeout}
    if admission_mode == "region_state_no_schedule":
        campaign["recording"]["admission_mode"] = admission_mode
    else:
        bind_executed_schedule(campaign, args.trace_dir,
                               args.schedule_index, args.schedule_plan,
                               engine_jar)
    emit_json(output / "campaign-config.json", campaign)
    emit_json(output / "preparation-receipt.json", {"case_id": row["case_id"],
              "selected_junit": row["workload"]["selected_selector"],
              "source": source_proof, "static": static, "healthy": healthy,
              "schedule": schedule, "weave_config_sha256": sha256(weave_path),
              "runner_classpath_sha256": sha256(args.runner_classpath_file),
              "original_engine_jar_sha256": sha256(engine_jar)})
    emit_script(output / "run_campaign.sh", ["python3", "-m",
                "Mallory.native_graphchecker_campaign", "--config",
                str(output / "campaign-config.json"), "--output",
                str(output / "campaign")],
                {"PYTHONPATH": str(MALLORY.parent),
                 "MALLORY_NATIVE_ENGINE_ROOT": str(engine_root)})
    return {"case_id": row["case_id"], "phase": "campaign_prepared",
            "target_checks": healthy["target_checks"],
            "typed_fault_doors": static["typed_fault_doors"], "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    for name in ("scope", "weave", "campaign"):
        part = sub.add_parser(name)
        part.add_argument("--case-id", required=True)
        part.add_argument("--inventory", type=Path, default=INVENTORY)
        part.add_argument("--output", required=True, type=Path)
        part.add_argument("--eligibility-state-root", type=Path,
                          help="queue state root with SHA-verified healthy supersession for a skipped JUnit")
    scope = sub.choices["scope"]
    scope.add_argument("--source", required=True, type=Path)
    scope.add_argument("--protocol-receipt", type=Path,
                       default=NATIVE_PROTOCOL / "source_receipt.json")
    scope.add_argument("--protocol-patch", type=Path,
                       default=NATIVE_PROTOCOL / "solr-e27f44e-original-engine.patch")
    scope.add_argument("--class-tree", required=True, type=Path)
    scope.add_argument("--classpath-file", required=True, type=Path)
    scope.add_argument("--planner-jar", required=True, type=Path)
    scope.add_argument("--planner-deps", required=True, type=Path)
    scope.add_argument("--java", required=True, type=Path)
    scope.add_argument("--communication-mappings", type=Path,
                       default=COMMUNICATION_MAPPINGS)
    for name in ("weave", "campaign"):
        part = sub.choices[name]
        part.add_argument("--static-input", required=True, type=Path)
        part.add_argument("--static-output", required=True, type=Path)
        part.add_argument("--sidecars", required=True, type=Path)
        part.add_argument("--java", required=True, type=Path)
        part.add_argument("--timeout", type=int, default=900 if name == "weave" else 300)
    weave = sub.choices["weave"]
    weave.add_argument("--source", required=True, type=Path)
    weave.add_argument("--protocol-receipt", type=Path,
                       default=NATIVE_PROTOCOL / "source_receipt.json")
    weave.add_argument("--protocol-patch", type=Path,
                       default=NATIVE_PROTOCOL / "solr-e27f44e-original-engine.patch")
    weave.add_argument("--runner-classpath-file", required=True, type=Path)
    weave.add_argument("--adapter-jar", required=True, type=Path)
    weave.add_argument("--engine-root", required=True, type=Path)
    weave.add_argument("--communication-mappings", type=Path,
                       default=COMMUNICATION_MAPPINGS)
    weave.add_argument("--max-jobs", type=int, default=256)
    weave.add_argument("--analysis-heap-mb", type=int, default=3072)
    campaign = sub.choices["campaign"]
    campaign.add_argument("--source", required=True, type=Path)
    campaign.add_argument("--protocol-receipt", type=Path,
                          default=NATIVE_PROTOCOL / "source_receipt.json")
    campaign.add_argument("--protocol-patch", type=Path,
                          default=NATIVE_PROTOCOL / "solr-e27f44e-original-engine.patch")
    campaign.add_argument("--trace-dir", required=True, type=Path)
    campaign.add_argument("--junit-result-log", required=True, type=Path)
    campaign.add_argument("--schedule-index", type=Path)
    campaign.add_argument("--schedule-plan", type=Path)
    campaign.add_argument("--admission-mode", choices=("scheduled", "region_state_no_schedule"),
                          default="scheduled")
    campaign.add_argument("--weave-config", required=True, type=Path)
    campaign.add_argument("--runner-classpath-file", required=True, type=Path)
    campaign.add_argument("--engine-root", required=True, type=Path)
    campaign.add_argument("--max-jobs", type=int, default=256)
    campaign.add_argument("--analysis-heap-mb", type=int, default=3072)
    campaign.add_argument("--trials", type=int, default=64)
    campaign.add_argument("--seconds", type=int, default=1800)
    campaign.add_argument("--max-faults", type=int, default=4)
    args = parser.parse_args()
    if args.phase == "weave" and min(args.timeout, args.max_jobs, args.analysis_heap_mb) <= 0:
        parser.error("weave timeout, max jobs, and analysis heap must be positive")
    if args.phase == "campaign" and min(args.timeout, args.max_jobs, args.analysis_heap_mb,
                                        args.trials,
                                        args.seconds, args.max_faults) <= 0:
        parser.error("campaign budget must be positive")
    action = {"scope": prepare_scope, "weave": prepare_weave,
              "campaign": prepare_campaign}[args.phase]
    print(json.dumps(action(args), sort_keys=True))


if __name__ == "__main__":
    main()
