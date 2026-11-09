# Task: find an execution in which an ad hoc check of Apache ZooKeeper fails

## 1. Ad hoc coordination and the check

In a distributed system, components (processes such as servers, clients and peers, or threads inside one
process) often coordinate a piece of shared state through their own ad hoc protocol instead of a general
consensus primitive: they pass the state in RPCs, HTTP requests or SASL handshakes, keep it in ZooKeeper
znodes, or share it in variables between threads. This is **ad hoc coordination**. The component that uses
the coordinated state usually validates it with an **ad hoc check**: a branch that throws an exception (or an
assertion) when the state it received or read is not what the coordination was supposed to establish. If
the coordination goes wrong in some execution, for example because a message is lost, a node restarts, or two
operations interleave unexpectedly, the ad hoc check fails.

The ad hoc check you study is in the source tree `/bulk/codingagent/cases/zk-adhoc-b1/agent/zookeeper` (Apache ZooKeeper):

- file: `zookeeper-server/src/main/java/org/apache/zookeeper/server/FinalRequestProcessor.java`
- line: 674
- method: `FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, List<Id>)`
- exception thrown when the check fails: `org.apache.zookeeper.KeeperException.NoNodeException`
- condition: `n == null   (n = zks.getZKDatabase().getNode(path))`

## 2. The integration test to start from

`org.apache.zookeeper.test.TestAdhocWorkloadB1#run` (module `zookeeper-server`) is an existing integration test that exercises the coordination
behind this check: it reaches the check's method and passes, i.e. the check does not fail in it.

Build environment: `source /bulk/codingagent/cases/zk-adhoc-b1/agent/env.sh` first (JDK, build tool and a local dependency cache; there is no network,
so builds run offline). The tree is already built. Run the test with:

```
cd /bulk/codingagent/cases/zk-adhoc-b1/agent/zookeeper && mvn -B -o test -pl zookeeper-server -Dtest='org.apache.zookeeper.test.TestAdhocWorkloadB1#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false
```

## 3. The task

Find an execution of Apache ZooKeeper in which this ad hoc check fails, i.e. `org.apache.zookeeper.KeeperException.NoNodeException` is thrown at
`zookeeper-server/src/main/java/org/apache/zookeeper/server/FinalRequestProcessor.java:674`. Look for executions with **node crashes or restarts, failed or lost requests,
or concurrent operations** (together with the timing, configuration and inputs a real deployment can have)
that make the coordination behind the check go wrong. A failure counts only if it is a bug: the check rejects
state that a correct coordination should not have produced, in an execution that can happen in a real
deployment. A check that correctly rejects an invalid user request is not a bug.

## 4. The reproducing test

If you find such an execution, write a test that reproduces it **without modifying the system code**: do not
change any production source (every src/main) or build file of the system; add new test files only (you may
extend the starting test's setup in a new test class). The test may use test utilities the system already
has (mini clusters, stopping and restarting nodes, fault-injection hooks, Mockito spies that make a request
or an I/O call fail, latches that order concurrent operations), but it must not use reflection or similar
means to put system objects into states the system itself cannot reach, and must not call the check's method
directly with fabricated arguments. Run it and make sure it shows `org.apache.zookeeper.KeeperException.NoNodeException` thrown from
`zookeeper-server/src/main/java/org/apache/zookeeper/server/FinalRequestProcessor.java:674` (the stack trace with that frame must appear in the test output or the test's
failure).

When you are done, write `/bulk/codingagent/cases/zk-adhoc-b1/agent/result.json` (JSON):

```
{
  "found": true | false,
  "test": "<fully.qualified.TestClass>#<method>",           // the reproducing test, if found
  "test_files": ["<path relative to the tree>", ...],     // files you added
  "command": "<the command that runs it, from the tree's root>",
  "stack_frame": "<the frame of the check's line as it appears in the output>",
  "execution": "<the failing execution step by step: which nodes, which faults, which order>",
  "why_bug": "<why this is a bug and what its consequence is in a real deployment>"
}
```

If you do not find a failing execution, write `"found": false` and summarize what you tried in `"execution"`.
Work on your own until you have either a reproducing test or an answer that the check cannot fail.
