# zk-adhoc-b2 MC-1 (tier B): offer vanishes between list and read; participant goes FAILED and blocks the election

System: zookeeper. Found by Specula's ad hoc run `zk-adhoc-b2`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as b2/MC-3.

## Explanation (verified)

- **tier:** B
- **case/finding:** zk-adhoc-b2/MC-1 (=MC-3)
- **defect:** `LeaderElectionSupport.toLeaderOffers` (L300-315) has no NoNode handling for an offer that vanishes between list and read; the exception reaches `becomeFailed` (L138-139)
- **consequence:** a participant goes FAILED with its offer still live and blocks the election
- **trigger:** a peer stops or its session ends during a listing; recipe library, whose Javadoc leaves recovery to the application

**Specula's finding MC-1:** A peer's stop() deletes a listed offer before a participant's getData on it, leaving a FAILED live offer and no leader

- **Cause:** LeaderElectionSupport.toLeaderOffers reads each child from an earlier getChildren with a separate getData (LES:199, 310) and does not tolerate a vanished child, so a peer's delete at LES:155 makes FinalRequestProcessor.java:674 throw NoNodeException.
- **Trigger:** A participant inside start() or a watch re-determination has listed offers when a peer's ordinary stop() delete is served before its getData on that offer. No fault is needed.
- **Consequence:** The participant goes FAILED with its offer live and no watch and never re-enters the election. Listeners never get ELECTED, getLeaderHostName names the FAILED host, a healthy joiner stays READY behind it until an explicit stop(), and getLeaderHostName callers get NoNodeException.
- **Premises:** A start() or watch re-determination overlaps a peer's stop(); stop() is documented as allowed at any time. Reproduced with all participants on one shared handle and one standalone ClientBase server, as in the workload; separate sessions were not exercised. A listener that obeys the Javadoc by calling stop() on FAILED removes the blocking offer but the participant leaves the election; only an application-level re-start() rejoins, and the recipe does not document that.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s1.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `zk-adhoc-b2` (all phases) | 2h45m | 84.2M | $61.38 |
| of which: confirming this finding | | 1.5M | $2.46 |

Time is active time; quota sleeps are excluded.
