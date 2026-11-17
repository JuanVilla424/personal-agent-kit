// live.js — the live layer of the brain page. REAL EVENTS ONLY.
// It uses the page's own protocol: window.agentBrain.ingest({path, text, ref}) and
// window.__BRAIN.setMode(true), which relabels the log "real events". Every text it shows comes
// from the page's catalog (I18N in index.html) through __BRAIN.t.
// Source: SSE /api/brain/stream. The server numbers every event (the SSE id): events that share
// a second all arrive, a reconnection continues at the exact one, and the bus reaches the page in
// about 20 ms. The initial seed is ONLY the recent past (≤45 s): a reload does NOT replay old
// history as if it were current. No connection: the brain stays calm, nothing is made up.
(function () {
  "use strict";
  const B = window.__BRAIN;
  const AB = window.agentBrain;
  if (!B || !AB) return; // a page without the hooks: nothing to do
  const POLL_MS = 4000;      // fallback polling (only without EventSource)
  const STATE_MS = 60000;    // regions: baseline refresh (in between, the stream says when the state changed)
  const SEED_RECENT_MS = 45 * 1000; // on open: ONLY the last 45 s (cap 6)
  const FETCH_TIMEOUT_MS = 10000;
  const FRAME_BUDGET = 4;    // events drawn per animation frame: a burst must not stall the 3D
  let stateLast = null, stateError = "", stateFetched = 0, stateFlight = null, stateTimer = null;
  let stateRetry = POLL_MS, stream = null, seedTimer = null, seedRetry = POLL_MS;
  let since = "", seenBoot = "", seenSeq = -1; // the place of this page in the numbered stream
  let waiting = [], spent = 0, armed = false;  // events waiting for their animation frame
  let cursor = null;                           // ISO time of the last event taken

  async function readJson(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const r = await fetch(url, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return await r.json();
    } finally { clearTimeout(timer); }
  }
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const lang = () => (typeof B.lang === "function" ? B.lang() : "en");
  // a message of the catalog with its placeholders filled
  const say = (key, values) => String(B.t(key)).replace(/\{(\w+)\}/g, (_, name) =>
    values && values[name] != null ? values[name] : "—");
  const shown = (key, values) => ({ en: esc(say(key, values)) }); // what a region holds: markup, by language
  const fmtNumber = n => Number.isFinite(n) ? new Intl.NumberFormat(lang(), { maximumFractionDigits: 3 }).format(n) : "—";
  const fmtTs = ts => {
    if (!ts || !Number.isFinite(new Date(ts).getTime())) return "—";
    return new Intl.DateTimeFormat(lang(), { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }).format(new Date(ts));
  };
  // relative time, with the platform's own plurals
  function ago(ts) {
    const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
    const rtf = new Intl.RelativeTimeFormat(lang(), { numeric: "auto" });
    if (s < 15) return rtf.format(0, "second");
    if (s < 60) return rtf.format(-Math.round(s), "second");
    if (s < 3600) return rtf.format(-Math.max(1, Math.round(s / 60)), "minute");
    return rtf.format(-Math.max(1, Math.round(s / 3600)), "hour");
  }

  // ── live indicator: connection state and last event, in the page's header console ──
  let connected = false, lastEvTs = null;
  function renderBadge() {
    const b = document.getElementById("liveRec"); if (!b) return;
    b.classList.toggle("on", connected);
    b.children[1].textContent = say(connected ? "liveFeed" : "reconnecting");
    const sub = lastEvTs ? say("lastEvent", { when: ago(lastEvTs) }) : "";
    b.children[2].textContent = sub;
    b.title = say("liveBrain") + (sub ? " · " + sub : "");
  }
  setInterval(renderBadge, 1000); // the relative time stays fresh

  // ── the health panel ──
  const STATUS = { ok: "stOk", stale: "stStale", missing: "stMissing", invalid: "stInvalid", down: "stDown", warn: "stWarn", unknown: "stUnknown" };
  const CHECKS = { services: "checkServices", memory: "checkMemory", memory_user: "checkMemoryUser", snapshot: "checkSnapshot" };
  const CYCLES = { night: "cycleNight" };
  const statusOf = row => stateError ? "stale" : row && STATUS[row.status] ? row.status : "unknown";
  const statusTag = row => {
    const st = statusOf(row), cls = st === "ok" ? "ok" : st === "down" || st === "invalid" ? "bad" : "warn";
    return '<span class="tag ' + cls + '">' + esc(say(STATUS[st])) + "</span>";
  };
  const sourceNote = row => '<span class="source-note"><code>' + esc((row && row.source) || say("noData")) + "</code> · " + esc(fmtTs(row && row.ts)) + "</span>";
  function checkText(c) {
    const label = say(CHECKS[c.id] || "noData");
    if (c.id === "services") return c.status === "ok" ? say("servicesUp") : say("servicesDown", { detail: c.detail || "—" });
    return c.detail == null || c.detail === "" ? label : say("checkDetail", { label, detail: c.detail });
  }
  function renderHealth(s) {
    const h = s && s.health;
    const ul = document.getElementById("healthChecks");
    if (ul) {
      const rows = h ? [...(Array.isArray(h.checks) ? h.checks : []),
        ...(h.snapshot ? [{ ...h.snapshot, id: "snapshot", detail: h.snapshot.generation }] : [])] : [];
      ul.innerHTML = rows.length ? rows.map(c =>
        "<li>" + statusTag(c) + "<span>" + esc(checkText(c)) + sourceNote(c) + "</span></li>"
      ).join("") : '<li><span class="tag warn">' + esc(say("stWarn")) + "</span><span>" + esc(say("noData")) + "</span></li>";
    }
    const cov = document.getElementById("covNow"), covBar = document.getElementById("covBar"), covTs = document.getElementById("covTs");
    if (cov && covBar) {
      const c = h && h.coverage;
      const valid = c && Number.isFinite(c.total), target = c && c.target;
      cov.textContent = valid ? fmtNumber(c.total) : "—";
      covBar.querySelector("i").style.width = (valid ? Math.max(0, Math.min(100, c.total)) : 0) + "%";
      covBar.setAttribute("aria-label", valid ? fmtNumber(c.total) + "%" : say("noData"));
      const threshold = covBar.querySelector(".thr");
      if (threshold) { threshold.hidden = !Number.isFinite(target); if (!threshold.hidden) threshold.style.left = Math.max(0, Math.min(100, target)) + "%"; }
      const goal = document.getElementById("covGoal"), scope = document.getElementById("covScope");
      if (goal) goal.textContent = Number.isFinite(target) ? say("covGate", { target: fmtNumber(target) }) : " %";
      if (scope) scope.textContent = valid ? say("covScope", { files: fmtNumber(c.files), lines: fmtNumber(c.lines_valid) }) : say("noData");
      if (covTs) covTs.innerHTML = c ? statusTag(c) + sourceNote(c) : statusTag({ status: "missing" });
    }
    const bn = document.getElementById("benchNow"), bb = document.getElementById("benchBar"), bts = document.getElementById("benchTs");
    if (bn && bb) {
      const b = h && h.benchmark;
      bn.textContent = b ? fmtNumber(b.score) : "—";
      bb.querySelector("i").style.width = (b ? Math.max(0, Math.min(100, b.score * 100)) : 0) + "%";
      bb.setAttribute("aria-label", b ? b.score + " / 1" : "—");
      if (bts) bts.innerHTML = b ? statusTag(b) + sourceNote(b) : statusTag({ status: "missing" });
      const scope = document.getElementById("benchScope");
      if (scope) scope.textContent = b ? say("benchItems", { n: fmtNumber(b.items) }) : say("noData");
    }
    const wm = document.getElementById("healthWm");
    if (wm) {
      const rows = (h && Array.isArray(h.cycles) && h.cycles) || [];
      wm.innerHTML = rows.length ? rows.map(w =>
        '<li><span class="k">' + esc(say(CYCLES[w.id] || "noData")) + "</span>" + statusTag(w) + sourceNote(w) + "</li>"
      ).join("") : '<li><span class="k">—</span><span>' + esc(say("noData")) + "</span></li>";
    }
    const summary = document.getElementById("healthSummary");
    if (summary) {
      const seen = h ? [...(h.checks || []), ...(h.cycles || []), ...Object.values(h.sources || {}), ...(h.snapshot ? [h.snapshot] : [])] : [];
      summary.textContent = stateError ? say("healthUnavailable") : seen.length ? say("healthCount", {
        fresh: fmtNumber(seen.filter(c => c.status === "ok").length),
        attention: fmtNumber(seen.filter(c => c.status !== "ok").length) }) : say("noData");
      const quick = document.getElementById("healthQuick");
      if (quick) quick.textContent = summary.textContent;
    }
  }
  function renderCycle(s) {
    const h = s.health || {}, lessons = s.lessons || {}, mh = s.memory_health || {};
    const night = (h.cycles || []).find(c => c.id === "night");
    const entries = Number.isFinite(mh.entries) && Number.isFinite(mh.user_entries) ? mh.entries + mh.user_entries : null;
    const cells = {
      tasks: [say("openTasks", { n: fmtNumber(s.tasks && s.tasks.total) }), "TASKS.md", "#regions"],
      memory: [say("cycleMemory", { lessons: fmtNumber(lessons.count), entries: fmtNumber(entries) }), lessons.source || "/memory/health", "#health"],
      night: [night ? say("cycleNightSeen", { status: say(STATUS[statusOf(night)]), when: fmtTs(night.ts) }) : say("noData"), (night && night.source) || "—", "#health"],
      protocols: [say("cycleProtocols", { n: fmtNumber((s.protocols || []).length) }), (s.git || [])[0] || "—", "#regions"],
    };
    document.querySelectorAll("#cycleLive [data-cycle]").forEach(el => {
      const cell = cells[el.dataset.cycle];
      if (cell) el.innerHTML = "<span>" + esc(cell[0]) + '</span><span class="source-note">' + esc(cell[1]) + '</span><a href="' + cell[2] + '">' + esc(say("inspect")) + "</a>";
    });
  }

  // ── regions with real state (the inspector shows it when a region is selected) ──
  function patchNodes(s) {
    const put = (id, state, trace, status = "ok") => {
      const node = B.byId[id]; if (!node) return;
      node.state = state; node.trace = trace; node.status = status;
    };
    Object.keys(B.byId).forEach(id => put(id, shown("noObservation"), shown("noProbe"), "unknown"));
    const titles = (s.tasks && s.tasks.pending_titles) || [], total = s.tasks && s.tasks.total;
    put("dlpfc", shown("openTasks", { n: fmtNumber(total) }),
      shown("tasksTrace", { title: titles[0] || say("noTitles") }), Number.isFinite(total) ? "ok" : "unknown");
    const counters = (s.guard && s.guard.counters) || {};
    const verdicts = Object.values(counters).reduce((sum, c) => sum + (Number(c && c.total) || 0), 0);
    put("cb", shown("verdicts", { n: fmtNumber(verdicts) }), shown("verdictsTrace"), Object.keys(counters).length ? "ok" : "unknown");
    const protocols = (s.protocols || []).length, commit = (s.git && s.git[0]) || "";
    put("bg", shown("protocolCount", { n: fmtNumber(protocols) }),
      commit ? shown("gitTrace", { commit }) : shown("noGit"), protocols ? "ok" : "unknown");
    const mh = s.memory_health || {}, up = mh.status === "ok";
    put("atl", up ? shown("memoryHealthy", { shared: fmtNumber(mh.entries || 0), personal: fmtNumber(mh.user_entries || 0) }) : shown("memoryDegraded"),
      shown("memoryTrace"), up ? "ok" : "down");
    const lessons = s.lessons || {};
    put("post", shown("lessonCount", { n: fmtNumber(lessons.count) }),
      lessons.source ? { en: esc(lessons.source) } : shown("noSource"), Number.isFinite(lessons.count) ? "ok" : "unknown");
    const a2a = s.a2a || [];
    put("apfc", shown("delegations", { n: fmtNumber(a2a.length) }),
      a2a[0] ? shown("a2aTrace", a2a[0]) : shown("noA2a"), a2a[0] ? "ok" : "unknown");
    const h = s.health || {}, backup = h.snapshot || {};
    put("tha", backup.generation ? { en: esc(backup.generation) } : shown("noBackup"),
      backup.source ? { en: esc(backup.source) } : shown("noSource"), backup.status || "unknown");
    const storage = (h.checks || []).find(c => c.id === "memory");
    if (storage) put("hip", shown(storage.status === "ok" ? "storageUp" : "storageDown"),
      { en: esc(storage.source || "") }, storage.status === "ok" ? "ok" : "down");
    const generation = document.getElementById("snapshotGen");
    if (generation) { generation.textContent = backup.generation || "—"; generation.title = backup.source || ""; }
    renderHealth(s);
    renderCycle(s);
    if (typeof B.refresh === "function") B.refresh();
  }

  // ── ingest: every REAL event enters through the page's own protocol ──
  function ingest(ev) {
    const side = (ev.side === "L" || ev.side === "R" || ev.side === "both") ? ev.side : undefined;
    AB.ingest({
      path: ev.path,
      side,
      text: (typeof ev.text === "string" ? ev.text : "") + " · " + ago(ev.ts), // raw: the page escapes it
      ref: ev.ref ? ev.kind + " · " + ev.ref : ev.kind || "",
      meta: { kind: ev.kind, origin: ev.origin || "", tag: ev.tag || "" },
    });
    if (typeof B.observePulse === "function") B.observePulse(ev);
    lastEvTs = ev.ts;
    // context compaction: a momentary convulsion of the hypothalamus. The moment context is
    // sacrificed must stay visibly recorded
    if (ev.kind === "compact" && B.runPath) {
      for (let i = 0; i < 9; i++) setTimeout(() => {
        try { B.runPath(["hypo", "tha"]); B.runPath(["hypo", "amy"]); B.activate("hypo", 1.2); } catch (_) {}
      }, i * 180);
    }
  }

  // ── the feed: the recent past once, then the numbered stream ──
  async function fetchFeed(afterIso) {
    const q = afterIso ? "?after=" + encodeURIComponent(afterIso) + "&_=" + Date.now() : "?_=" + Date.now();
    const data = await readJson("/api/brain/events" + q);
    if (!Array.isArray(data.events)) throw new Error("Invalid events response");
    return data;
  }
  async function seed() {
    const feed = await fetchFeed(""), evs = feed.events; // newest first
    const recent = evs.filter(ev => Date.now() - new Date(ev.ts).getTime() <= SEED_RECENT_MS).slice(0, 6);
    recent.slice().reverse().forEach((ev, i) => setTimeout(() => ingest(ev), 100 + 120 * i));
    cursor = evs.length ? evs[0].ts : new Date().toISOString();
    since = typeof feed.cursor === "string" ? feed.cursor : "";
    const cut = since.lastIndexOf("-");
    seenBoot = cut > 0 ? since.slice(0, cut) : "";
    seenSeq = cut > 0 ? Number(since.slice(cut + 1)) : -1;
  }
  function fresh(m) {
    const id = (m && m.lastEventId) || "", cut = id.lastIndexOf("-");
    const seq = cut > 0 ? Number(id.slice(cut + 1)) : NaN;
    if (!Number.isInteger(seq)) return true;
    const boot = id.slice(0, cut);
    if (boot === seenBoot && seq <= seenSeq) return false;
    seenBoot = boot; seenSeq = seq;
    return true;
  }
  function nextFrame(fn) {
    let done = false;
    const once = () => { if (!done) { done = true; fn(); } };
    if (!document.hidden && typeof requestAnimationFrame === "function") requestAnimationFrame(once);
    setTimeout(once, document.hidden ? 0 : 100); // rAF sleeps in a hidden tab: real events do not wait for it
  }
  function draw(ev) { try { ingest(ev); } catch (_) { /* one bad event does not hold the rest */ } }
  function pump() {
    armed = false; spent = 0;
    while (waiting.length && spent < FRAME_BUDGET) { spent++; draw(waiting.shift()); }
    if (spent) arm(); // something was drawn in this frame: the next one opens with a fresh budget
  }
  function arm() { if (!armed) { armed = true; nextFrame(pump); } }
  function deliver(ev) {
    if (!waiting.length && spent < FRAME_BUDGET) { spent++; draw(ev); }
    else waiting.push(ev);
    arm();
  }
  function openStream() {
    if (typeof EventSource === "undefined") return;
    if (stream) stream.close();
    const es = new EventSource("/api/brain/stream" + (since ? "?since=" + encodeURIComponent(since) : ""));
    stream = es;
    es.onmessage = m => {
      try {
        const ev = JSON.parse(m.data);
        if (!fresh(m)) return;
        deliver(ev);
        if (ev.ts > (cursor || "")) cursor = ev.ts;
        connected = true; renderBadge();
        B.setMode(true);
      } catch (_) { /* a corrupt event does not bring the layer down */ }
    };
    es.addEventListener("state", () => { stateTick(); });
    es.onerror = () => { connected = false; B.setMode(false); renderBadge(); };
    es.onopen = () => { connected = true; B.setMode(true); renderBadge(); };
  }
  function pollFallback() {
    if (typeof EventSource !== "undefined" || !cursor) return;
    fetchFeed(cursor).then(feed => {
      const evs = feed.events;
      if (evs.length) { cursor = evs[0].ts; evs.slice().reverse().forEach(ev => ingest(ev)); }
      connected = true;
    }).catch(() => { connected = false; });
  }
  function connectFeed() {
    clearTimeout(seedTimer);
    seed().then(() => {
      seedRetry = POLL_MS;
      if (typeof EventSource === "undefined") { connected = true; B.setMode(true); renderBadge(); }
      else openStream();
    }).catch(() => {
      connected = false; B.setMode(false); renderBadge();
      seedTimer = setTimeout(connectFeed, seedRetry);
      seedRetry = Math.min(STATE_MS, seedRetry * 2);
    });
  }

  // ── the state: read at open, when the stream says it changed, and as a slow baseline ──
  async function stateTick() {
    if (stateFlight) return stateFlight;
    clearTimeout(stateTimer);
    const button = document.getElementById("refreshState");
    if (button) button.disabled = true;
    stateFlight = (async () => {
      try {
        const s = await readJson("/api/brain/state?_=" + Date.now());
        if (!s || typeof s !== "object" || Array.isArray(s)) throw new Error("Invalid state response");
        stateError = ""; stateLast = s; stateFetched = Date.now(); stateRetry = POLL_MS;
        patchNodes(s);
      } catch (error) {
        stateError = /^HTTP \d+$/.test(error.message) ? error.message : error.name === "AbortError" ? "timeout" : "network";
        Object.values(B.byId).forEach(n => { n.status = "stale"; n.state = shown("staleEvidence"); n.trace = shown("stateUnreachable"); });
        if (typeof B.refresh === "function") B.refresh();
        renderHealth(stateLast);
      } finally {
        stateFlight = null;
        if (button) button.disabled = false;
        renderStateStatus();
        stateTimer = setTimeout(stateTick, stateError ? stateRetry : STATE_MS);
        if (stateError) stateRetry = Math.min(STATE_MS, stateRetry * 2);
      }
    })();
    return stateFlight;
  }
  function renderStateStatus() {
    const el = document.getElementById("stateRec"); if (!el) return;
    const late = stateFetched && Date.now() - stateFetched > STATE_MS * 2;
    el.dataset.status = stateError ? "error" : late ? "stale" : stateFetched ? "ok" : "loading";
    el.textContent = stateError ? say("stateError", { why: stateError })
      : stateFetched ? say(late ? "stateLate" : "stateFresh", { when: ago(new Date(stateFetched).toISOString()) })
      : say("stateLoading");
  }
  function redrawEvidence() {
    if (stateLast && !stateError) patchNodes(stateLast);
    else renderHealth(stateLast);
    renderStateStatus();
  }

  window.addEventListener("brain:language", redrawEvidence);
  const refresh = document.getElementById("refreshState");
  if (refresh) refresh.addEventListener("click", stateTick);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) stateTick(); });
  window.addEventListener("pagehide", () => { if (stream) stream.close(); clearTimeout(stateTimer); clearTimeout(seedTimer); });
  setInterval(renderStateStatus, 1000);
  setInterval(pollFallback, POLL_MS);
  renderStateStatus();
  connectFeed();
  stateTick();
})();
