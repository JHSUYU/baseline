# Exact target throw coverage audit

The original 102-check campaign used the original embedded-cluster JUnit tests and a generic Soot-selected fault scope. Older selection artifacts for the checks below lack `target_throw_sites`. Their target exception oracle depended on a typed method-exit throw. Source inspection shows that these particular target throws may be caught or wrapped before method exit, so a zero-candidate result from the older run cannot rule out execution of the selected throw. This is an instrumentation false-negative risk, not evidence of a product bug.

| Check | Exact selected throw | Why method-exit observation may miss it | Older campaign evidence |
| --- | --- | --- | --- |
| HBASE-01 | `ConnectionImplementation.locateRegionInMeta`, `ConnectionImplementation.java:1106`, `RegionServerStoppedException` | The method catches it as `IOException` and retries; it exits with that exception only on the last attempt. | 80 trials, 80 strict injections, 11 post-fault target reaches, 0 candidates. |
| ZOOKEEPER-05 | `Follower.followLeader`, `Follower.java:103`, `IOException` | A catch for `Exception` in the same method logs and closes the socket without rethrowing. | 80 trials, 63 strict injections, 40 post-fault target reaches, 0 candidates. |
| ZOOKEEPER-11 | `QuorumPeer.loadDataBase`, `QuorumPeer.java:1175`, `IOException` | The enclosing `IOException` catch wraps the exception in `RuntimeException`. | 80 trials, 49 strict injections, 16 post-fault target reaches, 0 candidates. |
| ZOOKEEPER-12 | `QuorumPeer.loadDataBase`, `QuorumPeer.java:1197`, `IOException` | The same catch wraps the exception in `RuntimeException`. | 80 trials, 52 strict injections, 37 post-fault target reaches, 0 candidates. |
| HBASE-30 | `RSRpcServices.replay`, `RSRpcServices.java:2298`, `IOException` | The enclosing `IOException` catch wraps the exception in `ServiceException`. | Pinned original campaign still active when this audit began. |

Fresh Soot selection in `.study-repairs/selection-quality-audit/<case>/soot-selection.json` now identifies the exact explicit-throw lines `[1106]`, `[103]`, `[1175]`, `[1197]`, and `[2298]`, respectively. The general selection rule was corrected before the ZooKeeper 11/12 valid reruns so that the two different throws in `QuorumPeer.loadDataBase` are not attributed to one another. These are independently generated static artifacts; their runtime reproduction must still be established by an unchanged JUnit and an exactly matched fault injection.

The fresh runs are isolated from the original 102 results:

| Check | Execution host | New result root | Status at audit preparation |
| --- | --- | --- | --- |
| ZOOKEEPER-05 | node2 | `/users/ZhenyuLi/static-rerun/results-freshthrow/ZOOKEEPER-05` | Terminal: `budget_or_queue_complete`. |
| ZOOKEEPER-11 | node2 | `/users/ZhenyuLi/static-rerun/results-freshthrow-v2/ZOOKEEPER-11` | Terminal with `freshthrow-v2`. An earlier isolated v1 trial is retired under `results-freshthrow/ZOOKEEPER-11` because it used an ambiguous two-line oracle. |
| ZOOKEEPER-12 | node2 | `/users/ZhenyuLi/static-rerun/results-freshthrow-v2/ZOOKEEPER-12` | Terminal with `freshthrow-v2`. |
| HBASE-01 | node1 | `/users/ZhenyuLi/static-rerun/results-freshthrow/HBASE-01` | Terminal with `freshthrow-v1`. |
| HBASE-30 | node1 | `/users/ZhenyuLi/static-rerun/results-freshthrow/HBASE-30` | Active in an isolated `freshthrow-v1` campaign, started only after its original pinned campaign finished. |

The original `data/crashfuzz/static102-rerun.tsv` remains the record of the original campaign until fresh runs finish and are reviewed. Any candidate in a fresh run still requires exact target throw evidence, a strict injection, source review, and replay before a bug claim.

## Fresh-run outcomes

The new ZOOKEEPER-05 run finished with 80 fault trials, 75 exact injections, 55 post-fault target reaches, and zero target exception candidates. Its fresh selection identified the explicit `IOException` at line 103. The unchanged JUnit passed in 5.3 seconds without a target throw; the full fresh check used 937.044 seconds, including setup, versus 881.526 seconds for the original campaign. The two campaigns used 1,818.570 seconds in total. The new result is `node2:/users/ZhenyuLi/static-rerun/results-freshthrow/ZOOKEEPER-05/campaign-freshthrow-v1/ZOOKEEPER-05/result.json`; its selection digest is `a2d8c34342960022e0be87312f494d3483cc63538ef48940239a9c4d1aa43723`.

HBASE-01's unchanged healthy JUnit passed in 43.949 seconds, reached the exact check twice, and did not throw at line 1106. Its first three completed fault trials lost the target because selected `MetaTableAccessor.scanMeta` I/O during master startup was interrupted. After trial 3 reached an atomic checkpoint, the isolated worker was stopped; `state.before-site-diversity.json` preserves its state (`SHA-256 ec8cc04357c745d1e32c9a50a968b0e7e8e838a13f1d682bc18395b4a23c2c6c`). The generic scheduler from commit `1e1a9863` was then staged only in the isolated tool, `site_diversity_version` was set to 2, and the same campaign resumed with three completed trials and active trial 4 intact. No completed trial was rerun. An earlier setup failure caused by an omitted JUnit launcher jar is preserved in `setup-failure-missing-vendor/`; it occurred before any fault trial.

The resumed HBASE-01 campaign first retained the check in trial 6: `strict_injection=true`, `target_reached_after_fault=true`, `target_site_after_fault=true`, and `target_exception_count=0` in `campaign-freshthrow-v1/HBASE-01/trials/0006-304f77bbe62dbc8f32a2/result.json` (39.507 seconds). Trials 7 and 8 were also recorded as `checked`.

HBASE-01 subsequently finished at 82 trials under the adaptive rule, with 80 strict injections, 30 post-fault target reaches, and zero target exception candidates. The fresh campaign took 12,199.986 seconds including its 43.949-second healthy seed; its final result is `node1:/users/ZhenyuLi/static-rerun/results-freshthrow/HBASE-01/campaign-freshthrow-v1/HBASE-01/result.json`. The original campaign took 15,063.185 seconds, so the two isolated efforts total 27,263.171 seconds. The fresh run reached the selected check in its healthy seed and in 30 fault trials, but did not observe the selected `RegionServerStoppedException` throw after an injection. This is a bounded negative observation, not proof the branch is unreachable under other fault sequences.

ZOOKEEPER-11 and ZOOKEEPER-12 both finished their valid `freshthrow-v2` runs at the adaptive base budget of 80 trials. Their configured maximum was 240; each run had already exceeded the minimum of 30 target-retained trials, so the adaptive budget stopped at 80. Both unchanged healthy JUnit runs returned 0 (16.603 and 17.847 seconds, respectively). Neither fresh run observed a target exception candidate:

| Check | Valid fresh elapsed | Trials | Strict injections | Post-fault target reaches | Candidates | Old campaign elapsed | Old + valid fresh elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ZOOKEEPER-11 | 2,839.079 s | 80 | 71 | 43 | 0 | 3,254.523 s | 6,093.602 s |
| ZOOKEEPER-12 | 2,895.610 s | 80 | 71 | 61 | 0 | 3,934.746 s | 6,830.356 s |

The valid results are `node2:/users/ZhenyuLi/static-rerun/results-freshthrow-v2/ZOOKEEPER-11/campaign-freshthrow-v2/ZOOKEEPER-11/result.json` and the corresponding `ZOOKEEPER-12` path. Both use fresh Soot selection digest `d4b75a63947a232a7425ca86e379985aabb61458cda41d995f901b2c50d6c31b`. The retired ZOOKEEPER-11 `freshthrow-v1` attempt contains one completed trial and at least 35.385 seconds of active runtime. It is excluded from the valid fresh metrics because the older oracle conflated the two explicit throw lines; its state remains at `node2:/users/ZhenyuLi/static-rerun/results-freshthrow/ZOOKEEPER-11/campaign-freshthrow-v1/ZOOKEEPER-11/state.json`.

The original HBASE-30 run finished first with 80 fault trials, 51 strict injections, 26 post-fault target reaches, zero candidates, and 16,048.149 seconds of accumulated elapsed time. Only then did the isolated watcher start its fresh selection. The new selection digest is `d7a492bf914c6b4aa201b3cf5b77383ecc2d1aec7849a3f37e3cc56235a4deed`; `selected_target_throw_lines()` selects only the exact `IOException` at line 2298. The unchanged healthy JUnit returned 0 in 37.979 seconds. Its fresh fault campaign is still active under `node1:/users/ZhenyuLi/static-rerun/results-freshthrow/HBASE-30/campaign-freshthrow-v1/HBASE-30/`.

Fresh HBASE-30 trial 18 was the first completed strict injection that retained the target after the fault: one `executeProcedures` RPC fault matched, both `target_reached_after_fault` and `target_site_after_fault` are true, and `target_exception_count` and `target_fatal_exception_count` are zero. It ran for 41.406 seconds. The exact result is `node1:/users/ZhenyuLi/static-rerun/results-freshthrow/HBASE-30/campaign-freshthrow-v1/HBASE-30/trials/0018-67008ede6e4daa45f16a/result.json`. Trials 1–17 comprised 11 `lost_target` and 6 `unmatched` outcomes, so this is evidence of reachability, not a final coverage claim or bug candidate.
