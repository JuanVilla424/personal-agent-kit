// OpenCode 2 loads ONLY `export default { id, setup }` ("Plugin must export a default definition
// with an id and an effect or setup function"): a plugin with only the V1 factory never runs, and
// that is how the kit's guards were inert until this test existed. Each plugin's V2 definition is
// exercised here through a fake V2 context, with the 2.x event shapes: the tool is `shell` (not
// `bash`) and the file tools carry `path` (not `filePath`).
import { test, expect, beforeEach, afterEach, afterAll, mock } from "bun:test"
import { mkdtempSync, readdirSync, rmSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"

const PLUGINS = readdirSync(join(import.meta.dir, ".."))
  .filter((name) => name.endsWith(".js"))
  .map((name) => name.slice(0, -3))
  .sort()

const EXPECTED = {
  "auto-guard": { tool: ["execute.before"] },
  "pre-write-guard": { tool: ["execute.before"] },
  "rm-guard": { tool: ["execute.before"] },
  "session-lifecycle": { subscriptions: 1 },
  "url-guard": { tool: ["execute.before"] },
}

const ORIGINAL = process.env.OPENCODE_HOOKS_ENABLED
const sandbox = mkdtempSync(join(tmpdir(), "v2-definitions-"))
beforeEach(() => {
  delete process.env.OPENCODE_HOOKS_ENABLED
})
afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.OPENCODE_HOOKS_ENABLED
  else process.env.OPENCODE_HOOKS_ENABLED = ORIGINAL
})
afterAll(() => rmSync(sandbox, { recursive: true, force: true }))

// A fake V2 PluginContext: records hook registrations and replays a fixed event stream.
function fakeContext({ events = [], messages = [] } = {}) {
  const registered = { tool: {}, subscriptions: 0 }
  const ctx = {
    location: { directory: sandbox },
    tool: {
      hook: async (name, callback) => {
        registered.tool[name] = callback
        return { dispose: async () => {} }
      },
    },
    session: { context: async () => messages },
    event: {
      subscribe: ({ signal } = {}) => {
        registered.subscriptions += 1
        return {
          async *[Symbol.asyncIterator]() {
            for (const event of events) {
              if (signal?.aborted) return
              yield event
            }
          },
        }
      },
    },
  }
  return { ctx, registered }
}

const before = (tool, input) => ({ tool, sessionID: "ses_test", id: "call_test", input })

async function v2Before(name) {
  const { ctx, registered } = fakeContext()
  await (await import(`../${name}.js`)).default.setup(ctx)
  return registered.tool["execute.before"]
}

test("every plugin default-exports a V2 definition with a stable id", async () => {
  expect(PLUGINS).toEqual(Object.keys(EXPECTED))
  for (const name of PLUGINS) {
    const mod = await import(`../${name}.js`)
    expect(mod.default?.id).toBe(`pak.${name}`)
    expect(typeof mod.default?.setup).toBe("function")
  }
})

test("each plugin registers exactly its V2 hooks, and none with OPENCODE_HOOKS_ENABLED=false", async () => {
  for (const [name, want] of Object.entries(EXPECTED)) {
    const { ctx, registered } = fakeContext()
    const cleanup = await (await import(`../${name}.js`)).default.setup(ctx)
    expect(Object.keys(registered.tool)).toEqual(want.tool ?? [])
    expect(registered.subscriptions).toBe(want.subscriptions ?? 0)
    if (want.subscriptions) {
      expect(typeof cleanup).toBe("function")
      cleanup()
    }
  }
  process.env.OPENCODE_HOOKS_ENABLED = "false"
  for (const name of PLUGINS) {
    const { ctx, registered } = fakeContext()
    expect(await (await import(`../${name}.js`)).default.setup(ctx)).toBeUndefined()
    expect(registered).toEqual({ tool: {}, subscriptions: 0 })
  }
})

test("rm-guard blocks through the V2 hook (2.x `shell` → V1 `bash`)", async () => {
  const hook = await v2Before("rm-guard")
  await expect(hook(before("shell", { command: "rm -rf node_modules" }))).rejects.toThrow(/BLOCKED \(rm-guard\)/)
  await expect(hook(before("read", { path: "/etc/hostname" }))).resolves.toBeUndefined()
})

test("pre-write-guard blocks through the V2 hook, and the V2 path is authoritative", async () => {
  const hook = await v2Before("pre-write-guard")
  await expect(hook(before("write", { path: join(sandbox, ".env"), content: "A=1\n" }))).rejects.toThrow(
    /BLOCKED \(pre-write-guard\)/,
  )
  // a benign `filePath` riding along never shadows the real target
  await expect(
    hook(before("write", { path: join(sandbox, ".env"), filePath: join(sandbox, "ok.py"), content: "A=1\n" })),
  ).rejects.toThrow(/BLOCKED \(pre-write-guard\)/)
  const input = { path: join(sandbox, "ok.py"), content: "print('hi')\n" }
  await expect(hook(before("write", input))).resolves.toBeUndefined()
  expect(Object.keys(input).sort()).toEqual(["content", "path"]) // the live input is never mutated
})

test("session-lifecycle: V2 events and messages reach the V1 handler in the V1 shape", async () => {
  const fetchMock = mock(async () => new Response("{}", { status: 200 }))
  const originalFetch = global.fetch
  global.fetch = fetchMock
  try {
    const events = [
      { type: "permission.asked", data: { sessionID: "ses_1", action: "shell", resources: ["ls -la"] } },
      { type: "session.idle", data: { sessionID: "ses_1" } },
    ]
    const messages = [
      { type: "user", text: "hello" },
      { type: "assistant", agent: "dev", content: [{ type: "text", text: "Done.\nREMEMBER: the V2 adapter works" }] },
    ]
    const { ctx } = fakeContext({ events, messages })
    const cleanup = await (await import("../session-lifecycle.js")).default.setup(ctx)
    const memoryCall = () => fetchMock.mock.calls.find(([url]) => String(url).includes("/memory/add"))
    for (let i = 0; i < 200 && !memoryCall(); i++) await Bun.sleep(10)
    expect(JSON.parse(memoryCall()[1].body)).toMatchObject({ scope: "user", text: "the V2 adapter works" })
    cleanup()
  } finally {
    global.fetch = originalFetch
  }
})

test("session-lifecycle: the V2 → V1 reshaping of events", async () => {
  const { v2Event } = await import("../session-lifecycle.js")
  expect(v2Event({ type: "permission.asked", data: { action: "shell", resources: ["x"] } }).properties).toMatchObject({
    permission: "shell",
    patterns: ["x"],
  })
  expect(v2Event({ type: "permission.asked", data: {} }).properties.patterns).toEqual([])
  expect(v2Event(undefined)).toEqual({ type: undefined, properties: {} })
})
