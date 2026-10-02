"""Docker CLI cluster driver. One container is one independently killable node."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Dict, List, Mapping, Optional, Sequence


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class DockerBackend:
    """No Compose dependency; a setup script may create the containers.

    `prepare` should restore a known initial state for every trial. Inside a
    trial Docker stop/start preserves the selected container's volume state.
    """

    def __init__(self, containers: Mapping[str, str],
                 prepare: Sequence[str], workload: Sequence[str],
                 checker: Optional[Sequence[str]] = None,
                 cwd: Optional[Path] = None,
                 workload_timeout_s: int = 300,
                 command_timeout_s: int = 120,
                 docker_command: Sequence[str] = ("docker",)):
        if not containers or not prepare or not workload or not docker_command:
            raise ValueError("Docker backend needs containers, prepare, workload")
        self.containers = dict(containers)
        self.prepare_command = list(prepare)
        self.workload_command = list(workload)
        self.check_command = list(checker or [])
        self.cwd = cwd
        self.workload_timeout_s = workload_timeout_s
        self.command_timeout_s = command_timeout_s
        self.docker_command = list(docker_command)
        self._controller_host: Optional[str] = None
        self._controller_port: Optional[int] = None

    def _run(self, argv: Sequence[str], env: Optional[Mapping[str, str]] = None,
             timeout: Optional[int] = None) -> CommandResult:
        merged = os.environ.copy()
        merged.update(env or {})
        try:
            result = subprocess.run(list(argv), cwd=self.cwd, env=merged,
                                    text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    timeout=timeout or self.command_timeout_s,
                                    check=False)
            return CommandResult(result.returncode, result.stdout,
                                 result.stderr)
        except subprocess.TimeoutExpired as timeout_error:
            return CommandResult(-1, str(timeout_error.stdout or ""),
                                 str(timeout_error.stderr or ""), True)

    def prepare(self, run_dir: Path, controller_host: str,
                controller_port: int) -> CommandResult:
        self._controller_host = controller_host
        self._controller_port = controller_port
        env = {"ADHOCFUZZ_RUN_DIR": str(run_dir.resolve()),
               "ADHOCFUZZ_CONTROLLER_HOST": controller_host,
               "ADHOCFUZZ_CONTROLLER_PORT": str(controller_port)}
        return self._run(self.prepare_command, env)

    def run_workload(self, run_dir: Path) -> CommandResult:
        env = {"ADHOCFUZZ_RUN_DIR": str(run_dir.resolve())}
        if self._controller_host is not None and self._controller_port is not None:
            env.update({"ADHOCFUZZ_CONTROLLER_HOST": self._controller_host,
                        "ADHOCFUZZ_CONTROLLER_PORT": str(self._controller_port)})
        return self._run(self.workload_command,
                         env, self.workload_timeout_s)

    def check(self, run_dir: Path) -> Optional[CommandResult]:
        if not self.check_command:
            return None
        return self._run(self.check_command,
                         {"ADHOCFUZZ_RUN_DIR": str(run_dir.resolve())})

    def _container(self, node: str) -> str:
        if node not in self.containers:
            raise ValueError("unknown cluster node: " + node)
        return self.containers[node]

    def kill_node(self, node: str) -> None:
        result = self._run(self.docker_command + [
            "stop", "-t", "0", self._container(node)])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    def start_node(self, node: str) -> None:
        result = self._run(self.docker_command + [
            "start", self._container(node)])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
