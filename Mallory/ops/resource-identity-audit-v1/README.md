# Resource identity audit artifact

Read [REPORT.md](REPORT.md) for scope, case IDs, severity, and source-backed findings. `evidence-hashes.json` pins the reviewed source files and representative compressed traces. `resource-identity.patch` is an isolated proposal; it has not been applied to the live shared Mallory core or instrumentation.

From the repository root, reproduce the offline check with:

```sh
python Mallory/ops/resource-identity-audit-v1/verify_offline.py
```

The script checks patch applicability, applies it only inside a temporary directory, and runs the Python core and audit tests there. The patch also contains a Java negative test for wrong-resource replay and ordinal drift; that test has not run in a JVM. After pinned live runs finish, a reviewer can inspect the patch with `git apply --stat Mallory/ops/resource-identity-audit-v1/resource-identity.patch` and decide whether to promote it with adapter-specific resource binding and JVM validation.
