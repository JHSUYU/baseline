"""One checklist case end to end: selection, healthy run, campaign.

For each case the worker resolves the cluster JUnit and the target's
exception type from the checklist and the release source, asks Soot for a
selection, and runs the unchanged JUnit once under the agent. When that
healthy run observes no selected I/O, the selection widens (callers 6 deep,
then 800 methods) and the JUnit runs again. The campaign then fuzzes from
the healthy trace. Every step is resumable from ``<results>/<case>/``.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import settings
from .campaign import campaign, replay
from .faults import Sequence, point_from_event
from .selection import select_case
from .systems import SystemSpec, system_of
from .trace import atomic_json


@dataclass(frozen=True)
class Profile:
    """One width of the Soot selection, and where its runs live."""
    name: str | None          # selection_profile; None for the default width
    subdirectory: str         # selection output under the case directory
    healthy: str              # healthy run directory
    log: str                  # healthy run log
    analysis: dict[str, int]  # overrides of the system's analysis
    failure: str              # message when its healthy JUnit fails


PROFILES = (
    Profile(None, "", "healthy", "healthy-run.log", {},
            "original healthy JUnit did not pass"),
    Profile("caller_expanded", "caller-expanded", "healthy-expanded",
            "healthy-expanded-run.log", {"max_caller_depth": 6, "max_callee_depth": 0},
            "original healthy JUnit did not pass with expanded selection"),
    Profile("caller_expanded_800", "caller-expanded-800", "healthy-800",
            "healthy-800-run.log", {"max_methods": 800, "max_caller_depth": 6,
                                    "max_callee_depth": 0},
            "original healthy JUnit did not pass with wide selection"),
)


# --- reading the checklist row ----------------------------------------------

def test_spec(row: dict[str, Any]) -> tuple[str, str]:
    """(class, method) of the row's cluster JUnit."""
    raw = row.get("cluster_test")
    if not raw:
        raise ValueError("no cluster test")
    raw = raw.split(";", 1)[0].strip()
    if "#" in raw:
        clazz, method = raw.split("#", 1)
    elif "." in raw:
        clazz, method = raw.rsplit(".", 1)
    else:
        raise ValueError(f"cannot parse cluster test: {raw}")
    spec = system_of(row["system"])
    # JUnit 4's Request.method matches a parameterized display name;
    # Jupiter's selector takes the source method name.
    if spec.name != "HDFS":
        method = re.sub(r"\[\d+\]$|\(.*\)$", "", method)
    if "." not in clazz:
        matches = sorted(spec.source.rglob(clazz + ".java"))
        if len(matches) != 1:
            raise ValueError(f"ambiguous test class {clazz}: {len(matches)} source matches")
        package = re.search(r"^package\s+([\w.]+)\s*;",
                            matches[0].read_text(errors="replace"), re.M)
        if not package:
            raise ValueError(f"package missing in {matches[0]}")
        clazz = package.group(1) + "." + clazz
    return clazz, method


def _binary_name(qualified: str) -> str:
    # Imports say Outer.Inner; stack traces say Outer$Inner.
    return re.sub(r"([A-Z][\w]*)\.([A-Z][\w]*)", r"\1$\2", qualified)


def exception_type(row: dict[str, Any]) -> str | None:
    """The binary class name of the exception the check throws, or None.

    None marks a state guard rather than a throw site: it still gives reach
    and coverage feedback, but no exception oracle.
    """
    code = row.get("check_code", "")
    source = system_of(row["system"]).source / row["exact_check_location"]["file"]
    text = source.read_text(errors="replace") if source.is_file() else ""
    match = re.search(r"throw\s+new\s+([\w.]+)\s*\(", code)
    if not match:
        # An exception allocated into a local, then thrown.
        match = re.search(r"\b([\w.]+)\s+\w+\s*=\s*new\s+\1\s*\(", code)
    if not match:
        rethrow = re.search(r"throw\s+(\w+)\s*;", code)
        if rethrow:
            # A rethrown catch variable: the nearest matching catch before it.
            prefix = "\n".join(text.splitlines()[
                :int(row["exact_check_location"]["selected_line"])])
            catches = list(re.finditer(r"catch\s*\(\s*([\w.]+)\s+" +
                                       re.escape(rethrow.group(1)) + r"\s*\)", prefix))
            if catches:
                match = catches[-1]
    if match:
        name = match.group(1)
        resolved = _resolve_class(name, text)
        if resolved:
            return resolved
    if "Preconditions.checkState" in code:
        return "java.lang.IllegalStateException"
    if "Preconditions.checkArgument" in code:
        return "java.lang.IllegalArgumentException"
    if re.search(r"\bassert\s+", code):
        return "java.lang.AssertionError"
    return None


def selected_exception_type(selection: dict[str, Any], location: dict[str, Any]) -> str | None:
    """The type Soot gives the typed throw at the check's line, or None.

    It names the exception a check throws when the source text does not:
    ``throw make(x)`` throws the static type ``make`` returns.
    """
    types = {site.get("thrown_type") for site in selection.get("target_throw_sites", [])
             if site.get("line") == location.get("selected_line") and site.get("thrown_type")}
    return types.pop() if len(types) == 1 else None


def selected_site_id(selection: dict[str, Any], location: dict[str, Any],
                     exception: str | None = None) -> str:
    """The check's site as a Soot unit (``#uN``).

    A checklist row may give it as a source line (``#L<line>``); the agent and
    the oracle name sites by unit, so the throw of the check's exception type
    that Soot found at that line stands for it (a line can also hold the
    compiler's rethrow of a try-with-resources). A unit site, or a line with
    no single such throw, is kept.
    """
    site = location["site_id"]
    if "#L" not in site:
        return site
    units = {row["soot_site_id"] for row in selection.get("target_throw_sites", [])
             if row.get("line") == location.get("selected_line") and row.get("soot_site_id")
             and (exception is None or row.get("thrown_type") == exception)}
    return units.pop() if len(units) == 1 else site


def _resolve_class(name: str, text: str) -> str | None:
    if "." in name:
        outer, *nested = name.split(".")
        imported = re.search(r"^import\s+([\w.]+\." + re.escape(outer) + r")\s*;", text, re.M)
        if imported:
            return _binary_name(imported.group(1) + "".join("." + part for part in nested))
        if outer[0].islower():
            return _binary_name(name)
        return None
    imported = re.search(r"^import\s+([\w.]+\." + re.escape(name) + r")\s*;", text, re.M)
    if imported:
        return _binary_name(imported.group(1))
    if name in {"IOException", "EOFException", "IllegalArgumentException",
                "IllegalStateException", "RuntimeException", "AssertionError"}:
        return ("java.io." if name in {"IOException", "EOFException"} else "java.lang.") + name
    # A nested exception inherited from the imported superclass
    # (SecretManager.InvalidToken in a subclass).
    parent = re.search(r"\bclass\s+\w+[^\{;]*?\bextends\s+(\w+)", text)
    if parent:
        base = parent.group(1)
        base_import = re.search(r"^import\s+([\w.]+\." + re.escape(base) + r")\s*;", text, re.M)
        if base_import and re.search(r"\bthrows\s+" + re.escape(name) + r"\b", text):
            return _binary_name(base_import.group(1) + "." + name)
    package = re.search(r"^package\s+([\w.]+)\s*;", text, re.M)
    if package:
        return package.group(1) + "." + name
    return None


# --- the healthy run ------------------------------------------------------------

def runner_command(spec: SystemSpec, case_id: str, clazz: str, method: str, output: str,
                   selection: Path, classes_dir: Path | None = None) -> list[str]:
    command = [sys.executable, "-m", "crashfuzz.runners", spec.name, "--case-id", case_id,
               "--test-class", clazz, "--test-method", method, "--output", output,
               "--static-selection", str(selection), "--timeout", str(spec.timeout)]
    if classes_dir is not None:
        command += ["--classes-dir", str(classes_dir)]
    return command


def runner_env() -> dict[str, str]:
    """What a runner subprocess needs to import this package."""
    return {"PYTHONPATH": str(settings.HOME)}


def run_logged(argv: list[str], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as log:
        return subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=False,
                              env={**os.environ, **runner_env()}).returncode


def run_healthy_with_retry(argv: list[str], log: Path, output: Path) -> int:
    """Retry one failed clean JUnit once, keeping the failure for diagnosis."""
    if run_logged(argv, log) == 0:
        return 0
    log.replace(log.with_name(log.stem + "-failed-1" + log.suffix))
    for name in ("junit.log", "manifest.json"):
        if (output / name).is_file():
            shutil.copy2(output / name, output / (name + ".failed-1"))
    return run_logged(argv, log)


def healthy_matches(manifest: Path, digest: str) -> bool:
    """A passing healthy run made with exactly this selection exists."""
    if not manifest.is_file():
        return False
    try:
        record = json.loads(manifest.read_text())
        if record.get("returncode") != 0:
            return False
        with Path(record["trace"]).open() as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("event") == "STATIC_SELECTION_APPLIED":
                    return event.get("digest") == digest
    except (OSError, ValueError, KeyError):
        return False
    return False


def observed_fault_points(trace: Path) -> bool:
    with trace.open() as stream:
        return any((event := json.loads(line)).get("event") == "FAULT_POINT_OBSERVED" and
                   point_from_event(event) is not None for line in stream)


def live_selection_artifact(base: Path, cid: str, target: str) -> Path | None:
    """The selection an unfinished campaign of this case already runs with."""
    for artifact in (base / "caller-expanded-800/soot-selection.json",
                     base / "caller-expanded/soot-selection.json",
                     base / "soot-selection.json"):
        if not artifact.is_file():
            continue
        try:
            selected = json.loads(artifact.read_text())
            if selected.get("target_method") != target or not selected.get("input_digest"):
                continue
            for state_path in base.glob("campaign*/" + cid + "/state.json"):
                state = json.loads(state_path.read_text())
                if (state.get("static_selection_digest") == selected["input_digest"] and
                        (state.get("seed") or state.get("completed"))):
                    return artifact
        except (OSError, ValueError):
            continue
    return None


def healthy_dir(base: Path, selection: dict[str, Any], campaign_suffix: str = "") -> Path:
    name = next((profile.healthy for profile in PROFILES
                 if profile.name == selection.get("selection_profile")), "healthy")
    return base / (name + ("-" + campaign_suffix if campaign_suffix else ""))


# --- one case ----------------------------------------------------------------------

def _prepare(row: dict[str, Any], base: Path, summary: dict[str, Any], summary_path: Path,
             max_trials: int, max_faults: int, campaign_suffix: str,
             refresh_selection: bool,
             config_name: str = "campaign-config.json",
             stop_at_candidate: bool = False) -> tuple[dict[str, Any], Path]:
    """Selection and healthy run for the row; returns (campaign config, its root)."""
    cid = row["case_id"]
    spec = system_of(row["system"])
    location = row["exact_check_location"]
    clazz, method = test_spec(row)
    # A checklist site is a Soot unit (#u) or a source line (#L) of the method.
    target = location["site_id"].split("#", 1)[0]
    exc_type = exception_type(row)
    pinned = None if refresh_selection else live_selection_artifact(base, cid, target)
    selection = select_case(target, location, None if pinned else spec.analysis(), base,
                            artifact=pinned)
    exc_type = exc_type or selected_exception_type(selection, location)
    summary.update(status="healthy", test_class=clazz, test_method=method,
                   exception_type=exc_type, static_io_calls=len(selection["io_calls"]),
                   static_coverage_methods=len(selection["coverage_methods"]))
    atomic_json(summary_path, summary)
    start = next(index for index, profile in enumerate(PROFILES)
                 if profile.name == selection.get("selection_profile"))
    for index in range(start, len(PROFILES)):
        profile = PROFILES[index]
        if index > start:
            # The workload executed no selected I/O: the check may be reached
            # through a deeper caller path than this width covers.
            selection = select_case(target, location, {**spec.analysis(), **profile.analysis},
                                    base / profile.subdirectory, profile=profile.name)
            summary.update(static_io_calls=len(selection["io_calls"]),
                           static_coverage_methods=len(selection["coverage_methods"]),
                           selection_profile=profile.name)
            atomic_json(summary_path, summary)
        artifact = Path(selection["artifact_path"])
        healthy = healthy_dir(base, selection, campaign_suffix)
        manifest = healthy / "manifest.json"
        if not healthy_matches(manifest, selection["input_digest"]):
            argv = runner_command(spec, cid, clazz, method, str(healthy), artifact)
            # The first run keeps the default run's log and message whatever
            # width a resumed case was pinned to.
            named = PROFILES[0] if index == start else profile
            if run_healthy_with_retry(argv, base / named.log, healthy) != 0:
                raise RuntimeError(named.failure)
        healthy_record = json.loads(manifest.read_text())
        if observed_fault_points(Path(healthy_record["trace"])):
            break
    summary.update(selection_artifact=str(artifact), healthy_manifest=str(manifest))
    atomic_json(summary_path, summary)
    workspace = base / "campaign-workspace"
    temp = base / "campaign-temp"
    workspace.mkdir(exist_ok=True)
    temp.mkdir(exist_ok=True)
    command = runner_command(spec, cid, clazz, method, "{trace_dir}", artifact,
                             healthy / "classes" if spec.name == "Solr" else None)
    config = {"case_id": cid, "system": row["system"], "test_class": clazz,
              "test_method": method, "cwd": str(workspace),
              "workspaces": {"system_test": str(workspace), "temp": str(temp)},
              "env": runner_env(),
              "target": {"method": target,
                         "site_id": selected_site_id(selection, location, exc_type),
                         "check_events": ["CHECK_REACHED"], "exception_type": exc_type,
                         "source_file": location["file"],
                         "source_line": location["selected_line"],
                         "code": row.get("check_code")},
              "static_selection": {"artifact": str(artifact)},
              "archive_completed_trials": True,
              "seed": {"trace": healthy_record["trace"],
                       "elapsed_seconds": healthy_record["elapsed_seconds"]},
              "trial": {"command": command},
              "budget": {"max_trials": max_trials, "max_faults": max_faults,
                         "base_trials": min(80, max_trials),
                         "min_target_retained_trials": 30, "max_unmatched_retries": 1,
                         "stop_at_candidate": stop_at_candidate},
              "timeout_seconds": spec.timeout + 30}
    atomic_json(base / config_name, config)
    # A checkpoint made with another selection keeps its own directory.
    root = base / "campaign"
    existing = root / cid / "state.json"
    if existing.is_file() and json.loads(existing.read_text()).get(
            "static_selection_digest") != selection["input_digest"]:
        root = base / ("campaign-" + selection["input_digest"][:12])
    if campaign_suffix:
        root = base / (root.name + "-" + campaign_suffix)
    return config, root


def _new_summary(row: dict[str, Any]) -> dict[str, Any]:
    location = row["exact_check_location"]
    return {"case_id": row["case_id"], "system": row["system"],
            "target_file": location["file"], "target_function": location["enclosing_function"],
            "target_line": location["selected_line"], "target_site_id": location["site_id"],
            "check_code": row.get("check_code"), "cluster_test": row.get("cluster_test"),
            "status": "preparing", "bug_mark": "none", "finished": False,
            "started_at": time.time(), "updated_at": time.time()}


def _run_case_unlocked(row: dict[str, Any], result_root: Path, max_trials: int,
                       max_faults: int, campaign_suffix: str = "",
                       refresh_selection: bool = False,
                       stop_at_candidate: bool = False) -> dict[str, Any]:
    cid = row["case_id"]
    base = result_root / cid
    base.mkdir(parents=True, exist_ok=True)
    summary_path = base / "case-summary.json"
    previous_seconds = 0.0
    prior = None
    if summary_path.is_file():
        prior = json.loads(summary_path.read_text())
        previous_seconds = float(prior.get("total_elapsed_seconds") or 0)
        if prior.get("finished") and not (refresh_selection or campaign_suffix):
            return prior
    summary = _new_summary(row)
    atomic_json(summary_path, summary)
    if not row.get("cluster_test"):
        summary.update(status="no_cluster_test", finished=True, total_elapsed_seconds=0,
                       fault_trials=0)
        atomic_json(summary_path, summary)
        return summary
    started = time.monotonic()
    try:
        if prior and prior.get("started_at"):
            summary["started_at"] = prior["started_at"]
        config, root = _prepare(row, base, summary, summary_path, max_trials, max_faults,
                                campaign_suffix, refresh_selection,
                                stop_at_candidate=stop_at_candidate)
        summary["status"] = "fuzzing"
        atomic_json(summary_path, summary)
        state = campaign(config, root)
        record_path = root / cid / "result.json"
        record = json.loads(record_path.read_text())
        healthy = json.loads(Path(summary["healthy_manifest"]).read_text())
        summary.update(status=record["status"], finished=state["finished"],
                       healthy_seconds=healthy["elapsed_seconds"],
                       fault_trials=record["fault_trials"],
                       strict_injections=record["strict_injections"],
                       post_fault_target_reach_trials=record["post_fault_target_reach_trials"],
                       target_exception_candidates=record["oracle_candidates"],
                       bug_mark=record["bug_mark"],
                       active_runtime_seconds=record["total_elapsed_seconds"],
                       total_elapsed_seconds=round(max(
                           previous_seconds + time.monotonic() - started,
                           float(record["total_elapsed_seconds"])), 3),
                       campaign_result=str(record_path),
                       **_first_candidate(state, summary["started_at"]))
    except Exception as error:
        if str(error).startswith("case already claimed:") and prior is not None:
            atomic_json(summary_path, prior)
            return prior
        summary.update(status="blocked_setup", error=str(error),
                       total_elapsed_seconds=round(previous_seconds +
                                                   time.monotonic() - started, 3))
    summary["updated_at"] = time.time()
    atomic_json(summary_path, summary)
    return summary


def _first_candidate(state: dict[str, Any], started_at: float) -> dict[str, Any]:
    """The first candidate trial and the wall time from the case's start (selection, healthy
    run and trials) to its end."""
    for item in state["completed"]:
        if item["status"] in {"target_exception_candidate", "partial_target_exception_candidate"}:
            result = json.loads(Path(item["result"]).read_text())
            return {"first_candidate_trial": item["number"],
                    "first_candidate_seconds": round(result["completed_at"] - started_at, 1)}
    return {"first_candidate_trial": None, "first_candidate_seconds": None}


def run_case(row: dict[str, Any], result_root: Path, max_trials: int, max_faults: int,
             campaign_suffix: str = "", refresh_selection: bool = False,
             stop_at_candidate: bool = False) -> dict[str, Any]:
    """Run (or resume) a case; claimed first so parallel workers never collide."""
    base = result_root / row["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    with (base / ".run-case.lock").open("a+") as claim:
        try:
            fcntl.flock(claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            summary = base / "case-summary.json"
            if summary.is_file():
                return json.loads(summary.read_text())
            return {"case_id": row["case_id"], "system": row["system"],
                    "status": "claimed_elsewhere", "finished": False}
        try:
            return _run_case_unlocked(row, result_root, max_trials, max_faults,
                                      campaign_suffix, refresh_selection, stop_at_candidate)
        finally:
            fcntl.flock(claim, fcntl.LOCK_UN)


def replay_case(row: dict[str, Any], result_root: Path, sequence: Sequence, repeats: int,
                name: str) -> dict[str, Any]:
    """Run one fault sequence ``repeats`` times on the case's selection and healthy run.

    The replays live in ``<results>/<case>/replay-<name>/`` and share the
    selection and healthy run with the case's campaign.
    """
    base = result_root / row["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    summary = _new_summary(row)
    config, _ = _prepare(row, base, summary, base / f"replay-{name}-summary.json",
                         repeats, max(1, len(sequence)), "", False,
                         config_name=f"replay-{name}-config.json")
    state = replay(config, base / f"replay-{name}", sequence, repeats)
    statuses = [item["status"] for item in state["completed"]]
    return {"case_id": row["case_id"], "replays": len(statuses),
            "statuses": statuses,
            "candidates": sum(status in {"target_exception_candidate",
                                         "partial_target_exception_candidate"}
                              for status in statuses),
            "root": str(base / f"replay-{name}" / row["case_id"])}


def checklist_rows(checklist: Path, system: str, include_added: bool = False) -> list[dict]:
    """The checklist's rows of one system, in checklist order."""
    groups = {"original_102"} | ({"added_known_issue_check"} if include_added else set())
    return [row for row in json.loads(checklist.read_text())["rows"]
            if row.get("selection_group") in groups and system_of(row["system"]).name == system]
