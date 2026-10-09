#!/usr/bin/env python3
"""Run the original expired-key JUnit with independent control-plane hooks."""

from pathlib import Path
import os
import sys

from prepare_overlay import prepare


HERE = Path(__file__).resolve().parent
overlay = prepare()
os.execv(sys.executable, [sys.executable, str(HERE.parent / "run_original.py"),
                         "--method", "testFileChecksumWithInvalidEncryptionKey",
                         "--parameter", "0", "--overlay", str(overlay), *sys.argv[1:]])
