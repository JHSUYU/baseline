# SOLR-40 exact-reference full campaign, node0, v2

This is a future-only replacement for full-v1. It has a separate config,
runtime artifact set, GO receipt, and output directory. The live full-v1
campaign and its evidence are left untouched.

The v3 MiniCluster healthy JUnit passed 1/0/0/0 and recorded seven physically
bound watcher `getData` doors with observed event-time paths through the actual
`AliasesManager.aliases` reference to the exact `getAliasProps` check. The v3
raw trial is SHA-sealed in
`data/mallory/evidence_archives/SOLR-40-reference-healthy-node0-v3.receipt.json`.
It is prior evidence for this package, not a replacement for a fresh seed.

This distinct package runs the same JUnit through the recognized local
`run_pilot.py`, the exact-reference agent and the strict graph gate. Its first
phase runs **only a new r0000 healthy trial** and stops at a calibration
checkpoint. Before promoting that checkpoint, `seed_gate.py` and `audit_v2.py`
require a passing JUnit receipt, exact
named nonthrowing target, valid runtime attestation, physically named watcher
doors, and at least one observed door→field write→field read→target event-time
path containing both `state_ref` and balanced `return` edges. A lost target or
only sampled state evidence blocks all fault trials. Promotion also verifies
that every initial queued fault matches a uniquely witnessed, named watcher
door. The admitted r0000 trace, JUnit log, result, and checkpoint gate hashes
are checked again before every fault trial, including after a resume. If the
controller stops after writing the durable gate but before switching the
checkpoint to fault mode, `--resume` recomputes the r0000 proof and accepts
the existing gate only when its contents match exactly. A changed gate or raw
seed is rejected without starting fault trials.

The budget is **80 fault trials or 3600 cumulative seconds**, with at most
three exception faults per trial and a 480-second trial timeout. Mutations use
only exact watcher doors with a prior observed reference path. Target identity is matched
fresh on every trial because the MiniCluster may route a request to a different
physical node. A matched injection and a candidate target exception remain
separate evidence; any bug claim needs replay and source review.

No JVM is started by this offline preflight:

```sh
python3 Mallory/adapters/solr/cases/SOLR-40/full-reference-handoff-node0-v2/run_full.py --preflight-only
```

The node0 steward may run the campaign after dispatch issues a matching
case-local `admission-full-node0.json` GO receipt and the resource/lock gate is
clear. Launch it in tmux to preserve the process across Codex disconnects:

```sh
python3 Mallory/adapters/solr/cases/SOLR-40/full-reference-handoff-node0-v2/run_full.py \
  --admission-receipt Mallory/adapters/solr/cases/SOLR-40/full-reference-handoff-node0-v2/admission-full-node0.json
```

If the controller stops, use the same command with `--resume`; the core resumes
from the checkpoint and preserves completed trials. No raw v3 evidence or prior
campaign output is rewritten by this package.
