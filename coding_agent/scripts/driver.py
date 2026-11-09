#!/usr/bin/env python3
"""driver.py <case> -- run the coding agent (Claude Code, one prompt) on one prepared ad hoc check.

The agent runs in a container of its own (codingagent-runtime) that sees only:
  - the case's agent/ directory (its tree with a one-commit history, its dependency cache, env.sh,
    its own Claude Code home, /tmp), at the same path as on the host;
  - the JDKs, Maven and Ant, read-only under /opt/tools;
  - the Claude Code CLI, read-only;
and whose only network route is the allowlist proxy to the Anthropic API.  Web tools are disabled.

The driver records every session's stream-json, time and usage in cases/<case>/run.json.  A session that
stops on a usage limit, an expired login or an API error is resumed (same session) after a wait; waits are
not counted as the agent's time.  The agent's active time is capped at BUDGET_S.
"""
import json, os, re, shutil, subprocess, sys, time

R = "/bulk/codingagent"
S = "/bulk/specula-adhoc"
CLI = "/bulk/codingagent/cli/claude-2.1.319"   # Claude Code 2.1.319, one copy for every node
MODEL = "claude-opus-5-5[1m]"
EFFORT = "high"
BUDGET_S = 8 * 3600
# No web access, and nothing that runs outside this container (remote or scheduled agents).
DISALLOWED = ["WebSearch", "WebFetch", "RemoteTrigger", "CronCreate", "CronDelete", "CronList", "ScheduleWakeup", "Workflow"]
UID, GID = 20003, 3160
CONTINUE_MSG = ("Continue the task from where you stopped. When you are done, make sure the result file "
                "described in the task exists.")
NUDGE_MSG = ("You stopped without writing the result file the task asks for. Continue the task; when you "
             "are done, write the result file.")

case_id = sys.argv[1]
cdir = f"{R}/cases/{case_id}"
if os.path.exists(f"{cdir}/HOLD"):   # held by the operator: do not run
    sys.exit(0)
agent = f"{cdir}/agent"
logs = f"{cdir}/logs"
runjson = f"{cdir}/run.json"
cname = f"ca-{case_id}"
tree = next(d for d in os.listdir(agent) if d in ("hadoop", "zookeeper", "hbase", "lucene-solr"))
prompt = open(f"{cdir}/prompt.md").read()
os.makedirs(logs, exist_ok=True)


def now():
    return time.time()


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg):
    with open(f"{logs}/driver.log", "a") as f:
        f.write(f"{stamp()} {msg}\n")


def load_state():
    if os.path.exists(runjson):
        return json.load(open(runjson))
    return {"case": case_id, "model": MODEL, "effort": EFFORT, "cli": os.path.basename(CLI),
            "budget_s": BUDGET_S, "started": stamp(), "sessions": [], "waits": [], "session_id": None,
            "active_s": 0.0, "wait_s": 0.0, "state": "running"}


def save(st):
    tmp = runjson + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, runjson)


def freshest_credentials():
    """Copy the freshest login (by expiresAt) among the host's and every case home's into this case."""
    cands = [os.path.expanduser("~/.claude/.credentials.json")]
    for c in os.listdir(f"{R}/cases"):
        cands.append(f"{R}/cases/{c}/agent/home/.claude/.credentials.json")
    best, bexp = None, -1
    for p in cands:
        try:
            e = json.load(open(p))["claudeAiOauth"]["expiresAt"]
        except Exception:
            continue
        if e > bexp:
            best, bexp = p, e
    dst = f"{agent}/home/.claude/.credentials.json"
    if best and best != dst:
        try:
            if open(best).read() != (open(dst).read() if os.path.exists(dst) else ""):
                shutil.copyfile(best, dst + ".new"); os.chmod(dst + ".new", 0o600); os.replace(dst + ".new", dst)
        except Exception as e:
            log(f"credential copy failed: {e}")


def container_up():
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cname], capture_output=True, text=True)
    if r.stdout.strip() == "true":
        return
    subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    etc = f"{cdir}/etc"
    os.makedirs(etc, exist_ok=True)
    open(f"{etc}/passwd", "w").write(
        "root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
        f"agent:x:{UID}:{GID}:agent:{agent}/home:/bin/bash\n")
    open(f"{etc}/group", "w").write(f"root:x:0:\nnogroup:x:65534:\nagent:x:{GID}:\n")
    cmd = ["docker", "run", "-d", "--name", cname, "--hostname", "agent-host", "--network", "ca-internal",
           "--user", f"{UID}:{GID}", "--cpus", "24", "--memory", "96g", "--shm-size", "4g",
           "--ulimit", "nofile=65536:65536", "--ulimit", "nproc=65536:65536",
           "-v", f"{agent}:{agent}",
           "-v", f"{agent}/tmp:/tmp",
           "-v", f"{etc}/passwd:/etc/passwd:ro", "-v", f"{etc}/group:/etc/group:ro",
           "-v", f"{S}/jdk:/opt/tools/jdk:ro",
           "-v", f"{S}/apache-maven-3.9.15:/opt/tools/apache-maven-3.9.15:ro",
           "-v", f"{S}/apache-ant-1.10.14:/opt/tools/apache-ant-1.10.14:ro",
           # Old buggy versions (known bugs): JDK 8 and 7, Ant 1.9.16, protoc 2.5.0.
           "-v", f"{R}/tools/jdk8:/opt/tools/jdk8:ro", "-v", f"{S}/toolchain/jdk7:/opt/tools/jdk7:ro",
           "-v", f"{S}/toolchain/apache-ant-1.9.16:/opt/tools/apache-ant-1.9.16:ro",
           "-v", f"{S}/toolchain/protoc-2.5.0:/opt/tools/protoc-2.5.0:ro",
           "-v", f"{CLI}:/opt/claude/claude:ro",
           "-w", f"{agent}/{tree}",
           "codingagent-runtime:1", "sleep", "infinity"]
    subprocess.run(cmd, check=True, capture_output=True)
    log("container started")


def exec_env():
    env = {"HOME": f"{agent}/home", "USER": "agent", "LOGNAME": "agent", "SHELL": "/bin/bash",
           "HTTPS_PROXY": "http://ca-proxy:3128", "HTTP_PROXY": "http://ca-proxy:3128",
           "NO_PROXY": "localhost,127.0.0.1,::1,agent-host", "no_proxy": "localhost,127.0.0.1,::1,agent-host",
           "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1",
           "BASH_DEFAULT_TIMEOUT_MS": "600000", "BASH_MAX_TIMEOUT_MS": "3600000",
           "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/claude"}
    out = []
    for k, v in env.items():
        out += ["-e", f"{k}={v}"]
    return out


def parse_stream(path):
    """The session's id, its final result event (if any) and, as a fallback, usage summed per message."""
    sid, result, msgs = None, None, {}
    try:
        lines = open(path, errors="replace").read().splitlines()
    except FileNotFoundError:
        return None, None, {}
    for ln in lines:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        sid = ev.get("session_id") or sid
        if ev.get("type") == "result":
            result = ev
        elif ev.get("type") == "assistant":
            m = ev.get("message", {})
            if m.get("id") and m.get("usage"):
                msgs[m["id"]] = m["usage"]
    tot = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    for u in msgs.values():
        for k in tot:
            tot[k] += u.get(k) or 0
    return sid, result, tot


LIMIT_RE = re.compile(r"(usage limit|hit your limit|limit reached|rate.?limit|resets? )", re.I)
AUTH_RE = re.compile(r"(oauth|authenticat|401|/login|not logged in|invalid api key|token has expired)", re.I)


def classify(result, stderr_text):
    if result and not result.get("is_error") and result.get("subtype") == "success":
        return "ok"
    text = json.dumps(result or {}) + " " + stderr_text
    if LIMIT_RE.search(text):
        return "limit"
    if AUTH_RE.search(text):
        return "auth"
    return "error"


def main():
    st = load_state()
    if st["state"] in ("done", "budget"):
        print(f"{case_id}: already {st['state']}"); return
    container_up()
    errors = 0
    nudges = sum(1 for s in st["sessions"] if s.get("message") == "nudge")
    while True:
        remaining = BUDGET_S - st["active_s"]
        if remaining <= 60:
            st["state"] = "budget"; break
        freshest_credentials()
        i = len(st["sessions"]) + 1
        out = f"{logs}/session-{i:02d}.jsonl"
        err = f"{logs}/session-{i:02d}.stderr"
        if st["session_id"] is None:
            msg_kind, args = "prompt", ["-p", prompt]
        else:
            msg_kind = st.get("next_message", "continue")
            args = ["-p", NUDGE_MSG if msg_kind == "nudge" else CONTINUE_MSG, "--resume", st["session_id"]]
        cmd = ["docker", "exec", "-i", *exec_env(), "-w", f"{agent}/{tree}", cname,
               "/opt/claude/claude", *args, "--model", MODEL, "--effort", EFFORT,
               "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions",
               "--disallowedTools", *DISALLOWED]
        log(f"session {i} ({msg_kind}) start, remaining {remaining/3600:.2f} h")
        t0 = now()
        timed_out = False
        with open(out, "w") as fo, open(err, "w") as fe:
            p = subprocess.Popen(cmd, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL)
            try:
                p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(["docker", "exec", cname, "pkill", "-f", "/opt/claude/claude"], capture_output=True)
                try:
                    p.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    p.kill()
        dt = now() - t0
        sid, result, fallback = parse_stream(out)
        stderr_text = open(err, errors="replace").read()[-4000:]
        kind = "timeout" if timed_out else classify(result, stderr_text)
        rec = {"n": i, "message": msg_kind, "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
               "wall_s": round(dt, 1), "outcome": kind, "session_id": sid}
        if result:
            for k in ("duration_ms", "duration_api_ms", "num_turns", "total_cost_usd", "usage", "modelUsage",
                      "subtype", "is_error"):
                rec[k] = result.get(k)
            rec["result_text"] = (result.get("result") or "")[:2000]
        else:
            rec["usage_fallback"] = fallback
        if sid and st["session_id"] is None:
            st["session_id"] = sid
        st["sessions"].append(rec)
        has_result = os.path.exists(f"{agent}/result.json")
        # A session that failed at once (limit, login) did no work: count its time as a wait.
        if kind in ("limit", "auth") and dt < 120:
            st["wait_s"] += dt
        else:
            st["active_s"] += dt
        log(f"session {i} {kind} after {dt:.0f} s; result.json={'yes' if has_result else 'no'}")
        if kind == "timeout":
            st["state"] = "budget"; break
        if kind == "ok":
            errors = 0
            if has_result:
                st["state"] = "done"; break
            if nudges >= 2:
                st["state"] = "done"; break
            nudges += 1
            st["next_message"] = "nudge"
            save(st); continue
        st["next_message"] = "continue"
        if st["session_id"] is None:
            # It never started: the next try sends the prompt again.
            st["sessions"][-1]["message"] = "prompt-failed"
        wait = {"limit": 900, "auth": 120}.get(kind, 120)
        if kind == "error":
            errors += 1
            if errors > 6:
                st["state"] = "error"; break
        st["waits"].append({"at": stamp(), "kind": kind, "s": wait})
        st["wait_s"] += wait
        save(st)
        log(f"waiting {wait} s ({kind})")
        time.sleep(wait)
    st["ended"] = stamp()
    st["result"] = json.load(open(f"{agent}/result.json")) if os.path.exists(f"{agent}/result.json") else None
    save(st)
    subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    log(f"finished: {st['state']}, active {st['active_s']/3600:.2f} h, waits {st['wait_s']/3600:.2f} h")


if __name__ == "__main__":
    main()
