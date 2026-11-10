#!/bin/bash
# host-bot-relay.sh — push the two scrape-only exporters (node-exporter + bot) up to
# the pushgateway. The system is push-only (nothing scrapes locally nor
# writes to Prometheus), so these exporters are relayed like every other job.
# PUSHGATEWAY_URL is read from the root .env (never hardcode the host).
ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.env"
GW=$(grep -E '^PUSHGATEWAY_URL=' "$ENV" 2>/dev/null | head -1 | sed -E 's/^[^=]*=//' | tr -d '\r' | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')
[ -n "$GW" ] || GW="http://localhost:9391"
HOST="$(hostname)"

# node-exporter is not host-published; reach it by its container IP on the docker net
NEIP=$(docker inspect personal-agent-kit-node-exporter --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' 2>/dev/null | awk '{print $1}')
if [ -n "$NEIP" ]; then
  curl -sf --max-time 6 "http://${NEIP}:9100/metrics" 2>/dev/null \
    | curl -s -X PUT --data-binary @- --max-time 12 "${GW}/metrics/job/node/instance/${HOST}" >/dev/null 2>&1
fi

# slack-bot exporter (host port 9090)
curl -sf --max-time 6 "http://localhost:9090/metrics" 2>/dev/null \
  | curl -s -X PUT --data-binary @- --max-time 12 "${GW}/metrics/job/slack-bot/instance/${HOST}" >/dev/null 2>&1
