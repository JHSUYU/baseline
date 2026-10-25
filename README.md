# Baselines for GraphChecker's ad hoc coordination checks

Two baselines, each reproducing a paper's approach on the same systems GraphChecker checks:

| directory | approach | what it is |
| --- | --- | --- |
| [`crashfuzz/`](crashfuzz/README.md) | CrashFuzz | coverage-guided fault injection into a system's own cluster JUnit tests, Soot-selected I/O sites, the target check as oracle |
| [`mallory/`](mallory/README.md) | Mallory | greybox fuzzing guided by changes in the run's causal graph: GraphChecker's graph of every native run, Q-learning over injected faults |

Each directory holds its code, its per-system setup, how to run it on the CloudLab cluster, and its results.
