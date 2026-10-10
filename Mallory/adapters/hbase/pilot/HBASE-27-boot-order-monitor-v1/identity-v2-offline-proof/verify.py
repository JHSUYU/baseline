#!/usr/bin/env python3
"""Check HBASE-27 tracker handoffs against the exact target-check timeline."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


EXPECTED_GZIP_SHA256 = "b761f08ee5fa07e778af64cb6fba425d357bbd7370fc4eaa954812c5bdcb2014"
TARGET = "org.apache.hadoop.hbase.regionserver.HRegionServer#blockAndCheckIfStopped"
CALLBACK = "org.apache.hadoop.hbase.zookeeper.ZKNodeTracker#nodeCreated"


def verify(path: Path) -> dict:
    compressed = path.read_bytes()
    digest = hashlib.sha256(compressed).hexdigest()
    if digest != EXPECTED_GZIP_SHA256:
        raise ValueError(f"unexpected HBASE-27 evidence sha256: {digest}")
    events = [json.loads(line) for line in gzip.decompress(compressed).splitlines()]
    by_seq = {event["seq"]: event for event in events}
    if len(by_seq) != len(events):
        raise ValueError("duplicate event sequence")

    target_checks = [event for event in events if event["type"] == "TARGET_CHECK"
                     and event.get("node") == "rs0" and TARGET in event.get("site", "")]
    if [event["seq"] for event in target_checks] != [4, 7]:
        raise ValueError("the exact rs0 target-check sequence changed")

    paths = []
    for door_seq, submit_seq, claim_seq, exit_seq in ((9, 11, 14, 16),
                                                       (20, 22, 24, 26)):
        door, submit, claim, exit_event = (by_seq[seq] for seq in
                                           (door_seq, submit_seq, claim_seq, exit_seq))
        if (door["type"] != "DOOR_OBSERVED" or door["node"] != "rs0" or
                CALLBACK not in door["site"] or
                door.get("exception_class") !=
                "org.apache.zookeeper.KeeperException$ConnectionLossException"):
            raise ValueError(f"unqualified typed callback door at {door_seq}")
        if (submit["type"] != "TASK_SUBMIT" or submit["node"] != "rs0" or
                submit["site"] != "hbase:ZKNodeTracker.nodeCreated:data-published" or
                claim["type"] != "TASK_CLAIM" or claim["node"] != "rs0" or
                claim["site"] != "hbase:ZKNodeTracker.blockUntilAvailable:monitor-reacquire" or
                submit["correlation"] != claim["correlation"] or
                exit_event["type"] != "REGION_EXIT" or exit_event["node"] != "rs0" or
                TARGET not in claim["occurrence"] or
                claim["occurrence"] != exit_event["occurrence"]):
            raise ValueError(f"unqualified same-tracker transfer at {door_seq}")
        if any(check["seq"] >= door_seq and check["seq"] < exit_seq
               for check in target_checks):
            raise ValueError(f"a post-callback exact target check appeared at {door_seq}")
        paths.append({"typed_door_seq": door_seq, "submit_seq": submit_seq,
                      "claim_seq": claim_seq, "region_exit_seq": exit_seq,
                      "node": "rs0", "token": submit["correlation"],
                      "target_check_after_door": False})

    return {"case_id": "HBASE-27", "evidence_gzip_sha256": digest,
            "event_count": len(events), "healthy_target_check_seqs": [4, 7],
            "same_tracker_transfers": paths, "event_time_door_to_target_check_paths": 0,
            "full_campaign_go": False,
            "reason": "Both typed nodeCreated doors occur after the healthy target checks; "
                      "the same-tracker claims are followed by region exits without another check."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    print(json.dumps(verify(parser.parse_args().events), indent=2, sort_keys=True))
