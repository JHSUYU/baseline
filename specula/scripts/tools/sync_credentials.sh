#!/usr/bin/env bash
# sync_credentials.sh [--once] -- keep every node on the owner's one Claude login (owner, 2026-11-02).
# Every 5 min: read ~/.claude/.credentials.json's expiresAt on node0-node4, take the freshest copy, and
# write it to every node whose copy differs, so all nodes follow one refresh-token chain.
nodes="node0 node1 node2 node3 node4"
while true; do
  best=""; bestexp=0
  for n in $nodes; do
    e=$(ssh -o BatchMode=yes -o ConnectTimeout=8 $n "python3 -c \"import json,os;print(json.load(open(os.path.expanduser('~/.claude/.credentials.json')))['claudeAiOauth']['expiresAt'])\"" 2>/dev/null)
    [[ $e =~ ^[0-9]+$ ]] && (( e > bestexp )) && { bestexp=$e; best=$n; }
  done
  if [[ -n $best ]]; then
    src=$(ssh -o BatchMode=yes $best 'cat ~/.claude/.credentials.json')
    for n in $nodes; do
      [[ $n == "$best" ]] && continue
      cur=$(ssh -o BatchMode=yes $n 'cat ~/.claude/.credentials.json 2>/dev/null')
      if [[ "$cur" != "$src" ]]; then
        printf '%s' "$src" | ssh -o BatchMode=yes $n 'umask 077; mkdir -p ~/.claude; cat > ~/.claude/.credentials.json.new && mv ~/.claude/.credentials.json.new ~/.claude/.credentials.json'
        echo "$(date -u +%FT%TZ) copied $best -> $n (expiresAt $bestexp)"
      fi
    done
  fi
  [[ $1 == --once ]] && break
  sleep 300
done
