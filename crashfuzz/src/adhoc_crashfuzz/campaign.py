"""The target-guided CrashFuzz loop over a real cluster driver."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
import time
from typing import Dict, List, Mapping, Optional, Sequence, Set

from .backend import CommandResult, DockerBackend
from .controller import EventServer, FaultController
from .feedback import Candidate, Coverage, Delta, Queue
from .graph import CausalGraph, Closure, build_graph, read_events, target_closure
from .model import FaultSequence, PointKey, TargetSpec
from .mutation import NodeGroup, ObservedPoint, mutate_one_fault


@dataclass(frozen=True)
class Settings:
    target: TargetSpec
    output_dir: Path
    backend: DockerBackend
    groups: tuple
    roles: Mapping[str, str]
    controller_bind: str = "0.0.0.0"
    controller_advertise: str = "host.docker.internal"
    controller_port: int = 0
    max_runs: int = 100
    max_faults: int = 6
    max_candidates_per_run: int = 300
    max_crash_carry_per_depth: int = 12
    exploration_probability: float = 0.15
    random_seed: int = 0
    replay_count: int = 2
    matched_trial_limit: int = 0  # zero keeps exploring until max_runs
    allow_unreached_seed: bool = False
    max_site_occurrence: int = 0  # zero permits every observed occurrence

    @classmethod
    def from_file(cls, path: Path) -> "Settings":
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        target = TargetSpec(**data["target"])
        docker = data["docker"]
        containers = docker["containers"]
        groups = tuple(NodeGroup(frozenset(row["members"]),
                                 int(row["max_down"]))
                       for row in data["node_groups"])
        backend = DockerBackend(
            containers=containers, prepare=docker["prepare"],
            workload=docker["workload"], checker=docker.get("checker"),
            cwd=path.parent.resolve(),
            workload_timeout_s=int(docker.get("workload_timeout_s", 300)),
            command_timeout_s=int(docker.get("command_timeout_s", 120)),
            docker_command=docker.get("command", ["docker"]))
        search = data.get("search", {})
        controller = data.get("controller", {})
        output = Path(data.get("output_dir", "out"))
        if not output.is_absolute():
            output = path.parent / output
        return cls(
            target=target, output_dir=output.resolve(), backend=backend,
            groups=groups, roles=data.get("roles", {}),
            controller_bind=controller.get("bind", "0.0.0.0"),
            controller_advertise=controller.get("advertise",
                                                "host.docker.internal"),
            controller_port=int(controller.get("port", 0)),
            max_runs=int(search.get("max_runs", 100)),
            max_faults=int(search.get("max_faults", 6)),
            max_candidates_per_run=int(search.get("max_candidates_per_run", 300)),
            max_crash_carry_per_depth=int(search.get("max_crash_carry_per_depth", 12)),
            exploration_probability=float(search.get("exploration_probability", 0.15)),
            random_seed=int(search.get("random_seed", 0)),
            replay_count=int(search.get("replay_count", 2)),
            matched_trial_limit=int(search.get("matched_trial_limit", 0)),
            allow_unreached_seed=bool(search.get("allow_unreached_seed", False)),
            max_site_occurrence=int(search.get("max_site_occurrence", 0)),
        )


@dataclass(frozen=True)
class Trial:
    run_id: str
    sequence: FaultSequence
    points: Sequence[ObservedPoint]
    last_injected_order: int
    triggered: bool
    closure: Closure
    graph: CausalGraph
    workload: CommandResult
    checker: Optional[CommandResult]
    duration_s: float
    error: str = ""


def _command(row: Optional[CommandResult]) -> Optional[dict]:
    return None if row is None else {
        "returncode": row.returncode, "stdout": row.stdout,
        "stderr": row.stderr, "timed_out": row.timed_out}


class Campaign:
    def __init__(self, settings: Settings):
        if (settings.max_runs < 1 or settings.max_faults < 1
                or settings.matched_trial_limit < 0):
            raise ValueError("max_runs and max_faults must be positive")
        self.settings = settings
        self.queue = Queue(settings.random_seed,
                           settings.exploration_probability)
        self.coverage = Coverage()
        self._rng = random.Random(settings.random_seed)
        self._seen_points: Set[PointKey] = set()
        self._seed_points: Set[PointKey] = set()
        self._crash_carry: Dict[int, int] = {}
        self._trial_number = 0

    def _trial(self, sequence: FaultSequence, label: str = "run") -> Trial:
        self._trial_number += 1
        run_id = "{}-{:05d}".format(label, self._trial_number)
        run_dir = self.settings.output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        controller = FaultController(sequence, self.settings.backend,
                                     run_dir / "point-events.jsonl")
        started = time.monotonic()
        with EventServer(controller, self.settings.controller_bind,
                         self.settings.controller_port) as server:
            prepared = self.settings.backend.prepare(
                run_dir, self.settings.controller_advertise, server.port)
            if prepared.returncode:
                raise RuntimeError("cluster prepare failed in {}: {}".format(
                    run_id, prepared.stderr or prepared.stdout))
            workload = self.settings.backend.run_workload(run_dir)
            checker = (self.settings.backend.check(run_dir)
                       if controller.complete and not workload.timed_out
                       else None)
        duration_s = time.monotonic() - started
        events = read_events(run_dir / "traces")
        graph = build_graph(events)
        closure = target_closure(graph, self.settings.target,
                                 self.settings.roles)
        trial = Trial(run_id, sequence, tuple(controller.points),
                      controller.last_injected_order, controller.complete,
                      closure, graph, workload, checker, duration_s,
                      controller.error)
        result = {
            "run_id": run_id, "sequence": sequence.to_dict(),
            "triggered": trial.triggered, "injected": [
                {"action": action.to_dict(), "order": order,
                 "match_mode": controller.match_modes[order]}
                for action, order in controller.injected],
            "point_count": len(trial.points), "target_reached": closure.reached,
            "target_fatal": closure.fatal,
            "closure_nodes": len(closure.nodes),
            "closure_edges": len(closure.edges),
            "closure_blocks": len(closure.block_features),
            "closure_branch_outcomes": len(closure.branch_features),
            "global_blocks": len({event.site for event, _ in graph.blocks}
                                 | graph.global_blocks),
            "global_branch_outcomes": len({
                event.site + "|" + event.outcome
                for event, _ in graph.branches} | graph.global_branches),
            "graph_gaps": graph.gaps[:200],
            "workload": _command(workload), "checker": _command(checker),
            "duration_s": duration_s, "controller_error": controller.error,
        }
        with (run_dir / "result.json").open("w", encoding="utf-8") as out:
            json.dump(result, out, indent=2, sort_keys=True)
            out.write("\n")
        return trial

    def _offer_mutations(self, trial: Trial, delta: Delta,
                         force: bool = False) -> int:
        if not trial.triggered:
            return 0
        last_crash = (bool(trial.sequence.actions)
                      and trial.sequence.actions[-1].kind == "CRASH")
        depth = len(trial.sequence.actions)
        carry = self._crash_carry.get(depth, 0)
        retain = (force or trial.closure.fatal or delta.gained
                  or (last_crash and carry
                      < self.settings.max_crash_carry_per_depth))
        if not retain:
            return 0
        if last_crash and not delta.gained:
            self._crash_carry[depth] = carry + 1

        candidate_points = trial.points
        if self.settings.max_site_occurrence:
            candidate_points = [point for point in trial.points
                                if point.site_occurrence
                                <= self.settings.max_site_occurrence]
        mutations = mutate_one_fault(
            trial.sequence, candidate_points,
            self.settings.backend.containers, self.settings.groups,
            self.settings.max_faults, trial.last_injected_order)
        # Evaluate every observed candidate, then bound the queue contribution
        # while keeping some unranked alternatives for graph discovery.
        ranked = []
        for seq in mutations:
            last = seq.actions[-1]
            point = last.trigger
            ranked.append(Candidate(
                seq, trial.run_id,
                closure_point=point in trial.closure.points,
                recovery_point=point not in self._seed_points,
                new_point=point not in self._seen_points,
                parent_new_edges=len(delta.edges),
                parent_new_nodes=len(delta.nodes),
                parent_new_blocks=len(delta.blocks),
                parent_new_branches=len(delta.branches),
                parent_new_global_blocks=len(delta.global_blocks),
                parent_seconds=trial.duration_s))
        self._rng.shuffle(ranked)
        ranked.sort(key=lambda candidate: candidate.score(), reverse=True)
        limit = self.settings.max_candidates_per_run
        if limit > 0 and len(ranked) > limit:
            favored = ranked[:int(limit * 0.8)]
            remaining = ranked[int(limit * 0.8):]
            favored.extend(self._rng.sample(remaining, limit - len(favored)))
            ranked = favored
        added = sum(self.queue.add(candidate) for candidate in ranked)
        self._seen_points.update(point.key for point in trial.points)
        return added

    def _replay(self, sequence: FaultSequence) -> dict:
        outcomes = []
        for _ in range(self.settings.replay_count):
            trial = self._trial(sequence, "replay")
            outcomes.append({"run_id": trial.run_id,
                             "triggered": trial.triggered,
                             "target_fatal": trial.closure.fatal})
        return {"replays": outcomes,
                "reproduced": any(r["triggered"] and r["target_fatal"]
                                  for r in outcomes)}

    def _record_feedback(self, trial: Trial, delta: Delta) -> None:
        path = self.settings.output_dir / "runs" / trial.run_id / "feedback.json"
        path.write_text(json.dumps({
            "new_closure_nodes": len(delta.nodes),
            "new_closure_edges": len(delta.edges),
            "new_closure_branch_outcomes": len(delta.branches),
            "new_closure_blocks": len(delta.blocks),
            "new_global_branch_outcomes": len(delta.global_branches),
            "new_global_blocks": len(delta.global_blocks),
        }, indent=2, sort_keys=True) + "\n")

    def run(self) -> dict:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        seed = self._trial(FaultSequence(), "seed")
        if seed.workload.returncode or seed.workload.timed_out:
            raise RuntimeError("fault-free seed workload failed; inspect "
                               + seed.run_id)
        if ((seed.checker is None and getattr(
                self.settings.backend, "check_command", None))
                or (seed.checker is not None and (
                    seed.checker.returncode or seed.checker.timed_out))):
            raise RuntimeError("fault-free seed checker failed; inspect "
                               + seed.run_id)
        if not seed.points:
            raise RuntimeError("seed produced no fault points; check agent hooks")
        if not seed.closure.reached and not self.settings.allow_unreached_seed:
            raise RuntimeError("seed did not reach the configured target check; "
                               "check workload and target site")
        if seed.closure.fatal:
            raise RuntimeError("fault-free seed already reaches the target "
                               "exception; choose a cleaner oracle or workload")
        self._seed_points = {point.key for point in seed.points}
        seed_delta = self.coverage.observe(seed.closure, seed.graph)
        self._record_feedback(seed, seed_delta)
        self._offer_mutations(seed, seed_delta, force=True)
        findings = []
        tested = 1
        matched_trials = 0
        while tested < self.settings.max_runs and len(self.queue):
            candidate = self.queue.pop()
            assert candidate is not None
            trial = self._trial(candidate.sequence)
            tested += 1
            if not trial.triggered:
                continue
            matched_trials += 1
            delta = self.coverage.observe(trial.closure, trial.graph)
            self._record_feedback(trial, delta)
            if trial.closure.fatal:
                finding = {"run_id": trial.run_id,
                           "sequence": trial.sequence.to_dict(),
                           "checker": _command(trial.checker),
                           "confirmation": self._replay(trial.sequence)}
                findings.append(finding)
                with (self.settings.output_dir / "findings.jsonl").open(
                        "a", encoding="utf-8") as out:
                    out.write(json.dumps(finding, sort_keys=True) + "\n")
            self._offer_mutations(trial, delta)
            if (self.settings.matched_trial_limit
                    and matched_trials >= self.settings.matched_trial_limit):
                break
        summary = {"tested": tested, "pending": len(self.queue),
                   "seed_target_reached": seed.closure.reached,
                   "findings": len(findings),
                   "closure_nodes_seen": len(self.coverage.nodes),
                   "closure_edges_seen": len(self.coverage.edges),
                   "branch_outcomes_seen": len(self.coverage.branches),
                   "closure_blocks_seen": len(self.coverage.blocks),
                   "global_blocks_seen": len(self.coverage.global_blocks),
                   "global_branch_outcomes_seen": len(
                       self.coverage.global_branches)}
        with (self.settings.output_dir / "summary.json").open(
                "w", encoding="utf-8") as out:
            json.dump(summary, out, indent=2, sort_keys=True)
            out.write("\n")
        return summary
