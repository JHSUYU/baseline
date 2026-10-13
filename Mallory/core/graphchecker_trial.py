"""Join one GraphChecker trace and keep static may-scope separate from edges.

This module consumes MessageDoors rows only. It never treats legacy Mallory
events or static may-relevance as observed causal edges or target evidence.
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def runtime_jar() -> Path:
    return (Path(__file__).resolve().parents[1] / "graphchecker-runtime" / "target" /
            "mallory-graphchecker-runtime-1.0-SNAPSHOT-all.jar")


def analyze_trial(trial: Path, target_site: str | list[str], prior_trace: Path | None = None,
                  jar: Path | None = None,
                  static_scope_map: Path | None = None) -> dict[str, Any]:
    selected_jar = (jar or runtime_jar()).resolve()
    if not selected_jar.is_file():
        raise FileNotFoundError(f"build Mallory/graphchecker-runtime first: {selected_jar}")
    trace = trial / "graphchecker-trace.jsonl"
    graph = trial / "graphchecker-graph.jsonl"
    feedback = trial / "graphchecker-feedback.json"
    if prior_trace is not None and not prior_trace.is_file():
        raise FileNotFoundError(f"prior GraphChecker trace missing: {prior_trace}")
    if static_scope_map is not None and not static_scope_map.is_file():
        raise FileNotFoundError(f"GraphChecker static scope map missing: {static_scope_map}")
    # TrialGraphMain reads plain JSONL. A healthy seed is stored durably as
    # gzip, so materialize it only for this analysis invocation and remove it
    # even when Java fails. The current trial trace remains plain until its
    # result and archive receipts are complete.
    scratch = Path("/dev/shm") if Path("/dev/shm").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="mallory-gc-prior-", dir=scratch) as temp:
        prior_input = prior_trace
        if prior_trace is not None and prior_trace.suffix == ".gz":
            prior_input = Path(temp) / "prior.jsonl"
            with gzip.open(prior_trace, "rb") as source, prior_input.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        # A full static scope can yield a large original-JUnit trace. Bound
        # graph-builder heap independently of the workload JVM and allow two
        # streaming passes over the current and prior traces to finish.
        sites = target_site if isinstance(target_site, list) else [target_site]
        if not sites:
            raise ValueError("GraphChecker analysis needs a target site")
        target_arg = json.dumps(sites) if len(sites) > 1 else sites[0]
        command = ["java", "-Xmx6g", "-jar", str(selected_jar), str(trace), str(graph),
                   str(feedback), target_arg]
        if prior_input is not None or static_scope_map is not None:
            command.append(str(prior_input) if prior_input is not None else "-")
        if static_scope_map is not None:
            command.append(str(static_scope_map))
        subprocess.run(command, check=True, timeout=300, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)
    value = json.loads(feedback.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError(f"invalid GraphChecker trial feedback: {feedback}")
    if value.get("targetSite") != sites[0]:
        raise ValueError(f"GraphChecker feedback target differs from {target_site}: {feedback}")
    if len(sites) > 1 and value.get("configuredTargetSites") != sites:
        raise ValueError(f"GraphChecker feedback omitted target guards: {feedback}")
    return value
