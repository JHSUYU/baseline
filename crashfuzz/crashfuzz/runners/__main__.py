import sys

from . import MODULES, main

if len(sys.argv) < 2 or sys.argv[1] not in MODULES:
    sys.exit(f"usage: python3 -m crashfuzz.runners {{{'|'.join(MODULES)}}} [runner options]")
sys.exit(main(sys.argv[1], sys.argv[2:]))
