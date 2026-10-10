#!/usr/bin/env python3
"""Verify source/evidence pins for the ZOOKEEPER-05 source review."""

import hashlib
import json
from pathlib import Path


review = json.loads((Path(__file__).resolve().parent / "source-review.json").read_text())
assert review["case_id"] == "ZOOKEEPER-05"
assert review["new_jvm_runs_for_this_review"] == 0
assert not review["healthy_or_full_admission"]
assert not review["full_campaign_admission"]
assert review["archived_full_summary"]["fault_trials_completed"] == 80
assert review["archived_full_summary"]["exact_exception_trials"] == 0

for group in ("sources", "evidence"):
    for name, pin in review[group].items():
        actual = hashlib.sha256(Path(pin["path"]).read_bytes()).hexdigest()
        if actual != pin["sha256"]:
            raise SystemExit(f"SHA mismatch: {name}: {actual}")

full = json.loads(Path(review["evidence"]["archived_full_result"]["path"]).read_text())
assert full["fault_trials_completed"] == 80
assert full["exact_exception_trials"] == 0
actor = json.loads(Path(review["evidence"]["actor_retention"]["path"]).read_text())
assert actor["applied_fault_count"] == 6
assert actor["exact_same_occurrence_count"] == 0
assert actor["time_respecting_observed_path_count"] == 0

learner = Path(review["sources"]["Learner.java"]["path"]).read_text()
register = learner.split("protected long registerWithLeader(int pktType)", 1)[1].split("protected ", 1)[0]
assert "if (qp.getType() == Leader.LEADERINFO)" in register
assert "if (newEpoch > self.getAcceptedEpoch())" in register
assert "newEpoch == self.getAcceptedEpoch()" in register
assert "Leaders epoch, " in register
assert "if (qp.getType() != Leader.NEWLEADER)" in register

handler = Path(review["sources"]["LearnerHandler.java"]["path"]).read_text()
assert "if (this.getVersion() < 0x10000)" in handler
assert "new QuorumPacket(Leader.LEADERINFO" in handler

follower = Path(review["sources"]["Follower.java"]["path"]).read_text()
follow = follower.split("void followLeader()", 1)[1].split("void ", 1)[0]
assert follow.index("registerWithLeader(Leader.FOLLOWERINFO)") < follow.index("newEpoch < self.getAcceptedEpoch()")
print("PASS: source/evidence pins and protocol control flow; JVM not run")
