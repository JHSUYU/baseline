"""GraphChecker as Mallory runs it: a case's SEED and PLAN, its TARGET rows, and planted native runs.

Every call runs a GraphChecker command on a cluster node over ssh; inputs and
outputs live on the shared filesystem. A case's GraphChecker output (its static
scope, recording weave and the resolved target) is ``<work>/<case>/gc``.
"""

from __future__ import annotations

import getpass
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import settings


@dataclass(frozen=True)
class Case:
    case_id: str
    system: settings.System
    directory: Path     # the GraphChecker case directory (experiments/<system>/<dir>)
    argument: str       # the case's argument to its case.sh ('' when none)
    work: Path          # Mallory's work directory of this case

    @property
    def gc(self) -> Path:
        return self.work / "gc"

    @classmethod
    def resolve(cls, case_id: str, work: Path | None = None) -> "Case":
        system = settings.system_of(case_id)
        lib = system.checkout / "experiments/lib/case-id.sh"
        out = subprocess.run(
            ["bash", "-c", f'source {shlex.quote(str(lib))} && case_dir_of '
                           f'{shlex.quote(str(system.checkout))} {shlex.quote(case_id)}'],
            check=True, capture_output=True, text=True).stdout.split()
        if len(out) != 2:
            raise ValueError(f"GraphChecker names no case directory for {case_id}: {out}")
        return cls(case_id, system, Path(out[0]), "" if out[1] == "-" else out[1],
                   (work or settings.WORK) / case_id)


def _remote(node: str, case: Case, environment: dict[str, str], arguments: list[str],
            log: Path, timeout: int | None = None) -> int:
    """``run.sh <case dir> <arg> <arguments>`` on ``node`` with ``environment``; its exit."""
    env = " ".join(f"{k}={shlex.quote(v)}" for k, v in environment.items())
    command = (f"cd {shlex.quote(str(case.directory))} && env {env} bash "
               f"{shlex.quote(str(case.system.checkout / 'experiments/lib/run.sh'))} "
               f"{shlex.quote(str(case.directory))} {shlex.quote(case.argument)} "
               + " ".join(shlex.quote(a) for a in arguments))
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        try:
            return subprocess.run(["ssh", "-o", "BatchMode=yes", node, command],
                                  stdout=stream, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124


def prepare(case: Case, node: str) -> dict:
    """GraphChecker's SEED and PLAN of the case on ``node`` alone: its recording weave and target."""
    subprocess.run(["rm", "-rf", str(case.gc)], check=True)
    status = _remote(node, case, {
        "CAUSYNTH_OUTPUT_DIR": str(case.gc),
        "CAUSYNTH_CUSTOM_JDK_HOME": str(case.system.image),
        "CAUSYNTH_CAMPAIGN_STOP_AFTER": "PLAN",
        "CAUSYNTH_CAMPAIGN_WORKER_HOSTS": node,
    }, ["campaign"], case.work / "prepare.log")
    if status != 0:
        raise RuntimeError(f"{case.case_id}: GraphChecker's SEED/PLAN exited {status} "
                           f"(see {case.work / 'prepare.log'})")
    index = case.gc / "schedule/iteration-0000/runtime_workflow_schedule_index.json"
    target = json.loads(index.read_text())["target"]["occurrenceId"]
    rows = subprocess.run(
        [settings.JAVA, "-cp", str(case.system.jar), "edu.uva.liftlab.graphchecker.explore.TargetRows",
         str(case.gc / "static_scope_map.jsonl"), target],
        check=True, capture_output=True, text=True).stdout
    target_rows = [json.loads(line) for line in rows.splitlines() if line.strip()]
    prepared = {"case": case.case_id, "target_occurrence": target, "target_rows": target_rows}
    (case.work / "prepared.json").write_text(json.dumps(prepared, indent=2) + "\n")
    return prepared


def plant_run(case: Case, node: str, run: Path, plant: Path, bound_s: int) -> int:
    """One native run of the case's workload planting ``plant``, its markers observed."""
    scratch = settings.LOCAL_SCRATCH.format(user=getpass.getuser())
    return _remote(node, case, {
        "CAUSYNTH_OUTPUT_DIR": str(case.gc),
        "CAUSYNTH_WORKLOAD_JAVA_OPTS": "-Dcausynth.plant.observe=true",
        "CAUSYNTH_LOCAL_SCRATCH": scratch,
    }, ["plant-run", str(run), str(plant), str(bound_s)], run.parent / (run.name + ".log"),
        timeout=bound_s + 300)
