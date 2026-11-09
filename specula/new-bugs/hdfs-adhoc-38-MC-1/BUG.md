# hdfs-adhoc-38 MC-1 (tier A): LAZY_PERSIST inherited by existing files; append refused, scrubber deletes DISK files

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-38`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as 38/MC-2.

## Explanation (verified)

- **case/finding:** hdfs-adhoc-38/MC-1 (=MC-2)
- **defect (root cause):** `INodeFile.getStoragePolicyID` inherits the parent's policy (L592-597). LAZY_PERSIST is meant to apply only at creation: it cannot be set on an existing file (`FSDirAttrOp` L446-459), and `MemoryStorage.md` says a directory's policy applies to "new files". Yet append (`FSDirAppendOp`:122) and the lazy-persist scrubber (`FSNamesystem` ~L4700-4712) use the inherited policy
- **consequence:** existing DISK files under a directory later tagged LAZY_PERSIST (or renamed into one) cannot be appended to (the target), and **the scrubber deletes such a file when its replicas are briefly all unavailable: data loss**
- **trigger:** any user with write access sets LAZY_PERSIST on a parent directory or renames a file into one; default configuration

**Specula's finding MC-1:** LAZY_PERSIST set on an ancestor after create makes append of an existing non-lazy file throw at FSDirAppendOp.java:122

- **Cause:** INodeFile.getStoragePolicyID resolves an unset file through its current ancestors, and the directory branch of setStoragePolicy has no copy-on-create check, so tagging an ancestor LAZY_PERSIST gives an existing file own=0, eff=15. The append guard compares the effective id.
- **Trigger:** create and close a file with no policy, setStoragePolicy(<any ancestor>, LAZY_PERSIST), then append. Public API, default configuration, WRITE on the ancestor is enough.
- **Consequence:** Append fails with RemoteException(java.lang.UnsupportedOperationException) thrown at FSDirAppendOp.java:122 on a DISK file never created lazy; hdfs dfs -appendToFile exits 1. Survives retries and NameNode restarts until the tag is explicitly unset. Same mechanism: truncate fails at FSDirTruncateOp.java:101, and the scrubber deletes such a file when its blocks have no live replica (observed after a transient DataNode outage, and after a NameNode restart with one block in the namespace).
- **Premises:** The file is replicated, not striped: INodeFile.java:603-606 maps LAZY_PERSIST to unspecified for striped files. The file's own policy id is unset, so it was created without the flag and before the tag. dfs.storage.policy.enabled=true (default). dfs.storage.policy.permissions.superuser-only=false (default) lets non-admins tag; with true a superuser still can. The tag stays in place until the append; an explicit unset of the ancestor clears the effect. No later revision on origin/trunk through 2026-10-26 changes the sites.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s1.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-38` (all phases) | 3h04m | 140.2M | $82.19 |
| of which: confirming this finding | | 7.0M | $6.77 |

Time is active time; quota sleeps are excluded.
