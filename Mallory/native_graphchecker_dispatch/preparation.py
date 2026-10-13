"""Inventory-derived, pinned preparation queue for native GraphChecker cases.

System adapters implement one shared command protocol. The older Mallory
prepare_case scripts do not implement it and are never treated as native
adapters. No case-specific I/O list or fault door enters the request.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from Mallory.instrumentation.graphchecker_port.native_original_weave import (
    class_tree_digest, file_tree_digest, verify_engine,
)
from Mallory.native_graphchecker_campaign import campaign as native

from .checklist import (_object, _sha, load_inventory, load_ownership,
                        load_reviews)

SYSTEMS = ("hdfs", "hbase", "solr", "zookeeper")
MODE = "original_graphchecker_native_preparation"
ADAPTER_MODE = "original_graphchecker_native_adapter"
FORBIDDEN = re.compile(r"(?:^|[-_])(?:fault[-_]?sites?|io[-_]?points?|doors?)(?:$|[-_=])", re.I)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    import hashlib
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".native-prep-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".native-config-",
                                             dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            for block in iter(lambda: origin.read(1 << 20), b""):
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _start_ticks(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def _new_attempt(prep_root: Path, item: dict, request: dict,
                 recipe: dict, recipe_file: Path, cache_key: str) -> tuple[Path, dict]:
    attempt = prep_root / f"attempt-{uuid.uuid4().hex}"
    attempt.mkdir()
    _atomic(attempt / "request.json", request)
    _atomic(attempt / "recipe.json", recipe)
    state = {"schema_version": 1, "case_id": item["case_id"],
             "status": "running", "phase": "adapter",
             "request_sha256": _digest(request),
             "recipe_sha256": _sha(recipe_file),
             "cache_key": cache_key,
             "attempt": str(attempt), "started_at": time.time()}
    _atomic(prep_root / "state.json", state)
    return attempt, state


def load_recipes(path: Path, inventory: Path) -> dict[str, dict]:
    document = _object(path)
    if (document.get("schema_version") != 1 or
            document.get("inventory_sha256") != _sha(inventory) or
            not isinstance(document.get("systems"), dict) or
            set(document["systems"]) - set(SYSTEMS)):
        raise ValueError("native adapter recipe is not pinned to the inventory")
    for system, recipe in document["systems"].items():
        if not isinstance(recipe, dict):
            raise ValueError(f"invalid {system} native adapter recipe")
        argv, pins = recipe.get("argv"), recipe.get("pins")
        trees = recipe.get("class_tree_pins", {})
        sources = recipe.get("source_tree_pins")
        classpath = recipe.get("classpath_pins")
        mappings = recipe.get("mapping_pins")
        if (not isinstance(argv, list) or not argv or
                not all(isinstance(arg, str) and arg for arg in argv) or
                argv.count("{request}") != 1 or argv.count("{output}") != 1 or
                not isinstance(pins, dict) or not pins or
                not isinstance(trees, dict) or
                not isinstance(sources, dict) or not sources or
                not isinstance(classpath, dict) or not classpath or
                not isinstance(mappings, dict) or not mappings or
                not isinstance(recipe.get("timeout_seconds"), int) or
                not 1 <= recipe["timeout_seconds"] <= 86400 or
                any(FORBIDDEN.search(arg) for arg in argv)):
            raise ValueError(f"invalid {system} native adapter command")
        # The adapter is a shared system command. No case ID, target, I/O or
        # JUnit token can be smuggled through the recipe argv.
        if any("{" in arg or "}" in arg for arg in argv
               if arg not in ("{request}", "{output}")):
            raise ValueError(f"unknown {system} native adapter template token")
        for name, expected in pins.items():
            file = Path(name)
            if (not file.is_absolute() or not file.is_file() or file.is_symlink() or
                    _sha(file) != expected):
                raise ValueError(f"changed native adapter pin: {name}")
        for name, expected in trees.items():
            directory = Path(name)
            if (not directory.is_absolute() or not directory.is_dir() or
                    class_tree_digest(directory) != expected):
                raise ValueError(f"changed native adapter class tree: {name}")
        for label, entries in (("source tree", sources),
                               ("classpath", classpath),
                               ("mapping", mappings)):
            for name, expected in entries.items():
                path = Path(name)
                if not path.is_absolute() or path.is_symlink() or not (
                        path.is_file() or path.is_dir()):
                    raise ValueError(f"invalid native {label} pin: {name}")
                actual = _sha(path) if path.is_file() else file_tree_digest(path)
                if actual != expected:
                    raise ValueError(f"changed native {label} pin: {name}")
        absolute_inputs = [arg for arg in argv if Path(arg).is_absolute()
                           and Path(arg).is_file()]
        if any(arg not in pins for arg in absolute_inputs):
            raise ValueError(f"un-pinned absolute adapter input for {system}")
    return document["systems"]


def build_request(item: dict, inventory: Path) -> dict:
    """Only the target, original JUnit, and source/build identity are passed."""
    target, workload, build = item["target"], item["workload"], item.get("build", {})
    mapping = target.get("runtime_mapping", {})
    if (not isinstance(workload.get("test_class"), str) or
            not isinstance(workload.get("test_method"), str) or
            workload.get("selected_selector") !=
            f"{workload['test_class']}#{workload['test_method']}"):
        raise ValueError("inventory lacks an exact original JUnit selector")
    return {
        "schema_version": 1, "mode": MODE,
        "case_id": item["case_id"], "system": item["system"],
        "system_version": item["system_version"],
        "inventory_sha256": _sha(inventory),
        "inventory_row_sha256": _digest(item),
        "target": {
            "site_id": target["site_id"],
            "source_path": target["source_path"],
            "source_sha256": target.get("source_sha256"),
            "source_line": target["source_line"],
            "compiled_throw_source_line": mapping.get("selected_source_line"),
            "compiled_throw_site": mapping.get("throw_site"),
            "function": target["function"],
            "target_throw": target.get("target_throw"),
            "target_exception": target["target_exception"],
        },
        "original_junit": {
            "class": workload["test_class"],
            "method": workload["test_method"],
            "selector": workload["selected_selector"],
            "source_path": workload.get("test_source_path"),
        },
        "source_build": {
            "source_root": build.get("cwd"), "module": build.get("module"),
        },
    }


def verify_target_occurrence(proof: dict, config: dict, output: Path,
                             expected_throw_site: str) -> dict:
    """Accept only a reached original-runtime check selected from the healthy trace."""
    name = proof.get("target_occurrence_receipt_path")
    if not isinstance(name, str) or not name:
        raise ValueError("native adapter lacks observed target occurrence receipt")
    path = Path(name).resolve(strict=True)
    if not path.is_relative_to(output.resolve(strict=True)) or not path.is_file():
        raise ValueError("target occurrence receipt is outside native adapter output")
    if _sha(path) != proof.get("target_occurrence_receipt_sha256"):
        raise ValueError("target occurrence receipt bytes changed")
    receipt = _object(path)
    rec = config["recording"]
    anchor = config["target_site"]
    base_site = anchor if re.search(r"#u\d+$", anchor) else anchor.rsplit("#", 1)[0]
    selected = receipt.get("selectedOccurrenceAddress")
    seq = receipt.get("selectedEventSeq")
    call = receipt.get("selectedCallId")
    reached = receipt.get("reachedEvents")
    if (receipt.get("kind") != "MALLORY_OBSERVED_TARGET_OCCURRENCE" or
            receipt.get("test") != rec["test_id"] or
            receipt.get("checkSiteId") != base_site or
            config["target_throw"]["siteId"] != expected_throw_site or
            not isinstance(selected, str) or not selected or
            rec.get("target_occurrence") != selected or
            not isinstance(seq, int) or isinstance(seq, bool) or seq < 0 or
            not isinstance(call, int) or isinstance(call, bool) or call < 0 or
            not isinstance(reached, list) or not any(
                isinstance(row, dict) and row.get("eventSeq") == seq and
                row.get("callId") == call and
                row.get("occurrenceAddress") == selected for row in reached) or
            receipt.get("traceManifestSha256") != _sha(
                Path(rec["trace_dir"]) / "streaming_trace_manifest.json") or
            receipt.get("scopeMapSha256") != _sha(Path(rec["static_scope_map"])) or
            receipt.get("candidateGraphSha256") != _sha(
                Path(rec["candidate_graph"])) or
            receipt.get("regionSkeletonsSha256") != _sha(
                Path(rec["region_skeletons"]))):
        raise ValueError("original-runtime target occurrence does not match healthy recording")
    return receipt


def _validate_output(item: dict, request: dict, output: Path,
                     case_root: Path) -> tuple[Path, dict, dict]:
    proof_path = output / "adapter-proof.json"
    config_path = output / "case.json"
    proof, config = _object(proof_path), _object(config_path)
    junit = request["original_junit"]
    if (proof.get("schema_version") != 1 or proof.get("mode") != ADAPTER_MODE or
            proof.get("case_id") != item["case_id"] or
            proof.get("request_sha256") != _digest(request) or
            proof.get("original_cluster_junit_verified") is not True or
            proof.get("scope_generated_by_original_graphchecker") is not True or
            proof.get("recording_closed") is not True or
            proof.get("junit") != {"class": junit["class"],
                                   "method": junit["method"]} or
            not isinstance(proof.get("source_evidence_paths"), list) or
            not proof["source_evidence_paths"] or not all(
                isinstance(name, str) and Path(name).is_file()
                for name in proof["source_evidence_paths"])):
        raise ValueError("native adapter lacks original-cluster-JUnit evidence")
    native._validate_config(config)
    if (config["case_id"] != item["case_id"] or
            config["junit"] != {"class": junit["class"],
                                "method": junit["method"]} or
            config["recording"]["test_id"] != junit["selector"] or
            config["target_site"].split("#", 1)[0] != request["target"][
                "site_id"].split("#", 1)[0] or
            config["target_throw"]["exceptionClass"] != request["target"][
                "target_exception"]):
        raise ValueError("native adapter output changed inventory target/JUnit")
    verify_target_occurrence(proof, config, output, request["target"]["site_id"])
    scope_path = Path(proof.get("static_scope_receipt_path", ""))
    recording_path = Path(proof.get("recording_weave_receipt_path", ""))
    if not scope_path.is_file() or not recording_path.is_file():
        raise ValueError("native adapter lacks both static and recording weave receipts")
    scope = _object(scope_path)
    recording = _object(recording_path)
    rec = config["recording"]
    if (scope.get("schema_version") != 1 or
            scope.get("mode") != "original_graphchecker_static_scope" or
            scope.get("case_id") != item["case_id"] or
            scope.get("request_sha256") != _digest(request) or
            any(scope.get(key) != _sha(Path(rec[path_key]))
                for key, path_key in (
                    ("candidate_graph_sha256", "candidate_graph"),
                    ("static_scope_map_sha256", "static_scope_map"),
                    ("region_skeletons_sha256", "region_skeletons")))):
        raise ValueError("original GraphChecker static scope receipt differs")
    static_preimage = scope.get("process_classes_sha256")
    if (not isinstance(static_preimage, str) or
            not re.fullmatch(r"[0-9a-f]{64}", static_preimage) or
            not isinstance(scope.get("ordered_analysis_classpath_sha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}",
                             scope["ordered_analysis_classpath_sha256"])):
        raise ValueError("static Soot class tree or ordered classpath was not pinned")
    scope_input_path = Path(scope.get("scope_input_path", ""))
    analysis_path = Path(scope.get("analysis_path", ""))
    if (not scope_input_path.is_file() or
            _sha(scope_input_path) != scope.get("scope_input_sha256") or
            not analysis_path.is_file() or
            _sha(analysis_path) != scope.get("analysis_sha256") or
            scope.get("analysis_kind") != "original_graphchecker_seed_backward" or
            scope.get("engine_jar_sha256") != _sha(native.JAR)):
        raise ValueError("original GraphChecker static input/engine receipt differs")
    scope_input = _object(scope_input_path)
    analysis_report = _object(analysis_path)
    analysis = scope_input.get("analysis", {})
    process_path = Path(scope.get("process_classes_path", ""))
    classpath = analysis.get("classpath")
    if (analysis.get("original_graphchecker_seed") is not True or
            analysis.get("process_dirs") != [str(process_path)] or
            not isinstance(classpath, list) or not classpath or
            not all(isinstance(path, str) and Path(path).is_absolute()
                    for path in classpath) or
            hashlib.sha256(os.pathsep.join(classpath).encode()).hexdigest()
            != scope["ordered_analysis_classpath_sha256"] or
            analysis_report.get("analysisKind") != scope["analysis_kind"] or
            analysis_report.get("sootDependencyClasspathSha256") != scope[
                "ordered_analysis_classpath_sha256"] or
            class_tree_digest(process_path) != static_preimage):
        raise ValueError("static Soot process classes/classpath identity differs")
    if (recording.get("schema_version") != 1 or
            recording.get("mode") != "original_graphchecker_region_state_weave" or
            recording.get("case_id") != item["case_id"] or
            recording.get("request_sha256") != _digest(request) or
            recording.get("engine_jar_sha256") != _sha(native.JAR) or
            recording.get("input_classes_sha256") != static_preimage or
            recording.get("input_classes_sha256") != class_tree_digest(Path(
                recording["input_classes"])) or
            recording.get("output_classes_sha256") != class_tree_digest(Path(
                recording["output_classes"]))):
        raise ValueError("original GraphChecker REGION_STATE weave receipt differs")
    # _admit verifies original source-built weave, closed healthy recording,
    # and recording-derived scheduler tasks; it caches the proof for campaign.
    admitted = native._admit(config, case_root)
    if (not isinstance(admitted.get("origin"), dict) or
            not isinstance(admitted.get("weave_receipt"), dict)):
        raise ValueError("native original GraphChecker admission failed")
    if admitted["weave_receipt"].get("input_classes_sha256") != static_preimage:
        raise ValueError("concolic weave preimage differs from static Soot class tree")
    return config_path, config, proof


def _verify_pins_again(recipe_file: Path, inventory: Path,
                       system: str, expected: dict) -> dict:
    current = load_recipes(recipe_file, inventory).get(system)
    if current != expected:
        raise ValueError("native system adapter recipe changed during preparation")
    return verify_engine()


def _cache_key(request: dict, recipe: dict, engine: dict) -> str:
    """Identity of immutable Soot scope plus both original GraphChecker weaves.

    The recipe pins live source/classpath/mapping bytes, and the engine proof
    pins the source-built GraphChecker JAR and dependencies. The inventory row
    in request fixes the target check and exact original JUnit selector.
    """
    return _digest({"request": request, "recipe": recipe, "engine": engine})


def _input_pins(recipe: dict) -> list[dict[str, str]]:
    kinds = (("pins", "file"), ("mapping_pins", "file"),
             ("source_tree_pins", "tree"),
             ("classpath_pins", "file_or_tree"),
             ("class_tree_pins", "class_tree"))
    return sorted(({"path": path, "sha256": sha, "kind": kind}
                   for field, kind in kinds
                   for path, sha in recipe.get(field, {}).items()),
                  key=lambda row: (row["kind"], row["path"]))


def _execute_adapter(argv: list[str], request: Path, output: Path,
                     attempt: Path, timeout: int) -> int:
    command = [str(request) if arg == "{request}" else
               str(output) if arg == "{output}" else arg for arg in argv]
    output.mkdir(parents=True, exist_ok=True)
    with (attempt / "stdout.log").open("wb") as stdout, (
            attempt / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   cwd=attempt, start_new_session=True)
        _atomic(attempt / "process.json", {"pid": process.pid,
                                           "start_ticks": _start_ticks(process.pid),
                                           "argv": command})
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = process.returncode
        _atomic(attempt / "exit.json", {"return_code": code})
        return code


def _promote(item: dict, request: dict, recipe_file: Path, recipe: dict,
             attempt: Path, case_root: Path, config_root: Path) -> dict:
    engine = _verify_pins_again(recipe_file, Path(request["inventory_path"]),
                                item["system"], recipe)
    output = attempt / "output"
    source_config, config, proof = _validate_output(item, request, output, case_root)
    config_file = config_root / f"{item['case_id']}.json"
    receipt_file = config_root / f"{item['case_id']}.prep.json"
    if config_file.exists() and _sha(config_file) != _sha(source_config):
        raise ValueError("existing native campaign config cannot be replaced")
    if not config_file.exists():
        _atomic_copy(source_config, config_file)
    weave = _object(Path(config["native_weave_config"]))
    receipt = {
        "schema_version": 1, "mode": MODE, "case_id": item["case_id"],
        "inventory_row_sha256": _digest(item),
        "cache_key": _cache_key(request, recipe, engine),
        "input_pins": _input_pins(recipe),
        "recipe_file_path": str(recipe_file.resolve(strict=True)),
        "recipe_file_sha256": _sha(recipe_file),
        "engine_jar_path": str(native.JAR),
        "engine_jar_sha256": _sha(native.JAR),
        "request_path": str(attempt / "request.json"),
        "request_sha256": _sha(attempt / "request.json"),
        "recipe_snapshot_path": str(attempt / "recipe.json"),
        "recipe_snapshot_sha256": _sha(attempt / "recipe.json"),
        "adapter_proof_path": str(output / "adapter-proof.json"),
        "adapter_proof_sha256": _sha(output / "adapter-proof.json"),
        "static_scope_receipt_path": proof["static_scope_receipt_path"],
        "static_scope_receipt_sha256": _sha(Path(
            proof["static_scope_receipt_path"])),
        "recording_weave_receipt_path": proof["recording_weave_receipt_path"],
        "recording_weave_receipt_sha256": _sha(Path(
            proof["recording_weave_receipt_path"])),
        "target_occurrence_receipt_path": proof["target_occurrence_receipt_path"],
        "target_occurrence_receipt_sha256": _sha(Path(
            proof["target_occurrence_receipt_path"])),
        "source_config_path": str(source_config),
        "config_sha256": _sha(config_file),
        "recording_admission_sha256": _sha(case_root / "recording-admission.json"),
        "native_weave_receipt_sha256": _sha(
            Path(weave["output_classes"]) / "native-original-weave-receipt.json"),
        "original_cluster_junit_verified": proof["original_cluster_junit_verified"],
    }
    if receipt_file.exists() and _object(receipt_file) != receipt:
        raise ValueError("existing native preparation receipt cannot be replaced")
    if not receipt_file.exists():
        _atomic(receipt_file, receipt)
    return receipt


def prepare_one(item: dict, inventory: Path, recipe_file: Path, recipe: dict,
                config_root: Path, state_root: Path) -> dict:
    case_id = item["case_id"]
    case_root = state_root / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    prep_root = case_root / "preparation"
    prep_root.mkdir(exist_ok=True)
    with (prep_root / ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = prep_root / "state.json"
        request = build_request(item, inventory)
        request["inventory_path"] = str(inventory.resolve(strict=True))
        engine = _verify_pins_again(recipe_file, inventory, item["system"], recipe)
        cache_key = _cache_key(request, recipe, engine)
        if state_path.exists():
            state = _object(state_path)
            if (state.get("case_id") != case_id or
                    state.get("request_sha256") != _digest(request) or
                    state.get("recipe_sha256") != _sha(recipe_file) or
                    state.get("cache_key") != cache_key):
                raise ValueError("native preparation inputs changed; static scope and weaves are invalid")
            if state.get("status") == "complete":
                from .checklist import verify_preparation_receipt
                config_file = config_root / f"{case_id}.json"
                receipt = verify_preparation_receipt(item, config_file, case_root)
                if state.get("receipt_sha256") != _digest(receipt):
                    raise ValueError("native preparation state/receipt changed")
                # Revalidate the actual static scope, recording weave, and
                # original concolic weave; this does not run Soot or weave.
                _validate_output(item, request, Path(state["attempt"]) / "output",
                                 case_root)
                return state
            if state.get("status") == "failed":
                return state
            attempt = Path(state["attempt"])
            process_receipt = attempt / "process.json"
            exit_receipt = attempt / "exit.json"
            if process_receipt.is_file() and not exit_receipt.is_file():
                process = _object(process_receipt)
                pid = process.get("pid")
                current_ticks = _start_ticks(pid) if isinstance(pid, int) else None
                if current_ticks and (not process.get("start_ticks") or
                                      current_ticks == process["start_ticks"]):
                    raise RuntimeError(f"native adapter process is still running: {pid}")
                if not all((attempt / "output" / name).is_file() for name in
                           ("case.json", "adapter-proof.json")):
                    attempt, state = _new_attempt(
                        prep_root, item, request, recipe, recipe_file, cache_key)
        else:
            attempt, state = _new_attempt(prep_root, item, request,
                                          recipe, recipe_file, cache_key)
        if not (attempt / "exit.json").is_file():
            _verify_pins_again(recipe_file, inventory, item["system"], recipe)
            # A dead process with complete output can be verified and promoted
            # without repeating the expensive adapter command.
            if (attempt / "process.json").exists():
                code = 0
                _atomic(attempt / "exit.json", {
                    "return_code": 0, "recovered_from_closed_output": True})
            else:
                code = _execute_adapter(recipe["argv"], attempt / "request.json",
                                        attempt / "output", attempt,
                                        recipe["timeout_seconds"])
        else:
            code = _object(attempt / "exit.json").get("return_code")
        if code != 0:
            state.update(status="failed", phase="adapter", reason=f"adapter exit {code}")
            _atomic(state_path, state)
            return state
        try:
            receipt = _promote(item, request, recipe_file, recipe, attempt,
                               case_root, config_root)
        except (OSError, ValueError, KeyError, TypeError) as failure:
            state.update(status="failed", phase="verification", reason=str(failure))
            _atomic(state_path, state)
            return state
        state.update(status="complete", phase="promoted",
                     receipt=str(config_root / f"{case_id}.prep.json"),
                     receipt_sha256=_digest(receipt))
        _atomic(state_path, state)
        return state


def prepare_next(inventory: Path, ownership: Path, recipe_file: Path,
                 config_root: Path, state_root: Path, host: str,
                 reviews: Path | None = None) -> dict:
    """Prepare at most one native case on its owner host."""
    if host not in ("node0", "node1", "node2") or socket.gethostname().split(".")[0] != host:
        raise ValueError("prepare-next must execute on the physical owner host")
    cases, by_id = load_inventory(inventory)
    owners = load_ownership(ownership, set(by_id))
    no_junit = load_reviews(reviews, set(by_id))
    recipes = load_recipes(recipe_file, inventory)
    config_root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    with (state_root / f".host-{host}.prepare.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for item in cases:
            case_id = item["case_id"]
            if owners[case_id] != host or case_id in no_junit:
                continue
            recipe = recipes.get(item["system"])
            if recipe is None:
                continue
            from .checklist import inspect_case
            prep_state = state_root / case_id / "preparation/state.json"
            if prep_state.is_file() and _object(prep_state).get("status") == "complete":
                # Audit the content-addressed cache on every scheduling pass.
                # Same inputs reuse Soot scope, recording weave, and concolic
                # weave; changed inputs fail closed before any JUnit trial.
                prepare_one(item, inventory, recipe_file, recipe,
                            config_root, state_root)
                continue
            current = inspect_case(item, host, config_root, state_root)
            if (state_root / case_id / "checkpoint.json").exists():
                continue
            if current["terminal_disposition"] not in (
                    "needs_native_preparation", "native_preparing",
                    "receipt_error"):
                continue
            if (current["terminal_disposition"] == "receipt_error" and
                    not prep_state.is_file()):
                continue
            if prep_state.is_file() and _object(prep_state).get("status") in (
                    "failed",):
                continue
            return prepare_one(item, inventory, recipe_file, recipe,
                               config_root, state_root)
    return {"host": host, "status": "no_runnable_preparation"}
