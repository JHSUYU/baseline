# Solr: verified bugs (high quality, severe, make the ad hoc check fail)

Same bar as `../hdfs/VERIFIED-BUGS.md`. Source: apache/lucene-solr `faca81bff1` (branch_8_11). Verifier report: `../batches/VERIFY-batch6.md`. No test was rerun.

## Kept

None so far.

## Dropped (07, 09, 10, 13, 14, 19, 21, 31, 38: 42 findings)

- **07/CR-2:** real and severe (an orphan election znode leaves the shard leaderless; FORCELEADER cannot repair it), but already reported: SOLR-18558 (Open) lists this register/unregister race as a suspected cause. Seen only with a test hook aligning the unload, 1 in 150. The closest call.
- **07/MC-1, 21/MC-1:** SOLR-17700 (fixed in 9.9). **10/MC-1, 13/MC-1:** SOLR-18562. **38/CR-1:** SOLR-11685.
- **21:** the target is a Java `assert`; with `-da` the path is a caught NPE at L1766, never the target line.
- **19:** needs legacyCloud=true (removed in 9.0). **09/MC-2..4, 31/MC-1:** PRS, HDFS or legacyCloud only, and heal or retry.
- **14, 38, 10/MC-2..3, 13/MC-2..4, 07/MC-2..3:** a rejected admin call, a transient 503, or a misleading message; a retry works.
- The rest needed a source patch, a test-held window, or state injection, or are off-target.

**Off-target, not counted:** 21/MC-3 (after a failed reload, UNLOAD deletes the core's files but leaves it loaded and serving; `CoreContainer` L1841-1855; unchanged on apache/solr main), 19/CR-2 (a failed cluster-properties read leaves the watch unarmed), 10/CR-3 (a deleted alias's properties are inherited by a re-created alias).

- **05/MC-1, MC-2, MC-3, CR-2:** each needed a test-held window or sleeps patched into ZkStateReader; 0 hits unaided. If hit, the replica stays DOWN until restart (`ZkContainer` L222-231 swallows the failure). 05/MC-3 = 21/CR-3. **05/CR-1:** ENV_LIMITED, off-target.

- **39/MC-2:** fires unaided and lasts (commits and deletes fail at RAUP:247 until the alias is deleted; `Aliases` L302-315 keeps an emptied alias's properties), but both routes are admin misuse of unguarded APIs; the closest call after 07/CR-2. Same defect as 10/CR-3. **39/MC-3:** injected timing. **39/MC-1, 40/CR-1:** not severe. **39/CR-1:** masked. **40/MC-1, MC-3:** SOLR-18559. **40/MC-2:** SOLR-18562.

## Not run

- **solr-adhoc-22:** PORT_BLOCKED; counted as no bug found (owner, 2026-11-05).
