# Personal Agent Kit Monitoring Stack

![Prometheus](https://img.shields.io/badge/Prometheus-3.2-orange.svg)
![Grafana](https://img.shields.io/badge/Grafana-11.5-yellow.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)
![Status](https://img.shields.io/badge/Status-Active-green.svg)

Local metrics stack for the agent host: Prometheus (storage + scraping),
Pushgateway (one-shot script metrics) and Grafana (dashboards).

## Architecture

```
Slack bot exporter (:9090/metrics) ──scrape──┐
node-exporter (host CPU/mem/disk)  ──scrape──┤
one-shot scripts ──push──> Pushgateway (:9391) ──scrape──┤
                                                          ├─> Prometheus (:9390) ─> Grafana (:9392)
```

Attribution is enforced by the push contract (`ops/metrics_push.py`): every
push is grouped by `host` + `invoked_by`, and bot metrics carry `channel_id` /
`user_id` — so if you ever run this on more than one machine of your own, the
data stays filterable in Grafana instead of colliding.

## Ports (non-default on purpose)

| Service     | Host port | Container port | URL                   |
| ----------- | --------- | -------------- | --------------------- |
| Prometheus  | 9390      | 9090           | http://localhost:9390 |
| Pushgateway | 9391      | 9091           | http://localhost:9391 |
| Grafana     | 9392      | 3000           | http://localhost:9392 |

Avoided: 9090 (bot exporter) and 9091 (bot FastAPI health endpoint), both already
bound on the host.

## Getting Started

1. `cp .env.example .env` and set the Grafana admin credentials
2. `docker compose up -d`
3. Open http://localhost:9392 (login with credentials from `.env`)

All boards under the `Personal Agent Kit` folder are auto-provisioned from
`grafana/dashboards/*.json` — the single source of truth for dashboards
(edit the JSON, never the UI).

## Scrape targets

Defined in `prometheus/prometheus.yml`:

- `slack-bot` — `host.docker.internal:9090` (bot exporter, `local/scripts/notify/ops/metrics.py`)
- `pushgateway` — `pushgateway:9091` (`honor_labels: true` so pushed job/instance labels win)
- `prometheus` — self-monitoring

Retention: 180 days (`--storage.tsdb.retention.time=180d`).

## Pushing metrics from one-shot scripts

Scripts that run-and-exit (memory_index, the report generators) cannot be scraped — they must
push their final values to the Pushgateway before exiting, via `ops/metrics_push.py`. See
that module's docstring for the contract (grouping by `host`/`invoked_by`, best-effort —
never raises).

## Dashboard presentation rules (minimum bar)

**Canonical rules: [`GRAFANA-DASHBOARD-RULES.md`](GRAFANA-DASHBOARD-RULES.md)** —
the full base for every Grafana board (observability methods, layout, color,
queries, lifecycle, pre-publish checklist). The summary below is the quick
panel-level bar; the canonical doc governs.

Every panel in every dashboard MUST comply before showing it to a person.
These rules exist because Grafana defaults actively mislead: the default
threshold (red at 80) paints healthy values as critical, and counters with no
activity render "No data" instead of 0.

1. **Explicit unit, always** — seconds as `dtdurations`, money as `currencyUSD`,
   percent with `min: 0, max: 100`, bytes as `bytes`. Never a raw number.
2. **One question per panel, answered in the title** — and a `description`
   (the `?` tooltip) saying what it measures and when to worry.
3. **Intentional thresholds only** — color = action: green ok, yellow watch,
   red act (and the red must map to an alert rule when possible). Neutral
   values use `text` color. NEVER leave Grafana's default 80-threshold.
4. **Zero is data** — idle counters show `0` (`or vector(0)` / `noValue: "0"`),
   run-based sources show "No runs yet". "No data" is forbidden as a
   user-facing state.
5. **Aggregate every query** — `max by ()` / `sum by ()` so stale label
   variants never duplicate stats (e.g. after adding the `host` label).
6. **Human legends** — `{{service}}`, `{{account}} · {{resource}}` with
   separators; legend table (right, with last/max) when > 4 series.
7. **Sparse series stay visible** — `showPoints: always` + `spanNulls: true`
   on anything pushed by one-shot scripts.
8. **States read as states** — 0/1/2 get value mappings (OK/WARN/ALERTA) or a
   state-timeline, never a naked number.
9. **Time range matches data cadence** — host 6h, bot 6h, usage 24h,
   scripts 7d. Refresh no faster than the scrape (30s).
10. **Consistency across dashboards** — same metric, same unit, same color
    semantics everywhere.

## Operations

```bash
# Status / logs
docker compose ps
docker compose logs -f prometheus

# Reload Prometheus config without restart
curl -X POST http://localhost:9390/-/reload

# Stop / start
docker compose down        # keeps data (named volumes)
docker compose up -d
```
