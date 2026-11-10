// Coverage for .opencode/plugins/url-guard.js: the factory with an injected runner, and the URL
// corpus (evals/datasets/url-guard-corpus.jsonl) through the plugin's V2 hook and the real
// bin/url_guard.py. Allowed fetches resolve their name for real, so they stay in the Python suite.
import { test, expect, beforeEach, afterEach } from "bun:test"
import { readFileSync } from "fs"
import { join } from "path"
import { UrlGuard } from "../url-guard.js"

const REPO = join(import.meta.dir, "..", "..", "..")
const CORPUS = readFileSync(join(REPO, "evals", "datasets", "url-guard-corpus.jsonl"), "utf8")
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line))
  .filter((c) => !(c.expect === "allow" && c.tool === "webfetch"))

const ORIGINAL = process.env.OPENCODE_HOOKS_ENABLED
beforeEach(() => {
  delete process.env.OPENCODE_HOOKS_ENABLED
})
afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.OPENCODE_HOOKS_ENABLED
  else process.env.OPENCODE_HOOKS_ENABLED = ORIGINAL
})

test("is on by default and off only with OPENCODE_HOOKS_ENABLED=false", async () => {
  expect(Object.keys(await UrlGuard({ runGuard: () => ({ allowed: true }) }))).toEqual(["tool.execute.before"])
  process.env.OPENCODE_HOOKS_ENABLED = "false"
  expect(await UrlGuard()).toEqual({})
})

test("only the web tools are judged, and a guard that cannot judge blocks", async () => {
  const calls = []
  const before = (await UrlGuard({ runGuard: (tool, args) => (calls.push([tool, args]), null) }))["tool.execute.before"]
  await expect(before({ tool: "bash" }, { args: { command: "curl x" } })).resolves.toBeUndefined()
  await expect(before({ tool: "webfetch" }, { args: { url: "https://a.b/" } })).rejects.toThrow(
    /url-guard\): the guard could not judge/,
  )
  expect(calls).toEqual([["webfetch", { url: "https://a.b/" }]])
})

test.skipIf(!Bun.which("python3"))("the URL corpus gets its verdicts through the plugin's V2 hook", async () => {
  let hook
  await (await import("../url-guard.js")).default.setup({ tool: { hook: async (_name, fn) => (hook = fn) } })
  const wrong = []
  for (const c of CORPUS) {
    const value = c.parts ? c.parts.join("") : c.value
    const input = c.tool === "webfetch" ? { url: value } : { query: value }
    let outcome = "allow"
    try {
      await hook({ tool: c.tool, sessionID: "ses_url", id: "call_url", input })
    } catch (e) {
      outcome = e.message.includes(c.why ?? "\u0000") ? "block" : `error: ${e.message}`
    }
    if (outcome !== c.expect) wrong.push(`${c.id}: expected ${c.expect}, got ${outcome}`)
  }
  expect(wrong).toEqual([])
}, 120000)
