"""Issue one request through the two-container protocol."""

import os
from pathlib import Path
import socket
import subprocess
import time


def main():
    result = subprocess.run(["sudo", "-n", "docker", "port",
                             "adhocfuzz-tiny-b", "5052/tcp"], check=True,
                            text=True, stdout=subprocess.PIPE).stdout.strip()
    port = int(result.rsplit(":", 1)[1])
    deadline = time.monotonic() + 15
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), 1) as peer:
                peer.settimeout(12)
                peer.sendall(b"r1\n")
                answer = peer.makefile("r", encoding="utf-8").readline().strip()
            break
        except (OSError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    path = Path(os.environ["ADHOCFUZZ_RUN_DIR"]) / "workload-result.txt"
    path.write_text(answer + "\n", encoding="utf-8")
    print(answer)


if __name__ == "__main__":
    main()
