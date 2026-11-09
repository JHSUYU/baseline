# Task: find an execution in which an ad hoc check of Apache Solr fails

## 1. Ad hoc coordination and the check

In a distributed system, components (processes such as servers, clients and peers, or threads inside one
process) often coordinate a piece of shared state through their own ad hoc protocol instead of a general
consensus primitive: they pass the state in RPCs, HTTP requests or SASL handshakes, keep it in ZooKeeper
znodes, or share it in variables between threads. This is **ad hoc coordination**. The component that uses
the coordinated state usually validates it with an **ad hoc check**: a branch that throws an exception (or an
assertion) when the state it received or read is not what the coordination was supposed to establish. If
the coordination goes wrong in some execution, for example because a message is lost, a node restarts, or two
operations interleave unexpectedly, the ad hoc check fails.

The ad hoc check you study is in the source tree `/bulk/codingagent/cases/solr-adhoc-21/agent/lucene-solr` (Apache Solr):

- file: `solr/core/src/java/org/apache/solr/core/CoreContainer.java`
- line: 1765
- method: `CoreContainer.reload(String, UUID)`
- exception thrown when the check fails: `java.lang.AssertionError`
- condition: `assert replica != null;   (fails when replica == null; replica = docCollection.getReplica(cd.getCloudDescriptor().getCoreNodeName()), inside if (docCollection != null); a Java assert, active only with -ea)`

## 2. The integration test to start from

`org.apache.solr.cloud.api.collections.CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss` (module `solr/core`) is an existing integration test that exercises the coordination
behind this check: it reaches the check's method and passes, i.e. the check does not fail in it.

Build environment: `source /bulk/codingagent/cases/solr-adhoc-21/agent/env.sh` first (JDK, build tool and a local dependency cache; there is no network,
so builds run offline). The tree is already built. Run the test with:

```
cd /bulk/codingagent/cases/solr-adhoc-21/agent/lucene-solr && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=CollectionReloadTest -Dtests.method=testReloadedLeaderStateAfterZkSessionLoss -Dtests.jvms=1 -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib
```

## 3. The task

Find an execution of Apache Solr in which this ad hoc check fails, i.e. `java.lang.AssertionError` is thrown at
`solr/core/src/java/org/apache/solr/core/CoreContainer.java:1765`. Look for executions with **node crashes or restarts, failed or lost requests,
or concurrent operations** (together with the timing, configuration and inputs a real deployment can have)
that make the coordination behind the check go wrong. A failure counts only if it is a bug: the check rejects
state that a correct coordination should not have produced, in an execution that can happen in a real
deployment. A check that correctly rejects an invalid user request is not a bug.

## 4. The reproducing test

If you find such an execution, write a test that reproduces it **without modifying the system code**: do not
change any production source (solr/*/src/java and lucene/*/src/java) or build file of the system; add new test files only (you may
extend the starting test's setup in a new test class). The test may use test utilities the system already
has (mini clusters, stopping and restarting nodes, fault-injection hooks, Mockito spies that make a request
or an I/O call fail, latches that order concurrent operations), but it must not use reflection or similar
means to put system objects into states the system itself cannot reach, and must not call the check's method
directly with fabricated arguments. Run it and make sure it shows `java.lang.AssertionError` thrown from
`solr/core/src/java/org/apache/solr/core/CoreContainer.java:1765` (the stack trace with that frame must appear in the test output or the test's
failure).

When you are done, write `/bulk/codingagent/cases/solr-adhoc-21/agent/result.json` (JSON):

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
