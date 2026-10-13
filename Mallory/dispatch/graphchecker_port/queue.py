"""Resumable, one-case-at-a-time queue for native GraphChecker campaigns.

Each lane runs on its owner host. A lane recipe invokes the existing system
adapter, Soot planner, and native fuzzer; it contains no per-case I/O sites.
Dry run is read-only. The host lease and live-process guard protect campaigns
that were started outside this dispatcher.
"""

from __future__ import annotations

import argparse
import fcntl
import functools
import gzip
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Mallory.dispatch.graphchecker_port.import_case import import_case
from Mallory.dispatch.graphchecker_port.plan import CASE_ID, sha256


STEP_KINDS = {
    "hdfs": ("hdfs_scope", "scope_planner", "hdfs_campaign"),
    "hbase": ("hbase_prepare",),
    "solr": ("solr_scope", "solr_scope_planner", "solr_campaign"),
    "zookeeper": ("zookeeper_prepare",),
}
ADAPTER_SCRIPT = {
    "hdfs_scope": "prepare_case.py", "hdfs_campaign": "prepare_case.py",
    "hbase_prepare": "prepare_case.py", "solr_scope": "prepare_case.py",
    "solr_campaign": "prepare_case.py",
    "zookeeper_prepare": "prepare_zk_campaign.py",
}
COMPACT_PROPERTY = "-Dmallory.graphchecker.trace.compact=true"
COMPACT_CLASS = "edu/uva/liftlab/mallory/graphchecker/runtime/TraceRows.class"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
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


def _inside(relative: str) -> bool:
    path = Path(relative)
    return bool(relative) and relative != "." and not path.is_absolute() and ".." not in path.parts


def _render(value: str, case_id: str, prep: Path, inventory: Path) -> str:
    if not isinstance(value, str):
        raise ValueError("recipe argv must be strings")
    for token, replacement in (("{case_id}", case_id), ("{prep}", str(prep)),
                               ("{inventory}", str(inventory))):
        value = value.replace(token, replacement)
    if "{" in value or "}" in value:
        raise ValueError(f"unknown recipe token: {value}")
    return value


def _argv(step: dict, case_id: str, prep: Path, inventory: Path) -> list[str]:
    args = step.get("argv")
    if not isinstance(args, list) or not args:
        raise ValueError("recipe step needs nonempty argv")
    return [_render(value, case_id, prep, inventory) for value in args]


def _validate_step(step: dict, kind: str) -> None:
    if step.get("kind") != kind:
        raise ValueError(f"expected {kind} recipe step")
    args = step.get("argv")
    outputs = step.get("outputs")
    if (not isinstance(args, list) or not args or
            not isinstance(outputs, list) or not outputs or
            any(not isinstance(item, str) or not _inside(item) for item in outputs) or
            len(outputs) != len(set(outputs))):
        raise ValueError(f"invalid {kind} argv/outputs")
    rendered = " ".join(args)
    if re.search(r"--(?:doors?|fault[-_]?sites?|io[-_]?points?)\b|"
                 r"\b(?:door|fault.site|io.point)s?\s*(?:=|:)", rendered, re.I):
        raise ValueError("queue recipe cannot declare I/O or fault sites")
    if kind in ADAPTER_SCRIPT:
        if ADAPTER_SCRIPT[kind] not in rendered or "--case-id" not in args or "{case_id}" not in args:
            raise ValueError(f"{kind} must invoke its inventory-driven adapter")
    if kind == "hdfs_scope" and "scope-input" not in args:
        raise ValueError("HDFS scope phase missing")
    if kind == "hdfs_campaign" and "campaign-config" not in args:
        raise ValueError("HDFS campaign phase missing")
    if kind == "solr_scope" and "scope" not in args:
        raise ValueError("Solr scope phase missing")
    if kind == "solr_campaign" and "campaign" not in args:
        raise ValueError("Solr campaign phase missing")
    if kind == "scope_planner" and "ScopePlanner" not in rendered:
        raise ValueError("HDFS must run Soot ScopePlanner")
    if kind == "solr_scope_planner" and "{prep}/run_scope.sh" not in args:
        raise ValueError("Solr must run generated scope script")


def load_manifest(path: Path) -> tuple[dict, dict[str, dict], str]:
    path = path.resolve(strict=True)
    document = _object(path)
    if document.get("schema_version") != 1:
        raise ValueError("unsupported queue manifest schema")
    host, system = document.get("host"), document.get("system")
    if host not in ("node0", "node1", "node2") or system not in STEP_KINDS:
        raise ValueError("queue needs a known host and system")
    inventory = Path(document.get("inventory", ""))
    if (not inventory.is_absolute() or not inventory.is_file() or
            sha256(inventory) != document.get("inventory_sha256")):
        raise ValueError("queue inventory is not SHA-pinned")
    rows = _object(inventory).get("cases")
    if not isinstance(rows, list) or len(rows) != 102:
        raise ValueError("queue requires the 102-check inventory")
    by_id = {r.get("case_id"): r for r in rows if isinstance(r, dict)}
    if len(by_id) != 102 or any(not CASE_ID.fullmatch(str(case_id)) or
                                case_id.split("-", 1)[0].lower() != row.get("system")
                                for case_id, row in by_id.items()):
        raise ValueError("inventory has duplicate or invalid case IDs")
    selected = document.get("case_ids")
    if selected is None:
        selected = [r["case_id"] for r in rows if r.get("system") == system]
    if (not isinstance(selected, list) or not selected or
            len(set(selected)) != len(selected) or
            any(case_id not in by_id or by_id[case_id].get("system") != system
                for case_id in selected)):
        raise ValueError("queue case IDs must be unique inventory rows of one system")
    supported = document.get("adapter_supported_case_ids", selected)
    if (system == "zookeeper" and "adapter_supported_case_ids" not in document):
        raise ValueError("ZooKeeper preparer supports only five named cases; declare its supported IDs")
    if (not isinstance(supported, list) or len(set(supported)) != len(supported) or
            any(case_id not in selected for case_id in supported)):
        raise ValueError("adapter_supported_case_ids must be a unique selected-case subset")
    for field in ("state_root", "import_root"):
        root = Path(document.get(field, ""))
        if not root.is_absolute() or root == Path("/") or str(root).startswith("/dev/shm/"):
            raise ValueError(f"{field} must be an absolute durable path")
    recipe = document.get("recipe")
    if not isinstance(recipe, dict) or not _inside(recipe.get("config_relative", "")):
        raise ValueError("recipe needs a relative config path")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or tuple(s.get("kind") for s in steps) != STEP_KINDS[system]:
        raise ValueError(f"recipe must follow {system} adapter phases")
    for step, kind in zip(steps, STEP_KINDS[system]):
        _validate_step(step, kind)
    if document.get("compact_runtime_trace", False) not in (True, False):
        raise ValueError("compact_runtime_trace must be boolean")
    pins = document.get("pins")
    if not isinstance(pins, dict) or not pins:
        raise ValueError("queue needs SHA-pinned tool inputs")
    for name, digest in pins.items():
        item = Path(name)
        if (not item.is_absolute() or not item.is_file() or item.is_symlink() or
                not re.fullmatch(r"[0-9a-f]{64}", str(digest)) or sha256(item) != digest):
            raise ValueError(f"changed or unpinned tool file: {name}")
    for step in steps:
        for arg in step["argv"]:
            if "{" in arg:
                continue
            item = Path(arg)
            if (item.is_absolute() and item.is_file() and
                    item.suffix in (".py", ".jar", ".sh", ".json", ".txt") and
                    arg not in pins):
                raise ValueError(f"recipe input file lacks SHA pin: {arg}")
    external = document.get("existing_campaigns", {})
    if not isinstance(external, dict) or any(case_id not in selected or
            not isinstance(paths, dict) or not all(
                isinstance(paths.get(key), str) and Path(paths[key]).is_absolute()
                for key in ("config", "campaign"))
            for case_id, paths in external.items()):
        raise ValueError("invalid existing campaign map")
    reviews = document.get("no_suitable_junit", {})
    if not isinstance(reviews, dict) or any(case_id not in selected or
            not isinstance(review, dict) or not isinstance(review.get("reason"), str)
            or not review["reason"].strip() or
            not isinstance(review.get("evidence_paths"), list) or
            not review["evidence_paths"] or any(
                not isinstance(item, str) or not Path(item).is_file()
                for item in review["evidence_paths"])
            for case_id, review in reviews.items()):
        raise ValueError("no-suitable-JUnit review requires a reason and existing evidence")
    holds = document.get("holds", {})
    if not isinstance(holds, dict) or any(case_id not in selected or
            not isinstance(hold, dict) or not isinstance(hold.get("reason"), str)
            or not hold["reason"].strip() or
            not isinstance(hold.get("evidence_paths"), list) or
            not hold["evidence_paths"] or any(
                not isinstance(item, str) or not Path(item).is_file()
                for item in hold["evidence_paths"])
            for case_id, hold in holds.items()):
        raise ValueError("hold requires a reason and existing evidence")
    document["case_ids"] = selected
    document["adapter_supported_case_ids"] = supported
    return document, by_id, sha256(path)


def _eligible(row: dict) -> bool:
    work = row.get("workload", {})
    selector = work.get("selected_selector")
    return bool(isinstance(selector, str) and selector.count("#") == 1 and
                work.get("test_class") and work.get("test_method") and
                row.get("eligibility", {}).get("may_attempt_seed") and
                row.get("eligibility", {}).get("may_dispatch_healthy_seed"))


def _live_graph_jobs() -> list[dict]:
    """Read-only guard for existing pilots not owned by this queue."""
    jobs = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            args = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace")
        except (OSError, ProcessLookupError):
            continue
        if ("Mallory.core.graphchecker_fuzzer" in args or
                "edu.uva.liftlab.mallory.scope.ScopePlanner" in args):
            jobs.append({"pid": int(entry.name), "command": args[:300]})
    return jobs


def _case_files(root: Path, case_id: str) -> tuple[Path, Path]:
    case = root / case_id
    return case, case / "queue-state.json"


def _state(path: Path, case_id: str, manifest_sha: str) -> dict | None:
    if not path.exists():
        return None
    value = _object(path)
    if (value.get("schema_version") != 1 or value.get("case_id") != case_id or
            value.get("manifest_sha256") != manifest_sha or
            value.get("phase") not in ("preparing", "prepared", "running", "imported")):
        raise ValueError(f"unknown or changed queue state: {path}")
    return value


def _receipt(prep: Path, case_id: str, manifest_sha: str) -> dict:
    value = _object(prep / "prepare-receipt.json")
    if (value.get("schema_version") != 1 or value.get("case_id") != case_id or
            value.get("manifest_sha256") != manifest_sha):
        raise ValueError("prepared case identity changed")
    for relative, digest in value.get("outputs", {}).items():
        path = prep / relative
        if not _inside(relative) or not path.is_file() or path.is_symlink() or sha256(path) != digest:
            raise ValueError(f"prepared output changed: {path}")
    config = prep / value["config_relative"]
    if sha256(config) != value["config_sha256"]:
        raise ValueError("prepared native config changed")
    return value


def _external_state(paths: dict, case_id: str) -> str:
    config = Path(paths["config"])
    campaign = Path(paths["campaign"])
    if not config.is_file():
        return "blocked_missing_external_config"
    if not campaign.is_dir():
        return "blocked_missing_external_campaign"
    checkpoint = campaign / "checkpoint.json"
    if not checkpoint.is_file():
        return "external_waiting_checkpoint"
    item = _object(checkpoint)
    if item.get("case_id") != case_id or item.get("config_sha256") != sha256(config):
        return "blocked_external_identity"
    if item.get("terminal") is True:
        summary = campaign / "summary.json"
        if (not summary.is_file() or _object(summary).get("config_sha256") !=
                item["config_sha256"]):
            return "blocked_external_summary"
        return "external_terminal_import"
    if item.get("terminal") is False and item.get("status") == "running":
        if _healthy_target_attribution_gap(campaign, item):
            return "blocked_healthy_target_attribution"
        return "external_running"
    return "blocked_external_checkpoint"


def _core_lock_held(campaign: Path) -> bool:
    lock = campaign / ".campaign.lock"
    if not lock.is_file():
        return False
    with lock.open("rb") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
    return False


def _healthy_target_attribution_gap(campaign: Path, checkpoint: dict) -> bool:
    """Detect a raw exact target check lost by graph attribution.

    Bootstrap is only valid when the original JUnit truly did not reach the
    check. A GraphChecker graph that lost a raw TARGET_CHECK needs adapter
    repair, even if an old core checkpoint still says ``running``.
    """
    if checkpoint.get("healthy_target_reached") is not False:
        return False
    healthy = checkpoint.get("healthy")
    selected = set(checkpoint.get("configured_check_sites", []))
    if not isinstance(healthy, dict) or not selected:
        return False
    relative = healthy.get("result")
    if not isinstance(relative, str) or not _inside(relative):
        raise ValueError("healthy result receipt is missing")
    result = _object(campaign / relative)
    if result.get("evidence", {}).get("target_reached"):
        return False
    raw = result.get("artifacts", {}).get("raw_trace", {})
    name = raw.get("path")
    if not isinstance(name, str) or not _inside(name):
        raise ValueError("healthy raw trace path is missing")
    path = (campaign / relative).parent / name
    if not path.is_file() or sha256(path) != raw.get("sha256"):
        raise ValueError("healthy raw trace differs from result receipt")
    return _scan_target_raw(str(path), tuple(sorted(selected)), raw.get("encoding"))


@functools.lru_cache(maxsize=64)
def _scan_target_raw(path_name: str, selected: tuple[str, ...], encoding: str) -> bool:
    path = Path(path_name)
    opener = gzip.open if encoding == "gzip" else open
    with opener(path, "rb") as stream:
        for line in stream:
            if b'TARGET_CHECK' not in line:
                continue
            row = json.loads(line)
            if row.get("kind") == "TARGET_CHECK" and row.get("siteId") in selected:
                return True
    return False


def _weave_identity(campaign: Path, config_sha: str, graph_jar_sha: str) -> bool:
    receipt = campaign / "prepared/weave-receipt.json"
    if not receipt.is_file():
        return False
    row = _object(receipt)
    return (row.get("config_sha256") == config_sha and
            row.get("graph_jar_sha256") == graph_jar_sha)


def plan(document: dict, inventory: dict[str, dict], manifest_sha: str,
         *, active_jobs: list[dict] | None = None) -> dict:
    root = Path(document["state_root"])
    imports = Path(document["import_root"]) / "import-index.json"
    imported = {}
    if imports.exists():
        from Mallory.dispatch.graphchecker_port.aggregate import load_import_index
        imported = load_import_index(imports)
    rows = []
    for case_id in document["case_ids"]:
        row = inventory[case_id]
        case, state_path = _case_files(root, case_id)
        if case_id in imported:
            status = ("skip_imported_terminal" if (case / "result.json").is_file()
                      or not (state_path.is_file() or
                              case_id in document.get("existing_campaigns", {}))
                      else "ready_result_receipt")
        elif case_id in document.get("holds", {}):
            status = "skip_reviewed_hold"
        elif case_id in document.get("existing_campaigns", {}):
            status = _external_state(document["existing_campaigns"][case_id], case_id)
        elif case_id in document.get("no_suitable_junit", {}):
            status = "skip_reviewed_no_suitable_junit"
        elif not _eligible(row):
            status = "blocked_no_eligible_original_junit"
        elif case_id not in document["adapter_supported_case_ids"]:
            status = "blocked_unsupported_adapter_case"
        else:
            state = _state(state_path, case_id, manifest_sha)
            if state is None:
                if case.exists() and any(case.iterdir()):
                    status = "blocked_unrecognized_case_data"
                else:
                    status = "ready_prepare"
            elif state["phase"] == "preparing":
                status = "resume_new_prepare_attempt"
            else:
                prep = Path(state["prep"])
                receipt = _receipt(prep, case_id, manifest_sha)
                if receipt["config_sha256"] != state.get("config_sha256"):
                    status = "blocked_config_changed"
                elif state["phase"] == "prepared":
                    status = "ready_campaign"
                elif state["phase"] == "imported":
                    status = "blocked_missing_import_index"
                else:
                    campaign = Path(state["campaign"])
                    if not campaign.is_dir():
                        status = "blocked_missing_campaign"
                    elif _core_lock_held(campaign):
                        status = "currently_running"
                    else:
                        cp = campaign / "checkpoint.json"
                        if cp.is_file():
                            record = _object(cp)
                            if record.get("config_sha256") != state["config_sha256"]:
                                status = "blocked_campaign_config_changed"
                            elif record.get("terminal") is False and (
                                    record.get("status") != "running"):
                                status = "blocked_explicit_checkpoint_status"
                            elif record.get("terminal") is True:
                                status = "ready_import"
                            elif _healthy_target_attribution_gap(campaign, record):
                                status = "blocked_healthy_target_attribution"
                            elif (campaign / "prepared").exists() and not (
                                    campaign / "prepared/weave-receipt.json").is_file():
                                status = "resume_new_campaign_attempt"
                            elif (campaign / "prepared/weave-receipt.json").is_file() and not (
                                    _weave_identity(campaign, state["config_sha256"],
                                                    document["pins"].get(_object(
                                                        prep / receipt["config_relative"]
                                                    ).get("graph_jar"), ""))):
                                status = "blocked_weave_identity_changed"
                            else:
                                status = "resume_campaign"
                        else:
                            status = "resume_campaign"
        rows.append({"case_id": case_id, "system": document["system"],
                     "host": document["host"], "junit": row.get("workload", {}).get(
                         "selected_selector"), "status": status,
                     "state": str(state_path)})
    return {"schema_version": 1, "mode": "dry_run", "host": document["host"],
            "system": document["system"], "manifest_sha256": manifest_sha,
            "active_jobs": active_jobs if active_jobs is not None else _live_graph_jobs(),
            "cases": rows}


def _prepare(document: dict, case_id: str, case: Path, state_path: Path,
             manifest_sha: str) -> dict:
    attempt = uuid.uuid4().hex
    prep = case / "preparations" / attempt
    prep.mkdir(parents=True, exist_ok=False)
    state = {"schema_version": 1, "case_id": case_id,
             "manifest_sha256": manifest_sha, "phase": "preparing",
             "prep": str(prep), "created_at": _now()}
    _atomic_json(state_path, state)
    outputs = {}
    inventory = Path(document["inventory"])
    for index, step in enumerate(document["recipe"]["steps"]):
        _verify_pins(document)
        command = _argv(step, case_id, prep, inventory)
        started = time.monotonic()
        with (prep / f"step-{index}.stdout.log").open("wb") as stdout, \
                (prep / f"step-{index}.stderr.log").open("wb") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr,
                                    cwd=prep, timeout=step.get("timeout_seconds", 3600))
        _atomic_json(prep / f"step-{index}.json", {
            "schema_version": 1, "kind": step["kind"], "argv": command,
            "returncode": result.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3)})
        if result.returncode:
            raise RuntimeError(f"{case_id} {step['kind']} failed; inspect {prep}")
        for relative in step["outputs"]:
            output = prep / relative
            if not output.is_file() or output.is_symlink():
                raise ValueError(f"missing prepared output: {output}")
            outputs[relative] = sha256(output)
    relative = document["recipe"]["config_relative"]
    config = prep / relative
    if not config.is_file() or config.is_symlink():
        raise ValueError(f"adapter did not produce native config: {config}")
    parsed = _object(config)
    if parsed.get("case_id") != case_id:
        raise ValueError("prepared native config has wrong case ID")
    if document.get("compact_runtime_trace", False):
        _enable_compact_runtime_trace(parsed, document["pins"])
        _atomic_json(config, parsed)
    for field in ("weave_manifest", "static_scope_map"):
        item = Path(parsed.get(field, ""))
        try:
            scoped = item.resolve(strict=True).relative_to(prep.resolve())
        except (OSError, ValueError):
            raise ValueError(f"{field} must be generated in the unique preparation")
        relative_scoped = scoped.as_posix()
        if relative_scoped not in outputs or sha256(item) != outputs[relative_scoped]:
            raise ValueError(f"{field} must be among SHA-pinned preparation outputs")
    graph_jar = parsed.get("graph_jar")
    if not isinstance(graph_jar, str) or document["pins"].get(graph_jar) != sha256(
            Path(graph_jar)):
        raise ValueError("graph analyzer is not a SHA-pinned queue input")
    outputs[relative] = sha256(config)
    receipt = {"schema_version": 1, "case_id": case_id,
               "manifest_sha256": manifest_sha, "config_relative": relative,
               "config_sha256": outputs[relative], "outputs": outputs,
               "prepared_at": _now()}
    _atomic_json(prep / "prepare-receipt.json", receipt)
    state.update({"phase": "prepared", "config_sha256": outputs[relative]})
    _atomic_json(state_path, state)
    return state


def _enable_compact_runtime_trace(config: dict, pins: dict[str, str]) -> None:
    """Opt in only when the pinned runtime bytecode implements the setting."""
    supported = False
    for name in config.get("tool_classpath", []):
        path = Path(name)
        if not path.is_file() or path.suffix != ".jar" or pins.get(name) != sha256(path):
            continue
        with zipfile.ZipFile(path) as archive:
            if COMPACT_CLASS not in archive.namelist():
                continue
            if b"mallory.graphchecker.trace.compact" in archive.read(COMPACT_CLASS):
                supported = True
                break
    if not supported:
        raise ValueError("pinned runtime jar lacks compact trace property")
    runner = config.get("runner")
    if not isinstance(runner, dict) or not isinstance(runner.get("jvm_args"), list):
        raise ValueError("native runner lacks JVM arguments")
    args = runner["jvm_args"]
    if any(isinstance(arg, str) and arg.startswith(
            "-Dmallory.graphchecker.trace.compact=") and arg != COMPACT_PROPERTY
            for arg in args):
        raise ValueError("conflicting compact trace JVM setting")
    if COMPACT_PROPERTY not in args:
        args.append(COMPACT_PROPERTY)


def _campaign(document: dict, case_id: str, state: dict, state_path: Path) -> dict:
    _verify_pins(document)
    prep = Path(state["prep"])
    config = prep / document["recipe"]["config_relative"]
    if sha256(config) != state["config_sha256"]:
        raise ValueError("native config changed after preparation")
    if state["phase"] == "prepared" or not state.get("campaign"):
        campaign = state_path.parent / "campaigns" / uuid.uuid4().hex
        campaign.mkdir(parents=True, exist_ok=False)
        state.update({"phase": "running", "campaign": str(campaign)})
        _atomic_json(state_path, state)
    else:
        campaign = Path(state["campaign"])
    if (campaign / "prepared").exists() and not (
            campaign / "prepared/weave-receipt.json").is_file():
        state.setdefault("abandoned_campaigns", []).append(str(campaign))
        campaign = state_path.parent / "campaigns" / uuid.uuid4().hex
        campaign.mkdir(parents=True, exist_ok=False)
        state["campaign"] = str(campaign)
        _atomic_json(state_path, state)
    command = [sys.executable, "-m", "Mallory.core.graphchecker_fuzzer",
               "--config", str(config), "--out", str(campaign)]
    started = time.monotonic()
    with (campaign / "queue.stdout.log").open("ab") as stdout, \
            (campaign / "queue.stderr.log").open("ab") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr)
    history = state.setdefault("attempts", [])
    history.append({"returncode": result.returncode,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "finished_at": _now()})
    _atomic_json(state_path, state)
    if result.returncode:
        raise RuntimeError(f"native campaign exited {result.returncode}: {campaign}")
    return state


def _verify_pins(document: dict) -> None:
    if sha256(Path(document["inventory"])) != document["inventory_sha256"]:
        raise ValueError("inventory changed during queue execution")
    for name, digest in document["pins"].items():
        if sha256(Path(name)) != digest:
            raise ValueError(f"tool input changed during queue execution: {name}")


def _import(document: dict, case_id: str, state: dict, state_path: Path) -> None:
    prep = Path(state["prep"])
    config = prep / document["recipe"]["config_relative"]
    campaign = Path(state["campaign"])
    receipt = import_case(case_id, config, campaign, Path(document["import_root"]))
    _record_result(document, case_id, config, campaign, receipt,
                   state_path.parent, state.get("attempts", []))
    state.update({"phase": "imported", "import_receipt": receipt,
                  "imported_at": _now()})
    _atomic_json(state_path, state)


def _record_result(document: dict, case_id: str, config: Path, campaign: Path,
                   import_receipt: dict, case_root: Path, attempts: list[dict]) -> None:
    """Small, stable per-case timing/result hook; full traces stay in campaign."""
    inventory = _object(Path(document["inventory"]))
    matches = [row for row in inventory["cases"] if row["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError("result row absent from pinned inventory")
    item = matches[0]
    summary = _object(campaign / "summary.json")
    target = item["target"]
    result = {"schema_version": 1, "case_id": case_id,
              "system": document["system"], "host": document["host"],
              "target_source_path": target["source_path"],
              "target_function": target["function"],
              "target_line": target["source_line"],
              "target_exception": target["target_exception"],
              "original_junit": item["workload"]["selected_selector"],
              "config": import_receipt["source_paths"]["config"],
              "config_sha256": import_receipt["source_sha256"]["config"],
              "campaign": import_receipt["source_campaign"],
              "status": summary["status"],
              "completed_fault_trials": summary.get("completed_fault_trials", 0),
              "strict_trials": summary.get("strict_trials", 0),
              "post_fault_target_trials": summary.get("post_fault_target_trials", 0),
              "target_exception_triggered_trials": summary.get(
                  "target_exception_triggered_trials", 0),
              "differential_candidates": summary.get("differential_candidates", 0),
              "trial_elapsed_seconds": summary.get("trial_elapsed_seconds"),
              "queue_launcher_elapsed_seconds": round(sum(float(
                  attempt.get("elapsed_seconds", 0)) for attempt in attempts), 3),
              "import_source_sha256": import_receipt["source_sha256"]}
    path = case_root / "result.json"
    if path.exists():
        if _object(path) != result:
            raise ValueError(f"existing per-case result differs: {path}")
    else:
        _atomic_json(path, result)


def _record_review_skip(document: dict, case_id: str, root: Path, kind: str) -> None:
    review = document[kind][case_id]
    row = {"schema_version": 1, "case_id": case_id,
           "system": document["system"], "host": document["host"],
           "status": "no_suitable_original_junit" if kind == "no_suitable_junit"
                     else "held_for_adapter_review",
           "reason": review["reason"], "evidence_paths": review["evidence_paths"]}
    path = root / case_id / "review-result.json"
    if path.is_file() and _object(path) != row:
        raise ValueError(f"review result changed: {path}")
    if not path.exists():
        _atomic_json(path, row)


def run_queue(document: dict, inventory: dict[str, dict], manifest_sha: str,
              *, max_cases: int | None = None) -> dict:
    if socket.gethostname().split(".")[0] != document["host"]:
        raise ValueError("run this lane only on its declared owner host")
    root = Path(document["state_root"])
    root.mkdir(parents=True, exist_ok=True)
    lease_path = root / (".host-" + document["host"] + ".lock")
    completed = []
    with lease_path.open("a+") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for case_id in document["case_ids"]:
            if max_cases is not None and len(completed) >= max_cases:
                break
            current = plan(document, inventory, manifest_sha)
            status = next(row["status"] for row in current["cases"]
                          if row["case_id"] == case_id)
            if status in ("skip_imported_terminal", "skip_reviewed_no_suitable_junit",
                          "skip_reviewed_hold"):
                if status == "skip_reviewed_no_suitable_junit":
                    _record_review_skip(document, case_id, root, "no_suitable_junit")
                elif status == "skip_reviewed_hold":
                    _record_review_skip(document, case_id, root, "holds")
                completed.append({"case_id": case_id, "status": status})
                continue
            if status == "ready_result_receipt":
                from Mallory.dispatch.graphchecker_port.aggregate import load_import_index
                selected = load_import_index(Path(document["import_root"]) /
                                             "import-index.json")[case_id]
                imported_receipt = _object(selected / "import-receipt.json")
                sources = imported_receipt["source_paths"]
                state_path = root / case_id / "queue-state.json"
                attempts = (_state(state_path, case_id, manifest_sha) or {}).get(
                    "attempts", []) if state_path.is_file() else []
                _record_result(document, case_id, Path(sources["config"]),
                               selected, imported_receipt, root / case_id, attempts)
                completed.append({"case_id": case_id, "status": "result_receipt_recovered"})
                continue
            if status == "external_terminal_import":
                paths = document["existing_campaigns"][case_id]
                if any(paths["campaign"] in job["command"] for job in current["active_jobs"]):
                    completed.append({"case_id": case_id, "status": "host_busy_external"})
                    break
                receipt = import_case(case_id, Path(paths["config"]),
                                      Path(paths["campaign"]), Path(document["import_root"]))
                _record_result(document, case_id, Path(paths["config"]),
                               Path(paths["campaign"]), receipt,
                               root / case_id, [])
                completed.append({"case_id": case_id, "status": "imported_external",
                                  "receipt": receipt})
                continue
            if status in ("currently_running", "external_running"):
                completed.append({"case_id": case_id, "status": status})
                break
            if status.startswith("blocked_") or status.startswith("external_"):
                completed.append({"case_id": case_id, "status": status})
                continue
            # Any other active GraphChecker campaign on this host owns its
            # resources. It may have been started before this queue existed.
            if current["active_jobs"]:
                completed.append({"case_id": case_id, "status": "host_busy",
                                  "active_jobs": current["active_jobs"]})
                break
            case, state_path = _case_files(root, case_id)
            state = _state(state_path, case_id, manifest_sha)
            if status in ("ready_prepare", "resume_new_prepare_attempt"):
                state = _prepare(document, case_id, case, state_path, manifest_sha)
            elif state is None:
                raise ValueError("missing queue state for runnable case")
            if status != "ready_import":
                state = _campaign(document, case_id, state, state_path)
            _import(document, case_id, state, state_path)
            completed.append({"case_id": case_id, "status": "imported",
                              "campaign": state["campaign"]})
    return {"schema_version": 1, "host": document["host"],
            "system": document["system"], "outcomes": completed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="execute one lane; default is read-only")
    parser.add_argument("--max-cases", type=int)
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be positive")
    document, inventory, digest = load_manifest(args.manifest)
    result = (run_queue(document, inventory, digest, max_cases=args.max_cases)
              if args.run else plan(document, inventory, digest))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
