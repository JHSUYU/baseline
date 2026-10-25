"""One Mallory campaign over one case: graph-guided fault trials until the target fails.

1. The healthy run: the case's workload planted with only its TARGET rows; its
   graph starts the corpus and its fault markers are the first fault points.
2. Every trial plants one more fault after a corpus run's last fault (at most
   ``max_faults``), at a fault point that run evaluated, chosen by the Q-policy
   from the state the point was reached in.
3. A finished trial's graph is compared with every graph so far: its new
   happens-before edges are the reward; a trial with new edges joins the corpus,
   so its later fault points become choices.
4. The oracle is GraphChecker's: the target took its fatal arm at the declared
   occurrence (PLANT_FATAL atAnchor) in a run where every planted fault applied.

As in Mallory, one trial runs at a time and the next choice uses everything the
earlier trials showed; a campaign runs on one node, so different cases (systems)
run side by side on different nodes.
"""

from __future__ import annotations

import gzip
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import engine, faults, graph, policy, settings


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

    # -- paths ---------------------------------------------------------------
    @property
    def runs(self) -> Path:
        return self.case.work / "runs"

    @property
    def checkpoint(self) -> Path:
        return self.case.work / "state.json"

    # -- one native run -------------------------------------------------------
    def _run(self, name: str, plan: tuple[faults.FaultPoint, ...], node: str
             ) -> tuple[int, graph.RunGraph | None, set[int]]:
        run = self.runs / name
        shutil.rmtree(run, ignore_errors=True)
        plant = self.runs / (name + ".plant.jsonl")
        planted = faults.write_plant(plant, plan, self.target_rows)
        status = engine.plant_run(self.case, node, run, plant, self.budget.trial_bound_s)
        trace = run / "runtime_trace.jsonl"
        if not trace.is_file():
            return status, None, set(planted)
        built = graph.build(trace)
        with trace.open("rb") as source, gzip.open(str(trace) + ".gz", "wb", compresslevel=3) as sink:
            shutil.copyfileobj(source, sink)
        trace.unlink()
        return status, built, set(planted)

    # -- the corpus -----------------------------------------------------------
    def _admit(self, name: str, plan: tuple[faults.FaultPoint, ...], run: graph.RunGraph) -> None:
        """A corpus run offers every fault point after its last applied fault."""
        after = max((p.seq for p in plan), default=-1)
        if plan:
            applied = [seq for seq, (_, label) in run.events if label.startswith("fault ")]
            after = max(applied, default=after)
        for point in faults.points(run, after_seq=after):
            if not faults.compatible(plan, point) or len(plan) >= self.budget.max_faults:
                continue
            candidate_plan = plan + (point,)
            identifier = faults.plan_id(candidate_plan)
            if identifier in self.tried:
                continue
            state = policy.state_key(point, run.timeline_before(
                point.node, point.seq, policy.TIMELINE_DEPTH))
            self.candidates.append(Candidate(candidate_plan, state, name))

    def _choose(self) -> Candidate | None:
        self.candidates = [c for c in self.candidates if faults.plan_id(c.plan) not in self.tried]
        if not self.candidates:
            return None
        index = self.q.choose(
            self.candidates, state_of=lambda c: c.state, action_of=lambda c: c.point.action,
            tried_count=lambda c: self.q.tries.get(c.state, {}).get(c.point.action, 0))
        chosen = self.candidates.pop(index)
        self.tried.add(faults.plan_id(chosen.plan))
        return chosen

    # -- trials ---------------------------------------------------------------
    def _trial(self, candidate: Candidate, number: int) -> Trial:
        trial = Trial(name=f"t{number:05d}", plan=candidate.plan, state=candidate.state,
                      node=self.node, started=time.time())
        status, run, planted = self._run(trial.name, candidate.plan, self.node)
        trial.ended, trial.exit = time.time(), status
        if run is None:
            return trial
        trial.applied = planted <= run.applied_rows
        trial.fatal = run.fatal and trial.applied
        trial.new_edges = len(run.edges - self.corpus_edges)
        trial.graph_added = len(run.edges - self.healthy_edges)
        trial.graph_removed = len(self.healthy_edges - run.edges)
        self.corpus_edges |= run.edges
        trial.reward = policy.reward(trial.new_edges) if trial.applied else 0.0
        following = [p for p in faults.points(run, after_seq=candidate.point.seq)
                     if p.node == candidate.point.node][:1]
        next_state = (policy.state_key(following[0], run.timeline_before(
            following[0].node, following[0].seq, policy.TIMELINE_DEPTH)) if following else None)
        self.q.update(candidate.state, candidate.point.action, trial.reward, next_state)
        if trial.applied and trial.new_edges > 0:
            self._admit(trial.name, candidate.plan, run)
        return trial

    def _save(self) -> None:
        state = {
            "case": self.case.case_id, "elapsed_s": round(self.elapsed, 1),
            "trials": [_trial_json(t) for t in self.trials],
            "detections": [t.name for t in self.detections],
            "tried": sorted(self.tried), "corpus_edges": len(self.corpus_edges),
            "candidates": len(self.candidates), "policy": self.q.to_json(),
        }
        tmp = self.checkpoint.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1) + "\n")
        tmp.replace(self.checkpoint)

    def run(self) -> dict:
        prepared_file = self.case.work / "prepared.json"
        prepared = (json.loads(prepared_file.read_text()) if prepared_file.is_file()
                    else engine.prepare(self.case, self.node))
        self.target_rows = prepared["target_rows"]
        started = time.time()
        status, healthy, _ = self._run("healthy", (), self.node)
        # A trial may take a few times the healthy run (a failure's retries and
        # timeouts), never the whole bound when a cluster hangs at its shutdown.
        healthy_s = time.time() - started
        self.budget.trial_bound_s = min(self.budget.trial_bound_s, max(120, int(4 * healthy_s)))
        if healthy is None:
            raise RuntimeError(f"{self.case.case_id}: the healthy run wrote no trace (exit {status})")
        if healthy.fatal:
            raise RuntimeError(f"{self.case.case_id}: the target fails without any fault")
        self.healthy_edges = set(healthy.edges)
        self.corpus_edges = set(healthy.edges)
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


def _trial_json(trial: Trial) -> dict:
    return {"name": trial.name, "plan": faults.to_json(trial.plan), "state": trial.state,
            "node": trial.node, "seconds": round(trial.ended - trial.started, 1),
            "exit": trial.exit, "applied": trial.applied, "fatal": trial.fatal,
            "new_edges": trial.new_edges, "graph_added": trial.graph_added,
            "graph_removed": trial.graph_removed, "reward": round(trial.reward, 4)}


def summary(campaign: Campaign) -> dict:
    first = campaign.detections[0] if campaign.detections else None
    result = {
        "case": campaign.case.case_id,
        "detected": first is not None,
        "trials": len(campaign.trials),
        "applied_trials": sum(t.applied for t in campaign.trials),
        "elapsed_s": round(campaign.elapsed, 1),
        "corpus_edges": len(campaign.corpus_edges),
        "detection": None if first is None else {
            "trial": first.name,
            "trial_index": campaign.trials.index(first) + 1,
            "seconds_from_start": round(first.ended - min(t.started for t in campaign.trials), 1),
            "faults": [p.action for p in first.plan],
            "plan": faults.to_json(first.plan),
            "graph_added": first.graph_added, "graph_removed": first.graph_removed,
        },
    }
    (campaign.case.work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
