# Grafana Dashboard Rules — Canonical Base

![Status](https://img.shields.io/badge/Status-Canonical-green.svg)
![Scope](https://img.shields.io/badge/Scope-All%20Boards-blue.svg)

The baseline every Grafana board in this organization must meet before being
shown to a person. Sources: Grafana official best practices, Grafana Labs
design guidance, Google SRE signals, and the hard lessons from building the
personal-agent-kit stack (three review rounds with screenshots).

---

## 1. Before building a single panel

- **Every dashboard answers ONE question or tells ONE story.** If you cannot
  state its goal in a sentence, do not build it.
- **Know the audience**: an operator needs state-at-a-glance; a manager needs
  trends and cost. Different audiences = different boards, not more panels.
- **Pick the observability method per layer** and let it choose your metrics:
  - **RED** for services (Rate, Errors, Duration) — symptoms, what users feel.
    This is where alerts belong.
  - **USE** for infrastructure (Utilization, Saturation, Errors) — causes.
  - **Four Golden Signals** for user-facing systems (Latency, Traffic,
    Errors, Saturation).
- **Reduce cognitive load**: someone who did not build the board must
  understand it without asking.

## 2. Layout and hierarchy

- People scan in a **Z pattern**: the most critical state goes **top-left**;
  detail and drill-down flow downward.
- **Size = importance.** Big stat panels for the verdict, smaller panels for
  the supporting evidence.
- Logical progression: overview row → domain rows → detail. No layout holes;
  every row is complete.
- One screen per audience question. If you scroll twice, split the board.

## 3. Panels

- **One question per panel, answered in the title** ("RAM disponible por
  instancia (MB)", never "Datos").
- **Every panel has a `description`** (the `?` tooltip): what it measures and
  when to worry.
- **Explicit unit, always**: `dtdurations` for ages/uptimes, `currencyUSD`,
  `percent` with `min: 0, max: 100`, `bytes`, `s`. A raw number is a bug.
- **States read as states**: 0/1/2 get value mappings (OK/WARN/ALERT) or a
  state-timeline — never naked numbers. Booleans map to UP/DOWN, OK/FAILED.
- **Zero is data**: idle counters show `0` (`or vector(0)` + `noValue: "0"`).
  Run-based sources show "No runs yet". A user-facing "No data" is a bug.
- Sparse/push-based series: `showPoints: always` + `spanNulls: true` or the
  single datapoint is invisible.
- Keep graphs simple; avoid stacking (it hides and misleads).

## 4. Color and thresholds

- **Color is action**: green = ok, yellow = watch, red = act. Anything else
  uses neutral `text` color. Decorative color is noise.
- **NEVER ship Grafana's default threshold (red at 80).** It paints healthy
  values as critical (uptime "27 minutes" in red). Every stat defines its
  thresholds intentionally or uses neutral color.
- **Every red must map to an alert rule** — if it is worth painting red, it
  is worth alerting; if it is not worth alerting, reconsider the red.
- Show the line: `thresholdsStyle: dashed` on graphs with thresholds, so the
  viewer sees the distance to the problem, not just the state.
- Avoid red-green-only encodings (colorblind users); pair color with text
  (mappings) or position.

## 5. Queries

- **Aggregate everything**: `max by ()` / `sum by ()` on every query. Stale
  label variants (after adding a label like `host`) otherwise duplicate every
  stat within the time window.
- **`instant: true` on stats of "current value" or freshness** over long
  ranges: range queries evaluate `time()` at the last step, which can lag
  ~30 min on a 30d window ("5 minutes" shown when the truth was 37).
- Counters get `rate()`/`increase()`; gauges get last value. Pushgateway
  metrics are gauges with run semantics: expose `<job>_last_run_timestamp_seconds`,
  `<job>_last_run_success`, `<job>_run_duration_seconds` from EVERY job — a
  job missing `success` is invisible in the health panel (it happened twice).
- Legends are human: `{{service}}`, `{{account}} · {{resource}}` with
  separators. Legend table (right, last/max) when > 4 series; list below
  otherwise.

## 6. Variables and reuse

- Template variables instead of dashboard copies (one parameterized board,
  not one board per account/node). `includeAll` needs an explicit
  `allValue: ".*"`.
- Never copy a board for a small tweak — parameterize. If you must copy:
  rename clearly and **do not copy the tags**.

## 7. Navigation

- All boards share the org tag (here: `personal-agent-kit`) and a dashboard-links
  dropdown ("Boards") with `keepTime: true` — any board reaches any other.
- Set the org **home dashboard** to the overview/coverage board.
- Alerts must lead back to dashboards (annotation/links), and dashboards show
  active alerts (alertlist panel on the overview).
- Annotate operational events (restarts, deploys) so gaps and resets explain
  themselves.

## 8. Time and refresh

- Default time range matches data cadence: host 6h, services 6-24h, run-based
  scripts 7d.
- Refresh no faster than the scrape/update interval (30s scrape → 30s-1m
  refresh). Faster refresh is pure backend load.

## 9. Visual polish (correctness is not enough)

Rules 1-8 make a board truthful and usable; they do NOT make it look
professional. Grafana's default rendering is intentionally plain — polished
boards activate the visual layer deliberately:

- **Color language everywhere, as tiles**: stats use `colorMode: background`
  so state reads as colored cards — blue = info, green = ok, yellow = watch,
  red = act. A wall of white numbers on black is a default, not a design.
- **Radial gauges for capacity**: current CPU/RAM/disk render as `gauge`
  panels with threshold markers — the viewer sees how full AND how far from
  the red line. Keep the timeseries next to it for history.
- **Living lines**: timeseries get `lineInterpolation: smooth`,
  `gradientMode: opacity`, `fillOpacity ≥ 20`. Flat 1px lines on black read
  as unfinished.
- **Gradient bargauges** (`displayMode: gradient`) instead of basic bars.
- **Section rows**: boards covering more than two domains group panels under
  `row` headers — scanning beats hunting.
- **Sparklines on counters** (`graphMode: area`) where history exists.
- **Density**: no dead space — a board that fills one screen tightly looks
  intentional; scattered small panels over a black void look broken.

## 10. Lifecycle (dashboards as code)

- **Boards live as provisioned JSON in git** (`grafana/dashboards/*.json`),
  never as hand-edits in the UI. The UI is for viewing; files are the truth.
- Validate JSON before shipping; verify renders with real screenshots —
  defaults lie, and only the rendered pixel tells you.
- Meaningful names; experiments carry `TEST`/`TMP` prefix and get deleted.
- Audit periodically: remove abandoned boards; track what is actually used.
- Same metric ⇒ same unit, same color semantics on every board.

---

## Pre-publish checklist (gate)

1. Does the board's title answer its question in one sentence?
2. Is the critical stuff top-left, with no layout gaps?
3. Does every panel have an explicit unit and a description?
4. Zero default thresholds? Does every red map to an alert?
5. States use mappings (never naked 0/1/2)?
6. Is "No data" impossible? (`noValue` or `or vector(0)` everywhere)
7. Is every query aggregated (`max by`/`sum by`)?
8. Do freshness/last-value stats use `instant: true`?
9. Tag + navigation link + range/refresh matching the cadence?
10. JSON in git, validated, and verified with a rendered screenshot?

**Referencias**: [Grafana dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/) ·
[Grafana Labs — design your first dashboard](https://grafana.com/blog/2024/07/03/getting-started-with-grafana-best-practices-to-design-your-first-dashboard/)
