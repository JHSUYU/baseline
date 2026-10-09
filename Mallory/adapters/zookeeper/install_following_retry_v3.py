#!/usr/bin/env python3
"""Extend the versioned FOLLOWING hook to cover normal follower exit/retry."""

import argparse
from pathlib import Path


def install(root: Path) -> None:
    peer = root / ("zookeeper-server/src/main/java/org/apache/zookeeper/"
                   "server/quorum/QuorumPeer.java")
    old = peer.read_text(encoding="utf-8")
    before = """                        } catch (Exception e) {
                            MalloryZkHooks.followingRetrySubmit(this);
                            LOG.warn("Unexpected exception", e);
                        } finally {
                            follower.shutdown();
                            setFollower(null);
                            updateServerState();
                        }
"""
    after = """                        } catch (Exception e) {
                            LOG.warn("Unexpected exception", e);
                        } finally {
                            follower.shutdown();
                            setFollower(null);
                            updateServerState();
                            // followLeader may return normally after its own I/O recovery.
                            // Submit for either exit; only an exact later FOLLOWING claims it.
                            if (isRunning()) {
                                MalloryZkHooks.followingRetrySubmit(this);
                            }
                        }
"""
    if old.count(before) != 1:
        raise ValueError("expected exactly one compiled v2 FOLLOWING branch")
    peer.write_text(old.replace(before, after), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patched_source_root", type=Path)
    args = parser.parse_args()
    install(args.patched_source_root.resolve())
