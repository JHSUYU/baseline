"""make_prompt.py <target.yaml> <tree> <env.sh> <result.json> -- the coding-agent prompt for one ad hoc check.

The prompt has the four parts of the paper's coding-agent baseline:
  (1) the definition of ad hoc coordination and the location of the ad hoc check;
  (2) the integration test to start from;
  (3) the task: find an execution, with node crashes, failed requests, or concurrent operations,
      in which the check fails;
  (4) the requirement: a test that reproduces the failure without modifying the system code.
Only the check's site and the workload come from the target file; its scope hints are not given.
"""
import os, sys

import yaml

target_path, tree, envsh, result_path = sys.argv[1:5]
t = yaml.safe_load(open(target_path))
chk, wl, build = t["check"], t["workload"], t["build"]
system = t["system"]
cls, _, meth = wl["test"].partition("#")
test_cmd = build["test_command"].replace("<Class>", cls.rsplit(".", 1)[-1] if "ant " in build["test_command"] else cls).replace("<method>", meth)
# surefire:test runs only compiled classes; `test` also compiles the new test files an agent adds.
test_cmd = test_cmd.replace(" -o surefire:test ", " -o test ")
if t["id"].startswith("hbase-") and "-PrunAllTests" not in test_cmd:
    test_cmd = test_cmd.replace(" -o test ", " -o test -PrunAllTests ")
note = (lambda n: f"\n{n[0].upper()}{n[1:].rstrip('.')}.\n")(build["note"]) if build.get("note") else ""
src_dirs = "solr/*/src/java and lucene/*/src/java" if "solr" in t["id"] else ("src/java/main" if os.path.isdir(f"{tree}/src/java/main") else "every src/main")

print(f"""# Task: find an execution in which an ad hoc check of {system} fails

## 1. Ad hoc coordination and the check

In a distributed system, components (processes such as servers, clients and peers, or threads inside one
process) often coordinate a piece of shared state through their own ad hoc protocol instead of a general
consensus primitive: they pass the state in RPCs, HTTP requests or SASL handshakes, keep it in ZooKeeper
znodes, or share it in variables between threads. This is **ad hoc coordination**. The component that uses
the coordinated state usually validates it with an **ad hoc check**: a branch that throws an exception (or an
assertion) when the state it received or read is not what the coordination was supposed to establish. If
the coordination goes wrong in some execution, for example because a message is lost, a node restarts, or two
operations interleave unexpectedly, the ad hoc check fails.

The ad hoc check you study is in the source tree `{tree}` ({system}):

- file: `{chk['file']}`
- line: {chk['line']}
- method: `{chk['method']}`
- exception thrown when the check fails: `{chk['thrown']}`
- condition: `{chk['guard']}`

## 2. The integration test to start from

`{wl['test']}` (module `{wl['module']}`) is an existing integration test that exercises the coordination
behind this check: it reaches the check's method and passes, i.e. the check does not fail in it.

Build environment: `source {envsh}` first (JDK, build tool and a local dependency cache; there is no network,
so builds run offline). The tree is already built. Run the test with:

```
cd {tree} && {test_cmd}
```
{note}
## 3. The task

Find an execution of {system} in which this ad hoc check fails, i.e. `{chk['thrown']}` is thrown at
`{chk['file']}:{chk['line']}`. Look for executions with **node crashes or restarts, failed or lost requests,
or concurrent operations** (together with the timing, configuration and inputs a real deployment can have)
that make the coordination behind the check go wrong. A failure counts only if it is a bug: the check rejects
state that a correct coordination should not have produced, in an execution that can happen in a real
deployment. A check that correctly rejects an invalid user request is not a bug.

## 4. The reproducing test

If you find such an execution, write a test that reproduces it **without modifying the system code**: do not
change any production source ({src_dirs}) or build file of the system; add new test files only (you may
extend the starting test's setup in a new test class). The test may use test utilities the system already
has (mini clusters, stopping and restarting nodes, fault-injection hooks, Mockito spies that make a request
or an I/O call fail, latches that order concurrent operations), but it must not use reflection or similar
means to put system objects into states the system itself cannot reach, and must not call the check's method
directly with fabricated arguments. Run it and make sure it shows `{chk['thrown']}` thrown from
`{chk['file']}:{chk['line']}` (the stack trace with that frame must appear in the test output or the test's
failure).

When you are done, write `{result_path}` (JSON):

```
{{
  "found": true | false,
  "test": "<fully.qualified.TestClass>#<method>",           // the reproducing test, if found
  "test_files": ["<path relative to the tree>", ...],     // files you added
  "command": "<the command that runs it, from the tree's root>",
  "stack_frame": "<the frame of the check's line as it appears in the output>",
  "execution": "<the failing execution step by step: which nodes, which faults, which order>",
  "why_bug": "<why this is a bug and what its consequence is in a real deployment>"
}}
```

If you do not find a failing execution, write `"found": false` and summarize what you tried in `"execution"`.
Work on your own until you have either a reproducing test or an answer that the check cannot fail.""")
