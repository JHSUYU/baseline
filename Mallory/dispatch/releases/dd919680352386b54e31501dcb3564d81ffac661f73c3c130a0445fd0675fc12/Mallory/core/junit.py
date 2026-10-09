"""Per-trial JUnit evidence for original MiniCluster workloads.

The controller never infers a passing test from the process exit code alone.
Maven reports get a unique suffix so an earlier trial cannot satisfy this gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runner_kind(argv: list[str]) -> str | None:
    if Path(argv[0]).name in {"mvn", "mvnw"}:
        return "surefire_xml"
    if "edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit" in argv:
        return "hbase_junit_platform"
    if any(Path(arg).name == "run_pilot.py" for arg in argv):
        return "solr_junit_wrapper"
    return None


def _counts_status(tests: int, failures: int, errors: int,
                   skipped: int, return_code: int) -> str:
    if failures or errors:
        return "failed"
    if tests <= skipped:
        return "no_tests"
    if return_code != 0:
        return "process_failed"
    return "passed"


def _projects(argv: list[str], cwd: Path) -> list[Path]:
    for index, arg in enumerate(argv):
        if arg in {"-pl", "--projects"} and index + 1 < len(argv):
            value = argv[index + 1]
        elif arg.startswith(("-pl=", "--projects=")):
            value = arg.split("=", 1)[1]
        else:
            continue
        projects = []
        for entry in value.split(","):
            # Maven artifact selectors need a module lookup that cannot be
            # inferred safely from the command alone.
            project = cwd / entry.lstrip("+")
            if not project.is_dir():
                return []
            projects.append(project)
        return projects
    return [cwd]


def _surefire_receipt(trial: Path, argv: list[str], cwd: Path,
                      suffix: str, return_code: int,
                      cluster_test: str | None) -> dict[str, Any]:
    sources = []
    for project in _projects(argv, cwd):
        sources.extend(sorted((project / "target" / "surefire-reports")
                              .glob(f"TEST-*-{suffix}.xml")))
    if not sources:
        fallback = _maven_stdout_receipt(trial / "stdout.log", cluster_test, return_code)
        return {**fallback, "reports": [], "report_suffix": suffix}
    archived = trial / "junit-reports"
    archived.mkdir(exist_ok=True)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    reports = []
    for index, source in enumerate(sources):
        destination = archived / f"{index:03d}-{source.name}"
        shutil.copyfile(source, destination)
        try:
            suite = ET.parse(destination).getroot()
            if suite.tag != "testsuite":
                raise ValueError(f"unexpected XML root {suite.tag}")
            counts = {key: int(suite.attrib[key]) for key in totals}
            if any(value < 0 for value in counts.values()):
                raise ValueError("negative test count")
        except (ET.ParseError, KeyError, ValueError) as exc:
            return {"status": "report_invalid", "reason": str(exc),
                    "tests": totals["tests"], "failures": totals["failures"],
                    "errors": totals["errors"], "skipped": totals["skipped"],
                    "reports": reports, "report_suffix": suffix}
        for key, value in counts.items():
            totals[key] += value
        reports.append({"path": str(destination.relative_to(trial)),
                        "sha256": _sha256(destination), "counts": counts})
    return {**totals, "status": _counts_status(totals["tests"], totals["failures"],
                                                totals["errors"], totals["skipped"],
                                                return_code),
            "reports": reports, "report_suffix": suffix}


def _maven_stdout_receipt(stdout: Path, cluster_test: str | None,
                          return_code: int) -> dict[str, Any]:
    """Use the current trial's Surefire summary when XML is unavailable.

    Class-qualified lines are required for a passing fallback. This avoids
    accepting counts from a different reactor module or an unrelated test.
    """
    selected = cluster_test.split("#", 1)[0] if cluster_test else None
    pattern = re.compile(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), "
                         r"Skipped: (\d+)(?:.*? - in (\S+))?")
    rows = []
    with stdout.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = pattern.search(line)
            if match:
                rows.append((tuple(map(int, match.groups()[:4])), match.group(5)))
    selected_rows = [counts for counts, name in rows if name == selected]
    if not selected_rows:
        return {"status": "no_tests" if not rows else "report_missing",
                "source": "surefire_stdout", "tests": 0, "failures": 0,
                "errors": 0, "skipped": 0, "selected_class": selected,
                "summary_lines": len(rows)}
    totals = {key: sum(row[index] for row in selected_rows)
              for index, key in enumerate(("tests", "failures", "errors", "skipped"))}
    return {**totals, "status": _counts_status(totals["tests"], totals["failures"],
                                                totals["errors"], totals["skipped"],
                                                return_code),
            "source": "surefire_stdout", "selected_class": selected,
            "summary_lines": len(rows)}


def _hbase_receipt(stderr: Path, return_code: int) -> dict[str, Any]:
    marker = re.compile(r"^MALLORY_JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)$")
    found = []
    with stderr.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = marker.fullmatch(line.rstrip("\r\n"))
            if match:
                found.append(tuple(map(int, match.groups())))
    if len(found) != 1:
        return {"status": "report_missing" if not found else "report_ambiguous",
                "tests": 0, "failures": 0, "errors": 0, "skipped": 0,
                "marker_count": len(found)}
    tests, succeeded, failed = found[0]
    if tests < succeeded + failed:
        return {"status": "report_invalid", "tests": tests,
                "failures": failed, "errors": 0, "skipped": 0}
    return {"tests": tests, "succeeded": succeeded, "failures": failed,
            "errors": 0, "skipped": tests - succeeded - failed,
            "status": _counts_status(tests, failed, 0,
                                      tests - succeeded - failed, return_code),
            "marker": f"MALLORY_JUNIT found={tests} succeeded={succeeded} failed={failed}"}


def _solr_receipt(trial: Path, return_code: int) -> dict[str, Any]:
    result = trial / "pilot-result.json"
    log = trial / "junit.log"
    if not result.is_file() or not log.is_file():
        return {"status": "report_missing", "tests": 0, "failures": 0,
                "errors": 0, "skipped": 0}
    try:
        wrapper = json.loads(result.read_text(encoding="utf-8"))
        counts = wrapper["junit"]
        tests, failures, ignored = (int(counts[key]) for key in ("run", "failures", "ignored"))
        marker = re.compile(r"^MALLORY_TEST_RESULT run=(\d+) failures=(\d+) ignored=(\d+)$")
        matches = []
        assumptions = 0
        with log.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if line.startswith("MALLORY_TEST_ASSUMPTION "):
                    assumptions += 1
                match = marker.fullmatch(line.rstrip("\r\n"))
                if match:
                    matches.append(tuple(map(int, match.groups())))
        if len(matches) != 1 or matches[0] != (tests, failures, ignored):
            raise ValueError("wrapper counts do not match the JUnit log")
        if min(tests, failures, ignored) < 0 or failures + ignored > tests:
            raise ValueError("invalid test counts")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {"status": "report_invalid", "reason": str(exc),
                "tests": 0, "failures": 0, "errors": 0, "skipped": 0,
                "wrapper_sha256": _sha256(result), "junit_log_sha256": _sha256(log)}
    return {"tests": tests, "failures": failures, "errors": 0,
            "skipped": ignored + assumptions, "assumption_failures": assumptions,
            "status": ("no_tests" if assumptions else
                       _counts_status(tests, failures, 0, ignored, return_code)),
            "wrapper_sha256": _sha256(result), "junit_log_sha256": _sha256(log),
            "marker": f"MALLORY_TEST_RESULT run={tests} failures={failures} ignored={ignored}"}


def collect_junit_receipt(trial: Path, argv: list[str], cwd: Path,
                          return_code: int, report_suffix: str | None,
                          cluster_test: str | None = None) -> dict[str, Any]:
    """Capture test counts and bind the receipt to raw stdout/stderr bytes."""
    kind = runner_kind(argv)
    receipt: dict[str, Any] = {"schema_version": 1, "runner": kind,
                               "stdout_sha256": _sha256(trial / "stdout.log"),
                               "stderr_sha256": _sha256(trial / "stderr.log")}
    if kind == "surefire_xml":
        receipt.update(_surefire_receipt(trial, argv, cwd, report_suffix or "",
                                         return_code, cluster_test))
    elif kind == "hbase_junit_platform":
        receipt.update(_hbase_receipt(trial / "stderr.log", return_code))
    elif kind == "solr_junit_wrapper":
        receipt.update(_solr_receipt(trial, return_code))
    else:
        receipt.update({"status": "not_applicable", "tests": None,
                        "failures": None, "errors": None, "skipped": None})
    return receipt
