#!/usr/bin/env python3
"""Healthy calibration of an unchanged original leader-change JUnit method."""

from pathlib import Path

import run
from build import HERE


def main() -> None:
    run.TEST_METHOD = 'testRetryUpdatesWhenClusterStateIsStale'
    output = HERE / 'supplemental/stale-leader/healthy-01'
    agent = HERE / 'solrleadership-independent-agent.jar'
    raise SystemExit(run.run(output, agent_path=agent))


if __name__ == '__main__':
    main()
