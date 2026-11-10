// .opencode/plugins/session-lifecycle.js — ALL hooks based on the generic
// "event" event (session.created, session.idle, permission.asked) live in ONE file.
//
// Why consolidated: each one used to live in its own plugin (memory-hooks.js,
// metrics-hooks.js, session-start.js, tts-hooks.js), mirroring their Claude
// Code equivalents — but tested live, with 4 plugins registering "event" separately,
// only one ever ran (unlike tool.execute.before/after, confirmed to aggregate
// correctly across separate files — rm-guard.js + pre-write-guard.js ran together with no
// issue). The exact cause in the plugin API wasn't confirmed; until it's
// understood, one single file guarantees all four pieces always run.

//
// Pieces (each one equivalent to a real Claude Code hook):
//   - session.created  → SessionStart: temp/ cleanup (session-start.sh — the injection of
//     orientation.txt already lives statically in bin/opencode/opencode.base.json → instructions).
//   - session.idle      → Stop: saves memory if there's a REMEMBER marker (memory-hooks.js),
//     pushes metrics to the Pushgateway (push-claude-code-metric.py), and speaks the response out
//     loud (tts_hook.py) — all three reuse the same assistant message, read ONCE.
//   - permission.asked  → Notification: speaks out loud what permission is being requested.
//
// ON by default; OPENCODE_HOOKS_ENABLED=false turns it off (same gate as the guards).
//
// ⚠️ SDK GOTCHA, confirmed 2026-09-07 via `opencode run --print-logs`: the `client`
// injected into the plugin requires `client.session.messages({ path: { id: sessionID } })` — the
// form documented in the SDK's public examples, `client.session.messages(sessionID)` (a bare
// string), ALWAYS fails with a server error (`Expected a string starting with "ses", got
// "%7Bid%7D"` — the URL's `{id}` template is never substituted with that form). It's not a
// timing race or something intermittent: it's a signature error, 100% reproducible. The
// response also comes wrapped in `{ data: [...] }`, not as a bare array.

import { existsSync, readdirSync, realpathSync, statSync, unlinkSync, rmdirSync, readFileSync, writeFileSync, mkdirSync } from "fs"
import { join, resolve } from "path"
import { hostname } from "os"
import { snapshotInBackground } from "./auto-guard.js"

// Temporary synchronous trace for debugging the session.idle intermittency issue described
// above. Gated behind its own env var so normal usage never touches disk for this.
function _trace(msg) {
  if (process.env.OPENCODE_TRACE_LIFECYCLE !== "true") return
  try {
    writeFileSync(join(process.cwd(), "temp", "lifecycle_trace.log"), `${Date.now()} ${msg}\n`, {
      flag: "a",
    })
  } catch {
    /* best-effort */
  }
}

const DAY_MS = 24 * 60 * 60 * 1000
const MEMORY_URL = (process.env.MEMORY_SERVICE_URL || "http://localhost:7700").replace(/\/$/, "")
const MEMORY_TOKEN = process.env.MEMORY_SERVICE_TOKEN || ""
const PUSHGATEWAY_URL = (process.env.PUSHGATEWAY_URL || "http://localhost:9391").replace(/\/$/, "")
const METRICS_STATE_DIR = join(process.env.HOME || "/tmp", ".claude", "metrics-state")

// ── SessionStart: temp/ cleanup ───────────────────────────────────────────────
function cleanOld(dir, maxAgeMs, skipSubdir) {
  let entries
  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const entry of entries) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (skipSubdir && entry.name === skipSubdir) continue
      cleanOld(path, maxAgeMs, skipSubdir)
      try {
        if (readdirSync(path).length === 0) rmdirSync(path)
      } catch {
        /* not empty or gone already */
      }
    } else {
      try {
        if (Date.now() - statSync(path).mtimeMs > maxAgeMs) unlinkSync(path)
      } catch {
        /* best-effort */
      }
    }
  }
}

// The kit's own folder. The plugin loads in every project: what it cleans and runs is the kit's,
// never the folder of the session.
export const KIT_ROOT = resolve(realpathSync(import.meta.dir), "..", "..")

function onSessionCreated(kitRoot, directory, snapshot) {
  try {
    const tempDir = join(kitRoot, "temp")
    cleanOld(tempDir, 7 * DAY_MS, "logs")
    cleanOld(join(tempDir, "logs"), 14 * DAY_MS)
  } catch {
    /* must never break session startup */
  }
  refreshMemoryBrief(process.env, kitRoot)
  // the session's repository, copied outside it before the agent touches anything
  snapshot(directory, "session-start", kitRoot)
}

// The memory brief OpenCode reads from `instructions` (bin/opencode/build-config.sh), refreshed at
// each session start like Claude Code's session-start.sh. Best-effort: left as it was on failure.
export function refreshMemoryBrief(env = process.env, kitRoot = KIT_ROOT) {
  const configDir = join(env.XDG_CONFIG_HOME || join(env.HOME || "/tmp", ".config"), "opencode")
  const cli = join(kitRoot, "local", "scripts", "memory_index", "memory.py")
  const venvPython = join(kitRoot, ".venv", "bin", "python3")
  if (!existsSync(venvPython) || !existsSync(cli) || !existsSync(configDir)) return false
  try {
    const proc = Bun.spawnSync([venvPython, cli, "brief"], { stdout: "pipe", stderr: "ignore", timeout: 10000, env })
    if (proc.exitCode !== 0) return false
    writeFileSync(join(configDir, "memory-brief.md"), proc.stdout.toString())
    return true
  } catch {
    return false
  }
}

// ── Memory: save if there's a REMEMBER/REMEMBER-SHARED marker ──────────────────
async function saveMemory(scope, text) {
  if (!text) return
  try {
    const resp = await fetch(`${MEMORY_URL}/memory/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-memory-token": MEMORY_TOKEN },
      body: JSON.stringify({ text, scope, category: "other" }),
    })
    if (!resp.ok) console.error(`session-lifecycle: memory_service returned ${resp.status} (scope=${scope})`)
  } catch (e) {
    console.error(`session-lifecycle: memory_service unreachable at ${MEMORY_URL} — ${e.message}`)
  }
}

function onMemoryMark(text) {
  const shared = /^REMEMBER-SHARED: (.+)$/m.exec(text)
  const personal = /^REMEMBER: (.+)$/m.exec(text)
  if (shared) saveMemory("shared", shared[1].trim())
  if (personal) saveMemory("user", personal[1].trim())
}

// ── Metrics: local counter + push to the Pushgateway ────────────────────────────────
function bumpCounter(name) {
  mkdirSync(METRICS_STATE_DIR, { recursive: true })
  const path = join(METRICS_STATE_DIR, name)
  let value = 1
  try {
    const raw = readFileSync(path, "utf8").trim()
    if (/^\d+$/.test(raw)) value = Number(raw) + 1
  } catch {
    /* first write */
  }
  try {
    writeFileSync(path, String(value))
  } catch {
    /* best-effort */
  }
  return value
}

async function pushMetric(job, grouping, gauges) {
  const segments = [`job/${encodeURIComponent(job)}`]
  for (const [key, value] of Object.entries(grouping)) {
    segments.push(`${key}/${encodeURIComponent(String(value).replace(/\//g, "_") || "unknown")}`)
  }
  const body = Object.entries(gauges)
    .map(([name, value]) => `${name} ${value}\n`)
    .join("")
  const url = `${PUSHGATEWAY_URL}/metrics/${segments.join("/")}`
  try {
    await fetch(url, { method: "PUT", body, signal: AbortSignal.timeout(2000) })
  } catch {
    /* best-effort — a downed Pushgateway must never affect the session */
  }
}

async function onMetrics(agent) {
  try {
    const host = hostname()
    const user = process.env.PAK_INVOKED_BY || process.env.USER || "unknown"
    const now = Date.now() / 1000
    const total = bumpCounter("opencode-turns.count")
    await pushMetric(
      "opencode",
      { host, invoked_by: user },
      { opencode_turns_total: total, opencode_last_run_timestamp_seconds: now }
    )
    const perAgent = bumpCounter(`opencode-turns-${agent}.count`)
    await pushMetric("opencode_agent", { host, invoked_by: user, agent }, { opencode_agent_turns_total: perAgent })
  } catch {
    /* best-effort */
  }
}

// ── TTS: reuses the real .claude/hooks/tts_speak_worker.py pipeline ──────────────
function speakAsync(directory, event, text) {
  if (!text) return
  const worker = join(directory, ".claude", "hooks", "tts_speak_worker.py")
  const venvPython = join(directory, ".venv", "bin", "python3")
  const python = existsSync(venvPython) ? venvPython : "python3"
  if (!existsSync(worker)) return
  try {
    const proc = Bun.spawn([python, worker], {
      stdin: "pipe",
      stdout: "ignore",
      stderr: "ignore",
      cwd: directory,
      detached: true,
    })
    proc.stdin.write(JSON.stringify({ event, text }))
    proc.stdin.flush()
    proc.stdin.end()
    proc.unref() // fire-and-forget — never blocks the OpenCode session
  } catch {
    /* best-effort: broken TTS must never affect the session */
  }
}

function permissionSentence(properties) {
  const kind = properties?.permission || "an action"
  const path = properties?.metadata?.filepath || (properties?.patterns || []).join(", ")
  return path ? `OpenCode is requesting permission: ${kind} — ${path}` : `OpenCode is requesting permission: ${kind}`
}

export const SessionLifecycle = async ({
  client,
  directory,
  kitRoot = KIT_ROOT,
  snapshot = snapshotInBackground,
}) => {
  if (process.env.OPENCODE_HOOKS_ENABLED === "false") {
    return {}
  }
  return {
    event: async ({ event }) => {
      _trace(`event received: ${event.type}`)
      if (event.type === "session.created") {
        onSessionCreated(kitRoot, directory, snapshot)
        return
      }

      if (event.type === "permission.asked") {
        speakAsync(directory, "Notification", permissionSentence(event.properties))
        return
      }

      if (event.type !== "session.idle") return
      const sessionID = event.properties?.sessionID
      if (!sessionID) return
      try {
        _trace(`session.idle: requesting messages for ${sessionID}`)
        const response = await client.session.messages({ path: { id: sessionID } })
        const messages = response?.data
        if (!Array.isArray(messages)) {
          _trace(`session.idle: unexpected response shape ${JSON.stringify(response)}`)
          return
        }
        _trace(`session.idle: got ${messages.length} messages`)
        const lastAssistant = [...messages].reverse().find((m) => m.info?.role === "assistant")
        if (!lastAssistant) {
          _trace("session.idle: no assistant message found, aborting")
          return
        }
        const text = (lastAssistant.parts || [])
          .filter((p) => p.type === "text")
          .map((p) => p.text)
          .join("")
        const agent = lastAssistant.info?.agent || "direct"
        _trace(`session.idle: text=${text.length} chars, agent=${agent}`)

        onMemoryMark(text)
        _trace("session.idle: onMemoryMark called")
        await onMetrics(agent)
        _trace("session.idle: onMetrics finished")
        speakAsync(directory, "Stop", text)
        _trace("session.idle: speakAsync called, DONE")
      } catch (e) {
        _trace(`session.idle: EXCEPTION ${e instanceof Error ? e.stack : String(e)}`)
      }
    },
  }
}

// ── OpenCode 2 (V2 plugin API) ───────────────────────────────────────────────────────────────
// The loader reads ONLY `export default { id, setup }`. Same implementation, fed from the V2
// primitives:
//   - the V1 "event" hook → `ctx.event.subscribe` (one async iterable). V2 events carry `data`
//     where V1 had `properties`, and `permission.asked` renamed its fields (`action`/`resources`
//     instead of `permission`/`patterns`): v2Event() restores the V1 shape the handler reads.
//   - the V1 `client.session.messages({ path: { id } })` → `ctx.session.context({ sessionID })`,
//     which returns V2 messages (`type: "assistant"`, `agent`, `content: [{ type: "text", text }]`):
//     v2Client() reshapes them to the V1 `{ data: [{ info: { role, agent }, parts }] }`.
export function v2Event(event) {
  const data = event?.data ?? {}
  if (event?.type === "permission.asked") {
    return { type: event.type, properties: { ...data, permission: data.action, patterns: data.resources ?? [] } }
  }
  return { type: event?.type, properties: data }
}

export function v2Client(ctx) {
  return {
    session: {
      messages: async ({ path: { id } }) => {
        const messages = await ctx.session.context({ sessionID: id })
        const data = []
        for (const m of Array.isArray(messages) ? messages : []) {
          if (m?.type === "assistant") {
            data.push({
              info: { role: "assistant", agent: m.agent },
              parts: (m.content ?? []).filter((c) => c?.type === "text").map((c) => ({ type: "text", text: c.text ?? "" })),
            })
          } else if (m?.type === "user") {
            data.push({ info: { role: "user" }, parts: [{ type: "text", text: m.text ?? "" }] })
          }
        }
        return { data }
      },
    },
  }
}

export default {
  id: "pak.session-lifecycle",
  async setup(ctx) {
    const onEvent = (await SessionLifecycle({ client: v2Client(ctx), directory: ctx.location?.directory }))["event"]
    if (!onEvent) return
    const controller = new AbortController()
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          try {
            await onEvent({ event: v2Event(event) })
          } catch {
            // best-effort: never breaks the stream
          }
        }
      } catch {
        // stream closed (unload/abort): nothing to do
      }
    })()
    return () => controller.abort()
  },
}
