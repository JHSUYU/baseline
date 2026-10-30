"""One Mallory campaign over one case: graph-guided fault trials until the target fails.

1. The healthy run: the case's workload planted with only its TARGET rows; its
   graph starts the corpus and its fault markers are the first fault points.
2. Every trial plants one more fault after a corpus run's last fault (at most
   ``max_faults``), at a fault point that run evaluated, chosen by the Q-policy
   from the state the point was reached in.
3. A finished trial's graph is compared with every graph so far: its new
   happens-before edges are the reward; a trial with new edges joins the corpus,
   so its later fault points become choices.
4. The oracle is GraphChecker's target check, counted: in a run where every
   planted fault applied, the target took its fatal arm (PLANT_FATAL, any
   occurrence) more often than in any healthy run. A workload whose own
   fault-free run fails the check (a test of the failure path, or two
   sessions contending for a lock) counts only further failures; runs go on
   past the declared occurrence (causynth.plant.continue), so a failure that
   repeats is counted whole; where healthy runs fail it k > 0 times, a
   detection fails it more than 2k times (``failure_threshold``).

As in Mallory, one trial runs at a time and the next choice uses everything the
earlier trials showed; a campaign runs on one node, so different cases (systems)
run side by side on different nodes.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import engine, faults, graph, policy, settings


HEALTHY_RUNS = 3


def _visible(path: Path, wait_s: float = 60.0) -> bool:
    """Whether a file another node wrote is there, waiting out this host's NFS caches
    (listing its directory revalidates them) for at most ``wait_s``."""
    deadline = time.time() + wait_s
    while True:
        try:
            os.listdir(path.parent)
        except OSError:
            pass
        if path.is_file():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(2)


def failure_threshold(healthy: int) -> int:
    """The most fatal arms a run may take and still be no detection.

    A workload whose fault-free runs never fail the check detects at its first
    failure. One whose fault-free runs fail it k times (two sessions taking
    turns at a lock, a test of the failure path) can fail it a few times more
    when a fault only delays a step; a detection fails it more than twice as
    often.
    """
    return 2 * healthy


@dataclass
class Budget:
    trials: int = 600
    seconds: int = 4 * 3600
    max_faults: int = 3
    trial_bound_s: int = 900
    stop_at_detection: bool = True


@dataclass
class Candidate:
    plan: tuple[faults.FaultPoint, ...]   # the parent's faults plus the new one
    state: str                           # the state the new fault is chosen in
    parent: str                          # the corpus run it extends

    @property
    def point(self) -> faults.FaultPoint:
        return self.plan[-1]


@dataclass
class Trial:
    name: str
    plan: tuple[faults.FaultPoint, ...]
    state: str
    node: str
    started: float
    ended: float = 0.0
    exit: int = -1
    applied: bool = False
    fatal: bool = False
    new_edges: int = 0
    graph_added: int = 0
    graph_removed: int = 0
    reward: float = 0.0
    fatal_at: list[str] = field(default_factory=list)   # occurrences of its target fatal arms


@dataclass
class Campaign:
    case: engine.Case
    budget: Budget = field(default_factory=Budget)
    node: str = settings.NODES[0]
    seed: int = 0

    def __post_init__(self) -> None:
        self.q = policy.QPolicy(seed=self.seed)
        self.corpus_edges: set[graph.Edge] = set()
        self.healthy_edges: set[graph.Edge] = set()
        self.candidates: list[Candidate] = []
        self.tried: set[str] = set()
        self.trials: list[Trial] = []
        self.detections: list[Trial] = []
        self.elapsed = 0.0
        self.target_rows: list[dict] = []
        self.healthy_noise = 0
        self.prepare_s: float | None = None    # GraphChecker's SEED and PLAN of the case
        self.healthy_s = 0.0                   # the two healthy runs
        self.healthy_fatal = 0                 # target fatal arms of a healthy run, at most
        self.started = 0.0

    # -- paths ---------------------------------------------------------------
    @property
    def directory(self) -> Path:
        """This campaign's runs, checkpoint and result; the case's GraphChecker output is shared."""
        return self.case.work / f"seed-{self.seed}"

    @property
    def runs(self) -> Path:
        return self.directory / "runs"

    @property
    def checkpoint(self) -> Path:
        return self.directory / "state.json"

    # -- one native run -------------------------------------------------------
    def _run(self, name: str, plan: tuple[faults.FaultPoint, ...], node: str
             ) -> tuple[int, graph.RunGraph | None, bool]:
        """One native run planting ``plan``: its exit, its graph, whether every fault applied."""
        run = self.runs / name
        shutil.rmtree(run, ignore_errors=True)
        plant = self.runs / (name + ".plant.jsonl")
        planted, planted_outside = faults.write_plant(plant, plan, self.target_rows)
        trace = run / "runtime_trace.jsonl"
        outside = graph.outside_log(trace)
        outside.unlink(missing_ok=True)
        # The node writes the run over NFS. A name this host looked up while it did not
        # exist stays absent in this host's lookup cache for up to a minute (NFSv3,
        # liftlab), so the run directory and the outside log exist here before the run.
        run.mkdir(parents=True)
        outside.touch()
        status = engine.plant_run(self.case, node, run, plant, faults.outside_plant(plant),
                                  outside, self.budget.trial_bound_s)
        if not _visible(trace):
            return status, None, False
        built = graph.build(trace, outside)
        for path in (trace, outside):
            if path.is_file():
                with path.open("rb") as source, \
                        gzip.open(str(path) + ".gz", "wb", compresslevel=3) as sink:
                    shutil.copyfileobj(source, sink)
                path.unlink()
        applied = (set(planted) <= built.applied_rows and
                   planted_outside <= built.outside_applied)
        return status, built, applied

    # -- the corpus -----------------------------------------------------------
    def _admit(self, name: str, plan: tuple[faults.FaultPoint, ...], run: graph.RunGraph) -> None:
        """A corpus run offers every fault point after its last applied fault."""
        after = faults.evaluated_at(run, plan) if plan else -1
        for point in faults.points(run, after_nanos=after):
            if not faults.compatible(plan, point) or len(plan) >= self.budget.max_faults:
                continue
            candidate_plan = plan + (point,)
            identifier = faults.plan_id(candidate_plan)
            if identifier in self.tried:
                continue
            state = policy.state_key(point, run.timeline_before(
                point.line, point.seq, policy.TIMELINE_DEPTH))
            self.candidates.append(Candidate(candidate_plan, state, name))

    def _choose(self) -> Candidate | None:
        self.candidates = [c for c in self.candidates if faults.plan_id(c.plan) not in self.tried]
        if not self.candidates:
            return None
        index = self.q.choose(
            self.candidates, state_of=lambda c: c.state, action_of=lambda c: c.point.action,
            tried_count=lambda c: self.q.tries.get(c.state, {}).get(c.point.action, 0),
            identity_of=lambda c: faults.plan_id(c.plan))
        chosen = self.candidates.pop(index)
        self.tried.add(faults.plan_id(chosen.plan))
        return chosen

    # -- trials ---------------------------------------------------------------
    def _trial(self, candidate: Candidate, number: int) -> Trial:
        trial = Trial(name=f"t{number:05d}", plan=candidate.plan, state=candidate.state,
                      node=self.node, started=time.time())
        status, run, applied = self._run(trial.name, candidate.plan, self.node)
        trial.ended, trial.exit = time.time(), status
        if run is None:
            return trial
        trial.applied = applied
        trial.fatal = trial.applied and len(run.fatal_rows) > failure_threshold(self.healthy_fatal)
        trial.fatal_at = [row.get("occurrenceAddress", "") for row in run.fatal_rows]
        trial.new_edges = len(run.edges - self.corpus_edges)
        trial.graph_added = len(run.edges - self.healthy_edges)
        trial.graph_removed = len(self.healthy_edges - run.edges)
        self.corpus_edges |= run.edges
        trial.reward = policy.reward(trial.new_edges, self.healthy_noise) if trial.applied else 0.0
        following = [p for p in faults.points(run, faults.evaluated_at(run, (candidate.point,)))
                     if p.node == candidate.point.node][:1]
        next_state = (policy.state_key(following[0], run.timeline_before(
            following[0].line, following[0].seq, policy.TIMELINE_DEPTH)) if following else None)
        self.q.update(candidate.state, candidate.point.action, trial.reward, next_state)
        if trial.applied and trial.new_edges > self.healthy_noise:
            self._admit(trial.name, candidate.plan, run)
        return trial

    def _save(self) -> None:
        state = {
            "case": self.case.case_id, "elapsed_s": round(self.elapsed, 1),
            "trials": [_trial_json(t) for t in self.trials],
            "detections": [t.name for t in self.detections],
            "tried": sorted(self.tried), "corpus_edges": len(self.corpus_edges),
            "healthy_noise_edges": self.healthy_noise, "seed": self.seed,
            "healthy_fatal_arms": self.healthy_fatal,
            "prepare_s": self.prepare_s, "healthy_s": round(self.healthy_s, 1),
            "candidates": len(self.candidates), "policy": self.q.to_json(),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.checkpoint.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1) + "\n")
        tmp.replace(self.checkpoint)

    def run(self) -> dict:
        prepared_file = self.case.work / "prepared.json"
        prepared = (json.loads(prepared_file.read_text()) if prepared_file.is_file()
                    else engine.prepare(self.case, self.node))
        self.target_rows = prepared["target_rows"]
        self.prepare_s = prepared.get("seconds")
        started = self.started = time.time()
        status, healthy, _ = self._run("healthy", (), self.node)
        # A trial may take a few times the healthy run (a failure's retries and
        # timeouts), never the whole bound when a cluster hangs at its shutdown.
        healthy_s = time.time() - started
        self.budget.trial_bound_s = min(self.budget.trial_bound_s, max(120, int(4 * healthy_s)))
        if healthy is None:
            raise RuntimeError(f"{self.case.case_id}: the healthy run wrote no trace (exit {status})")
        # More healthy runs: what differs between runs with no fault is the workload's
        # own nondeterminism, never a fault's effect, so the corpus starts with all of
        # them, the noise is the most another adds to the first, and the oracle's
        # baseline is the most fatal arms any of them took.
        others = [run for run in (self._run(f"healthy-{k}", (), self.node)[1]
                                  for k in range(2, HEALTHY_RUNS + 1)) if run is not None]
        self.healthy_s = time.time() - started
        self.healthy_fatal = max(len(run.fatal_rows) for run in [healthy, *others])
        self.healthy_edges = set(healthy.edges)
        self.corpus_edges = set(healthy.edges).union(*(run.edges for run in others))
        self.healthy_noise = max((len(run.edges - healthy.edges) for run in others), default=0)
        self._admit("healthy", (), healthy)
        while (len(self.trials) < self.budget.trials
               and time.time() - started < self.budget.seconds
               and not (self.detections and self.budget.stop_at_detection)):
            candidate = self._choose()
            if candidate is None:
                break
            trial = self._trial(candidate, len(self.trials) + 1)
            self.trials.append(trial)
            if trial.fatal:
                self.detections.append(trial)
            self.elapsed = time.time() - started
            self._save()
        self.elapsed = time.time() - started
        self._save()
        return summary(self)


class Sweep(Campaign):
    """Every single fault of one healthy run, once each: how many expose the target.

    Not a campaign and no part of Mallory: the ground truth a campaign's time to
    detect is read against (a uniformly random choice among ``points`` faults of
    which ``k`` expose the target needs (points + 1) / (k + 1) trials on average).
    """

    @property
    def directory(self) -> Path:
        return self.case.work / "sweep"

    def sweep(self, limit: int | None = None, reverse: bool = False) -> dict:
        """``reverse`` runs the points from the last, beside a forward sweep (its own record)."""
        prepared = json.loads((self.case.work / "prepared.json").read_text())
        self.target_rows = prepared["target_rows"]
        record = self.directory / ("sweep-reverse.json" if reverse else "sweep.json")
        other = self.directory / ("sweep.json" if reverse else "sweep-reverse.json")
        done = json.loads(record.read_text()) if record.is_file() else {"points": [], "runs": {}}
        if reverse and "healthy_s" not in done and other.is_file():
            done["healthy_s"] = json.loads(other.read_text()).get("healthy_s")
        healthy_trace = self.runs / "healthy" / "runtime_trace.jsonl.gz"
        if not healthy_trace.is_file():
            started = time.time()
            status, healthy, _ = self._run("healthy", (), self.node)
            if healthy is None:
                raise RuntimeError(f"{self.case.case_id}: unusable healthy run (exit {status})")
            done["healthy_s"] = round(time.time() - started, 1)
            done["healthy_fatal"] = len(healthy.fatal_rows)
        self.budget.trial_bound_s = min(self.budget.trial_bound_s,
                                        max(120, int(4 * done.get("healthy_s", 30))))
        healthy = graph.build(healthy_trace, Path(str(graph.outside_log(
            self.runs / "healthy" / "runtime_trace.jsonl")) + ".gz"))
        points = faults.points(healthy)
        done["points"] = faults.to_json(tuple(points))
        order = list(enumerate(points[:limit]))
        for index, point in (reversed(order) if reverse else order):
            name = f"s{index:05d}"
            if name in done["runs"]:
                continue
            if other.is_file() and name in json.loads(other.read_text())["runs"]:
                break                         # the two sweeps met
            started = time.time()
            status, run, applied = self._run(name, (point,), self.node)
            done["runs"][name] = {"action": point.action, "outside": point.outside,
                                  "exit": status, "seconds": round(time.time() - started, 1),
                                  "applied": applied,
                                  "fatal": bool(run and applied and
                                                len(run.fatal_rows) >
                                                failure_threshold(done.get("healthy_fatal", 0)))}
            self.directory.mkdir(parents=True, exist_ok=True)
            record.with_suffix(".tmp").write_text(json.dumps(done, indent=1) + "\n")
            record.with_suffix(".tmp").replace(record)
        merged = dict(done["runs"])
        if other.is_file():
            merged.update(json.loads(other.read_text())["runs"])
        runs = merged.values()
        return {"case": self.case.case_id, "points": len(points), "run": len(merged),
                "applied": sum(r["applied"] for r in runs), "expose": sum(r["fatal"] for r in runs),
                "exposing": sorted(name for name, r in merged.items() if r["fatal"])}


class Replay(Campaign):
    """A campaign's detecting plan run again on its node, ``repeats`` times: how often it detects.

    Not part of Mallory's search: the check a candidate gets before it is called a
    bug (CrashFuzz's ``replay``), through the same plant, matching and oracle
    (the campaign's healthy fatal arms set the threshold).
    """

    generalize: bool = False

    @property
    def directory(self) -> Path:
        return self.case.work / f"seed-{self.seed}" / ("replay-generalized" if self.generalize
                                                        else "replay")

    def replay(self, repeats: int) -> dict:
        """With ``generalize``, every fault is planted at all its siblings in the detecting run
        (``faults.generalized``), and a run applies a fault when it applied any of them."""
        campaign = self.case.work / f"seed-{self.seed}"
        detection = json.loads((campaign / "result.json").read_text()).get("detection")
        if not detection:
            raise RuntimeError(f"{self.case.case_id}: seed {self.seed} detected nothing to replay")
        state = json.loads((campaign / "state.json").read_text())
        healthy_fatal = state.get("healthy_fatal_arms", 0)
        self.target_rows = json.loads((self.case.work / "prepared.json").read_text())["target_rows"]
        # the campaign's bound: four times one healthy run, at least 120 s
        self.budget.trial_bound_s = min(self.budget.trial_bound_s,
                                        max(120, int(4 * state["healthy_s"] / HEALTHY_RUNS)))
        plan = faults.from_json(detection["plan"])
        groups = [(point,) for point in plan]
        if self.generalize:
            trace = campaign / "runs" / detection["trial"] / "runtime_trace.jsonl.gz"
            groups = faults.generalized(trace, plan)
            plan = tuple(point for group in groups for point in group)
        rows = {}                             # a window fault's plant row: its group
        for point, index in ((p, i) for i, g in enumerate(groups) for p in g):
            if not point.outside:
                rows[len(rows)] = index
        runs = []
        for k in range(1, repeats + 1):
            started = time.time()
            status, run, applied = self._run(f"r{k:02d}", plan, self.node)
            if run is not None and self.generalize:
                hit = {rows[row] for row in run.applied_rows if row in rows}
                hit |= {i for i, g in enumerate(groups) if g[0].outside and
                        (g[0].site, g[0].place, g[0].invocation) in run.outside_applied}
                applied = len(hit) == len(groups)
            fatal = len(run.fatal_rows) if run else 0
            runs.append({"run": f"r{k:02d}", "exit": status, "seconds": round(time.time() - started, 1),
                         "applied": applied, "fatal_arms": fatal,
                         "detected": bool(run and applied and fatal > failure_threshold(healthy_fatal))})
        record = {"case": self.case.case_id, "seed": self.seed, "trial": detection["trial"],
                  "faults": detection["faults"], "generalized": self.generalize,
                  "planted": [len(group) for group in groups], "healthy_fatal_arms": healthy_fatal,
                  "repeats": repeats, "applied": sum(r["applied"] for r in runs),
                  "detected": sum(r["detected"] for r in runs), "runs": runs}
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "replay.json").write_text(json.dumps(record, indent=2) + "\n")
        return record


def _trial_json(trial: Trial) -> dict:
    return {"name": trial.name, "plan": faults.to_json(trial.plan), "state": trial.state,
            "node": trial.node, "seconds": round(trial.ended - trial.started, 1),
            "exit": trial.exit, "applied": trial.applied, "fatal": trial.fatal,
            "new_edges": trial.new_edges, "graph_added": trial.graph_added,
            "graph_removed": trial.graph_removed, "reward": round(trial.reward, 4),
            "fatal_at": trial.fatal_at}


def summary(campaign: Campaign) -> dict:
    first = campaign.detections[0] if campaign.detections else None
    result = {
        "case": campaign.case.case_id,
        "seed": campaign.seed,
        "detected": first is not None,
        "trials": len(campaign.trials),
        "applied_trials": sum(t.applied for t in campaign.trials),
        "prepare_s": campaign.prepare_s,
        "healthy_s": round(campaign.healthy_s, 1),
        "elapsed_s": round(campaign.elapsed, 1),
        "corpus_edges": len(campaign.corpus_edges),
        "detection": None if first is None else {
            "trial": first.name,
            "trial_index": campaign.trials.index(first) + 1,
            # the trials alone; with the healthy runs; with GraphChecker's SEED and PLAN too
            "seconds_from_start": round(first.ended - min(t.started for t in campaign.trials), 1),
            "seconds_with_healthy": round(first.ended - campaign.started, 1),
            "seconds_with_prepare": (round(first.ended - campaign.started + campaign.prepare_s, 1)
                                     if campaign.prepare_s is not None else None),
            "faults": [p.action for p in first.plan],
            "plan": faults.to_json(first.plan),
            "graph_added": first.graph_added, "graph_removed": first.graph_removed,
            "fatal_at": first.fatal_at,
        },
    }
    campaign.directory.mkdir(parents=True, exist_ok=True)
    (campaign.directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
