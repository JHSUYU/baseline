#!/usr/bin/env python3
"""Keep up to K Specula runs of one system active on THIS node, sharing the case list with other nodes (B5).

Usage: queue.py <system> <K> <case> [<case> ...]

One queue runs on each node, all over the same case list.  A case belongs to the node that claimed
it: <system>/claims/<case>/ is created with mkdir (atomic on the shared /bulk), and its `owner` file
names the node.  A node starts only unclaimed cases it claims itself, and checks and resumes only the
cases it owns (a run's agent conversations live in that node's ~/.claude, so it resumes there).

Every 60 s, for each case this node owns or may claim, it reads the case's log (<system>/logs/<case>.log):
- not started: claim it and launch `run-case.sh <case>` when fewer than K of this node's cases run;
- running: the last "=== Pipeline invocation" is "started" and a process of the case is alive here;
- finished (exit 0): done;
- finished (exit N != 0), or started with no live process: resume with
  `run-case.sh <case> --run-id=<run id>` (counts as a running slot), at most MAX_RESUMES times;
  after that the case is left for the operator (state "needs operator"), unless the operator
  writes cases/<case>/resume-args (extra args for one more resume, e.g. --fresh-context).
State goes to <system>/queue-status.<node>.txt; events to <system>/queue.log.
It exits when no unclaimed case is left and every case this node owns is done or needs the operator.
"""
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc")
MAX_RESUMES = 3
HOST = socket.gethostname().split(".")[0]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def alive(case: str) -> bool:
    out = subprocess.run(["pgrep", "-f", f"pipelinelib.py {case}\\|"], capture_output=True, text=True).stdout
    return bool(out.strip())


def owner(system: str, case: str) -> str | None:
    try:
        return (ROOT / system / "claims" / case / "owner").read_text().strip() or None
    except OSError:
        return None


def claim(system: str, case: str) -> bool:
    d = ROOT / system / "claims" / case
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir()
    except FileExistsError:
        return False
    (d / "owner").write_text(HOST + "\n")
    return True


def state(log: Path, case: str) -> tuple[str, str | None, int]:
    """(state, run id, invocations) of a case from its log."""
    if not log.is_file():
        return "new", None, 0
    text = log.read_text(errors="replace")
    runs = re.findall(r"^Run:\s+(\S+)", text, re.M)
    marks = re.findall(r"=== Pipeline invocation \S+: (started|finished \(exit (-?\d+)\))", text)
    run_id = runs[-1] if runs else None
    if not marks:
        return ("running" if alive(case) else "crashed"), run_id, 0
    last, code = marks[-1]
    invocations = sum(1 for m, _ in marks if m == "started")
    if last == "started":
        return ("running" if alive(case) else "crashed"), run_id, invocations
    return ("done" if code == "0" else f"exit{code}"), run_id, invocations


def launch(system: str, case: str, extra: list[str], events) -> None:
    log = ROOT / system / "logs" / f"{case}.log"
    with open(log, "a") as out:
        subprocess.Popen([str(ROOT / "run-case.sh"), case, *extra], stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    events.write(f"{now()} {HOST} launch {case} {' '.join(extra)}\n")
    events.flush()


def main() -> None:
    system, k, cases = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    logs = ROOT / system / "logs"
    events = open(ROOT / system / "queue.log", "a")
    events.write(f"{now()} {HOST} queue start K={k} cases={' '.join(cases)}\n")
    events.flush()
    pending: dict[str, float] = {}
    while True:
        rows, running, open_cases = [], 0, 0
        states = {}
        for case in cases:
            who = owner(system, case)
            if who not in (None, HOST):
                continue
            st, run_id, inv = state(logs / f"{case}.log", case)
            if who is None and st != "new":
                st = f"started without a claim ({st})"  # never touch a case nobody claimed
            if case in pending and time.time() - pending[case] < 180:
                st = "running"  # a launch just happened; give it time to write its log line
            states[case] = (st, run_id, inv, who)
            running += st == "running"
        for case, (st, run_id, inv, who) in states.items():
            if st == "new":
                if running >= k:
                    open_cases += 1
                    continue
                if not claim(system, case):
                    continue  # another node claimed it first
                launch(system, case, [], events)
                pending[case] = time.time()
                st, running = "running", running + 1
            elif who == HOST and (st.startswith("exit") or st == "crashed"):
                # An operator file cases/<case>/resume-args grants one more resume past the cap.
                extra_file = ROOT / system / "cases" / case / "resume-args"
                granted = extra_file.is_file()
                if (inv - 1 < MAX_RESUMES or granted) and run_id and running < k:
                    extra = extra_file.read_text().split() if granted else []
                    launch(system, case, [f"--run-id={run_id}", *extra], events)
                    if granted:
                        extra_file.rename(extra_file.with_name(f"resume-args.used-{int(time.time())}"))
                    pending[case] = time.time()
                    st, running = "running", running + 1
                elif (inv - 1 >= MAX_RESUMES and not granted) or not run_id:
                    st = f"needs operator ({st}, {inv} invocations)"
            if not (st == "done" or st.startswith("needs operator") or st.startswith("started without")):
                open_cases += 1
            rows.append(f"{case}\t{st}\t{run_id or ''}\t{inv}")
        (ROOT / system / f"queue-status.{HOST}.txt").write_text(
            f"# {now()}  {HOST}  K={k}  running={running}  open={open_cases}\n" + "\n".join(rows) + "\n")
        if open_cases == 0:
            events.write(f"{now()} {HOST} queue done\n")
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
