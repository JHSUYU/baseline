# HBASE-20642: detected by Specula (yes), finding MC-2

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `hbase-adhoc-k2`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

Client `Admin.addColumnFamily` (sync) -> `HBaseAdmin.addColumnFamilyAsync` -> `MasterCallable.rpcCall()` builds an `AddColumnRequest` with `ng.newNonce()` **inside** `rpcCall`, so each retry carries a fresh nonce. HMaster.addColumn performs the "family already exists" pre-check **outside** the nonce-protected `NonceProcedureRunnable` and then submits a `ModifyTableProcedure`. If the active master dies after the procedure already wrote the new table descriptor (or the procedure completes on the new master after WAL replay), the client's retry reaches the new master with a new nonce; the nonce check cannot recognise it as a retry, and the pre-check sees the family already present and throws `InvalidFamilyOperationException("Column family ... already exists so cannot be added")` to a user who issued the call once. Fix: client keeps nonceGroup/nonce across retries (fields of the callable), and HMaster moves the pre-checks inside the nonce-protected runnable (`TableDescriptorGetter`), so a retry with the same nonce returns the existing procedure id.

## What counted as detecting it (written before the run)

A finding counts as this bug if a single client add-column call (one user request) gets InvalidFamilyOperationException from line 2255 because a retry of the same request (master failover / RPC failure after the first attempt's ModifyTableProcedure was submitted and persisted/completed its descriptor update) reaches addColumn with a different nonce and sees the family added by its own first attempt. Root cause: new nonce per retry + pre-check outside the nonce dedup. A second distinct user call adding an existing family (designed behaviour) does not count.

## What Specula found

**Specula's finding MC-2:** Master failover after ModifyTableProcedure writes the HDFS tableinfo makes the client's retried addColumn fail at HMaster.java:2255

- **Cause:** HMaster.addColumn checks old.hasColumnFamily() against committed table descriptors before any nonce dedup, and HBaseAdmin generates a fresh nonce per retry attempt; ModifyTableProcedure makes the new descriptor durable on HDFS before the blocked handler replies.
- **Trigger:** Client addColumn(cf1) is in flight; MTP has written tableinfo {cf0,cf1} to HDFS and not finished; the active master crashes; a new master loads descriptors from HDFS and reloads MTP; HBaseAdmin retries with a new nonce.
- **Consequence:** Admin.addColumnFamily throws InvalidFamilyOperationException ('already exists so cannot be added') from HMaster.addColumn(HMaster.java:2255) although the reloaded procedure completes the client's own add (table ends with cf1).
- **Premises:** One active-master crash after the HDFS tableinfo write and before ModifyTableProcedure completion (master failure is in HBase's fault model). HBaseAdmin retries a retriable connection failure and re-resolves the active master; the retry builds a new nonce inside MasterCallable.rpcCall(). The new master reads table descriptors from HDFS (preload or cache miss) before serving the retry. Pinned tree base_commit 6e53c90; upstream fix HBASE-20642 (72784c2) is not present.

**Operator's judgement:** yes. master failover after descriptor write; retry with fresh nonce hits pre-check (also MC-1 RPC-timeout retry)

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s2_failover.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-08: Invariant TargetSafe is violated.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 1h14m | 35.7M | $24.08 |

Time is active time; quota sleeps are excluded.
