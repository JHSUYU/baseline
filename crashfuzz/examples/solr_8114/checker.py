"""Read the final document through a fresh request after fault injection."""

import sys
import time

from workload import both


def main() -> int:
    deadline = time.monotonic() + 60
    last = ""
    while time.monotonic() < deadline:
        try:
            row = both("/adhoc8114/select?q=id:sentinel8114&wt=json",
                       attempts=1)
            if (row.get("responseHeader", {}).get("status") == 0
                    and row["response"]["numFound"] == 1):
                print("verified final Solr document: sentinel8114")
                return 0
            last = str(row)
        except (RuntimeError, ValueError, KeyError) as error:
            last = str(error)
        time.sleep(2)
    print("Solr checker did not observe sentinel8114: " + last)
    return 1


if __name__ == "__main__":
    sys.exit(main())
