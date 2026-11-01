# Ad Hoc Target File

`specula run --adhoc-target=PATH` names one target file. Specula does not parse its fields; the file is a contract between the person who picked the check and the agents. It is YAML, and it must contain at least the keys below.

```yaml
id: <target id>                          # stable id; becomes the run's target name
system: <system name>
source_tree: /path/to/tree               # the artifact Specula reads (same as --artifact)
base_commit: <commit>                    # the tree must be at this commit (rule 2)
check:
  file: <path/to/File.java>
  line: 123                              # the throw (or assert) line
  method: <Class>.<method>(<parameter types>)
  thrown: <exception type>               # the exception type the failing branch raises
  guard: "<the branch condition>"        # as written in the source
workload:
  module: <build module>
  test: <package>.<TestClass>#<testMethod>
  note: the test reaches the check's method and passes; the check does not fail in it
scope_hint:                              # starting classes, not limits
  - <package>.<Class>
build:
  env: /path/to/env.sh                   # source before building: JDK, build tool, local repository
  prepare: "<build command>"
  test_command: "<command that runs one test>"
```

## Field rules

- `check.line` is the line of the `throw` statement, or of the `assert` / `Preconditions` call. If the guard spans several lines, `guard` quotes all of it.
- `workload.test` uses `Class#method`. A parameterized test may carry an index (`method[1]`), meaning one invocation.
- `scope_hint` gives a starting set of classes. They are not limits.
- `build` is advisory. Agents may use other commands that produce the same build. They must keep the pinned tree and the given JDK.

Extra keys are allowed. Agents ignore keys they do not understand. Agents never write to the target file.
