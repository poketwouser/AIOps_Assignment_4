#!/usr/bin/env bash
cd "$(dirname "$0")"
for f in run/*.pid; do
  [ -f "$f" ] || continue
  kill "$(cat "$f")" 2>/dev/null && echo "stopped $(basename "$f" .pid)"
  rm -f "$f"
done
docker rm -f a4-grafana >/dev/null 2>&1 && echo "stopped grafana"
