#!/usr/bin/env python3
"""cred_sync.py -- keep one Claude login across this node's ~/.claude and every case's agent home.

Every 60 s: take the freshest credentials (by expiresAt) among node0's ~/.claude/.credentials.json and the
case homes, and write it (atomically) to every copy that is older.  An agent container that refreshed its
token thereby passes the new refresh token on before the old one is used again; the Specula setup's
tools/sync_credentials.sh on node2 spreads node0's copy to the other nodes' ~/.claude.
"""
import glob, json, os, time

HOST = os.path.expanduser("~/.claude/.credentials.json")


def exp(p):
    try:
        return json.load(open(p))["claudeAiOauth"]["expiresAt"]
    except Exception:
        return -1


while True:
    files = [HOST] + glob.glob("/bulk/codingagent/cases/*/agent/home/.claude/.credentials.json")
    best = max(files, key=exp)
    be = exp(best)
    if be > 0:
        data = open(best).read()
        for f in files:
            if f != best and exp(f) < be:
                tmp = f + ".sync"
                with open(tmp, "w") as fo:
                    fo.write(data)
                os.chmod(tmp, 0o600)
                os.replace(tmp, f)
                print(time.strftime("%FT%TZ", time.gmtime()), "copied", best, "->", f, flush=True)
    time.sleep(60)
