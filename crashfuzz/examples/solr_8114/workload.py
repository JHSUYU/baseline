"""Issue writes and searches through either surviving SolrCloud node."""

import json
import os
from pathlib import Path
import sys
import time
import uuid

from prepare import request


TRACE = None


class ClientTrace:
    """Publish the workload's HTTP sends for exact header correlation."""

    def __init__(self, directory: Path):
        self.process = "solr-http-client-" + uuid.uuid4().hex
        self.path = directory / ("trace-" + self.process + ".jsonl")
        self.seq = 0
        self.count = 0

    def send(self) -> str:
        self.count += 1
        correlation = self.process + "-" + str(self.count)
        span = str(self.count)
        context = "root/solr-http-request#" + span
        rows = []
        for kind, site in (("METHOD_ENTER", "solr/http#request"),
                           ("MESSAGE_SEND", "solr/http#send"),
                           ("METHOD_EXIT", "solr/http#request")):
            self.seq += 1
            rows.append({"schema": 1, "kind": kind, "node": "client",
                         "process": self.process, "seq": self.seq,
                         "wall_ms": int(time.time() * 1000), "thread": "main",
                         "span": span, "parent": "0", "site": site,
                         "context": context,
                         **({"correlation": "solr-http:" + correlation}
                            if kind == "MESSAGE_SEND" else {})})
        with self.path.open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, sort_keys=True) + "\n")
            out.flush()
        return correlation


def both(path, *, method="GET", data=None, attempts=45):
    last = ""
    for _ in range(attempts):
        for node in ("solr1", "solr2"):
            try:
                correlation = TRACE.send() if TRACE else None
                return request(path, node=node, method=method, data=data,
                               correlation=correlation)
            except (RuntimeError, ValueError) as error:
                last = str(error)
        time.sleep(1.5)
    raise RuntimeError("Solr request failed on both nodes: " + last)


def main() -> int:
    global TRACE
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    TRACE = ClientTrace(run_dir / "traces")
    outputs = []
    for batch in range(3):
        docs = [{"id": "doc-{}-{}".format(batch, number),
                 "title_s": "coordination batch {}".format(batch),
                 "count_i": number} for number in range(20)]
        outputs.append(both("/adhoc8114/update?wt=json", method="POST",
                            data=json.dumps(docs)))
        outputs.append(both("/adhoc8114/select?q=*:*&rows=3&wt=json"))
    outputs.append(both("/adhoc8114/update?commit=true&wt=json",
                        method="POST", data=json.dumps({
                            "delete": {"query": "id:doc-0-*"}})))
    outputs.append(both("/adhoc8114/update?commit=true&wt=json",
                        method="POST", data=json.dumps([
                            {"id": "sentinel8114", "title_s": "sentinel8114"}])))
    result = both("/adhoc8114/select?q=id:sentinel8114&wt=json")
    outputs.append(result)
    (run_dir / "solr-workload.json").write_text(
        json.dumps(outputs, indent=2, sort_keys=True) + "\n")
    if (any(row.get("responseHeader", {}).get("status") != 0
            for row in outputs) or result["response"]["numFound"] != 1):
        print("Solr workload returned an error or missed the sentinel")
        return 1
    print("Solr workload verified sentinel8114")
    return 0


if __name__ == "__main__":
    sys.exit(main())
