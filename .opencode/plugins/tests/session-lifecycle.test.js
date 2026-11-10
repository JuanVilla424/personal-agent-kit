// Coverage for .opencode/plugins/session-lifecycle.js.
//
// The single most valuable test here is the "session.idle" regression lock: this
// plugin's whole memory/metrics/TTS chain was broken for a while because
// `client.session.messages(sessionID)` (a bare string, matching the OpenCode SDK's
// own public docs/examples) fails every time against the `client` object actually
// injected into a plugin — the real, working call is
// `client.session.messages({ path: { id: sessionID } })`, and the response comes
// back as `{ data: [...] }`, not a bare array. That fix must never silently regress.
import { test, expect, mock, beforeAll, afterAll, beforeEach, afterEach } from "bun:test"
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"

let SessionLifecycle
let fakeHome
const ORIGINAL_HOME = process.env.HOME
const ORIGINAL_HOOKS = process.env.OPENCODE_HOOKS_ENABLED

beforeAll(async () => {
  // METRICS_STATE_DIR is computed once at module import time from $HOME — point it
  // at an isolated tmp dir BEFORE importing, so tests never touch the real
  // ~/.claude/metrics-state/.
  fakeHome = mkdtempSync(join(tmpdir(), "session-lifecycle-home-"))
  process.env.HOME = fakeHome
  ;({ SessionLifecycle } = await import("../session-lifecycle.js"))
})

afterAll(() => {
  if (ORIGINAL_HOME === undefined) delete process.env.HOME
  else process.env.HOME = ORIGINAL_HOME
  rmSync(fakeHome, { recursive: true, force: true })
})

let fakeDirectory
let fetchMock

beforeEach(() => {
  process.env.OPENCODE_HOOKS_ENABLED = "true"
  // No temp/ and no .claude/hooks/tts_speak_worker.py under here, so
  // onSessionCreated's cleanup and speakAsync's worker lookup both safely no-op —
  // no need to separately mock Bun.spawn.
  fakeDirectory = mkdtempSync(join(tmpdir(), "session-lifecycle-dir-"))
  fetchMock = mock(async () => new Response("{}", { status: 200 }))
  global.fetch = fetchMock
})

afterEach(() => {
  if (ORIGINAL_HOOKS === undefined) delete process.env.OPENCODE_HOOKS_ENABLED
  else process.env.OPENCODE_HOOKS_ENABLED = ORIGINAL_HOOKS
  rmSync(fakeDirectory, { recursive: true, force: true })
})

function assistantMessage(text, agent = "bmad-master") {
  return { data: [{ info: { role: "assistant", agent }, parts: [{ type: "text", text }] }] }
}

test("is on by default and off only with OPENCODE_HOOKS_ENABLED=false", async () => {
  delete process.env.OPENCODE_HOOKS_ENABLED
  expect(Object.keys(await SessionLifecycle({ client: {}, directory: fakeDirectory, kitRoot: fakeDirectory }))).toEqual(["event"])
  process.env.OPENCODE_HOOKS_ENABLED = "false"
  expect(await SessionLifecycle({ client: {}, directory: fakeDirectory, kitRoot: fakeDirectory })).toEqual({})
})

test("session.idle calls client.session.messages with {path:{id}}, not a bare string", async () => {
  const messages = mock(async () => assistantMessage("hola"))
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses_test123" } } })
  expect(messages).toHaveBeenCalledTimes(1)
  expect(messages).toHaveBeenCalledWith({ path: { id: "ses_test123" } })
})

test("session.idle unwraps the {data:[...]} response shape and saves a REMEMBER mark", async () => {
  const messages = mock(async () =>
    assistantMessage("Done.\nREMEMBER: session-lifecycle test data")
  )
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses_test123" } } })

  const memoryCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/memory/add"))
  expect(memoryCall).toBeDefined()
  const body = JSON.parse(memoryCall[1].body)
  expect(body.text).toBe("session-lifecycle test data")
  expect(body.scope).toBe("user")
})

test("session.idle does nothing harmful if messages() ever returns a bare array again", async () => {
  // Locks the OLD, wrong shape as a documented non-crash, not a supported input:
  // if a future SDK change makes messages() resolve to a bare array instead of
  // {data:[...]}, this must stay a silent no-op, never a thrown/unhandled error.
  const messages = mock(async () => [{ info: { role: "assistant" }, parts: [{ type: "text", text: "x" }] }])
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses_test123" } } })
  expect(fetchMock).not.toHaveBeenCalled()
})

test("session.idle with no assistant message present does not call fetch", async () => {
  const messages = mock(async () => ({ data: [{ info: { role: "user" }, parts: [] }] }))
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses_test123" } } })
  expect(fetchMock).not.toHaveBeenCalled()
})

test("session.idle without a sessionID never calls client.session.messages", async () => {
  const messages = mock(async () => assistantMessage("x"))
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({ event: { type: "session.idle", properties: {} } })
  expect(messages).not.toHaveBeenCalled()
})

test("session.created does not touch client.session.messages", async () => {
  const messages = mock(async () => assistantMessage("x"))
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({ event: { type: "session.created", properties: {} } })
  expect(messages).not.toHaveBeenCalled()
})

test("permission.asked does not touch client.session.messages", async () => {
  const messages = mock(async () => assistantMessage("x"))
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await plugin.event({
    event: { type: "permission.asked", properties: { permission: "bash", patterns: ["rm -rf /"] } },
  })
  expect(messages).not.toHaveBeenCalled()
})

test("session.idle exceptions from client.session.messages are swallowed, never thrown", async () => {
  const messages = mock(async () => {
    throw new Error("network exploded")
  })
  const plugin = await SessionLifecycle({ client: { session: { messages } }, directory: fakeDirectory, kitRoot: fakeDirectory })
  await expect(
    plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses_test123" } } })
  ).resolves.toBeUndefined()
})

test("session.created cleans the kit's own temp/, never the temp/ of the session's project", async () => {
  const kit = mkdtempSync(join(tmpdir(), "session-lifecycle-kit-"))
  const project = mkdtempSync(join(tmpdir(), "session-lifecycle-project-"))
  const old = Date.now() / 1000 - 30 * 24 * 3600
  for (const root of [kit, project]) {
    mkdirSync(join(root, "temp"))
    writeFileSync(join(root, "temp", "old.txt"), "x")
    utimesSync(join(root, "temp", "old.txt"), old, old)
  }
  try {
    const plugin = await SessionLifecycle({ client: {}, directory: project, kitRoot: kit })
    await plugin.event({ event: { type: "session.created", properties: {} } })
    expect(existsSync(join(kit, "temp", "old.txt"))).toBe(false)
    expect(existsSync(join(project, "temp", "old.txt"))).toBe(true)
  } finally {
    rmSync(kit, { recursive: true, force: true })
    rmSync(project, { recursive: true, force: true })
  }
})

test("refreshMemoryBrief writes what memory.py brief prints into OpenCode's config dir", async () => {
  const { refreshMemoryBrief } = await import("../session-lifecycle.js")
  const kit = mkdtempSync(join(tmpdir(), "session-lifecycle-brief-"))
  const config = join(kit, "xdg")
  mkdirSync(join(config, "opencode"), { recursive: true })
  mkdirSync(join(kit, ".venv", "bin"), { recursive: true })
  mkdirSync(join(kit, "local", "scripts", "memory_index"), { recursive: true })
  writeFileSync(join(kit, "local", "scripts", "memory_index", "memory.py"), "")
  writeFileSync(join(kit, ".venv", "bin", "python3"), "#!/bin/sh\necho '# What you remember'\n")
  chmodSync(join(kit, ".venv", "bin", "python3"), 0o755)
  try {
    expect(refreshMemoryBrief({ ...process.env, XDG_CONFIG_HOME: config }, kit)).toBe(true)
    expect(readFileSync(join(config, "opencode", "memory-brief.md"), "utf8")).toBe("# What you remember\n")
    // no config dir yet, or no kit venv: nothing is written
    expect(refreshMemoryBrief({ ...process.env, XDG_CONFIG_HOME: join(kit, "none") }, kit)).toBe(false)
    expect(refreshMemoryBrief({ ...process.env, XDG_CONFIG_HOME: config }, join(kit, "nowhere"))).toBe(false)
  } finally {
    rmSync(kit, { recursive: true, force: true })
  }
})

test("session.created snapshots the session's repository, with the kit's own snapshot.py", async () => {
  const calls = []
  const plugin = await SessionLifecycle({
    client: { session: { messages: async () => [] } },
    directory: "/work/app",
    kitRoot: fakeDirectory,
    snapshot: (dir, why, root) => calls.push([dir, why, root]),
  })
  await plugin.event({ event: { type: "session.created", properties: {} } })
  expect(calls).toEqual([["/work/app", "session-start", fakeDirectory]])
})
