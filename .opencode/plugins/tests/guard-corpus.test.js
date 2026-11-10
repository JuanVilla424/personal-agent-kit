// The guard corpus (evals/datasets/guard-corpus.jsonl) through OpenCode's real path: the plugin's
// V2 default export, registered on a fake V2 context, judging `shell` calls with the real
// bin/auto_guard.py. The same corpus runs through Claude Code's hook in bin/tests/test_guard_corpus.py.
// Needs python3 (and the repo's .venv when present), like the plugin itself.
import { test, expect, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, readFileSync, rmSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"

const REPO = join(import.meta.dir, "..", "..", "..")
const CORPUS = readFileSync(join(REPO, "evals", "datasets", "guard-corpus.jsonl"), "utf8")
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line))

const ORIGINAL = { ...process.env }
let sandbox
let hook

beforeAll(async () => {
  // the audit trail and approvals of this run go to a temp dir, never to logs/
  sandbox = mkdtempSync(join(tmpdir(), "guard-corpus-"))
  process.env.AUTO_GUARD_LOG = join(sandbox, "guard.jsonl")
  process.env.AUTO_GUARD_APPROVALS = join(sandbox, "approvals.json")
  delete process.env.OPENCODE_HOOKS_ENABLED
  const ctx = { tool: { hook: async (name, fn) => (hook = name === "execute.before" ? fn : hook) } }
  await (await import("../auto-guard.js")).default.setup(ctx)
})

afterAll(() => {
  for (const key of ["AUTO_GUARD_LOG", "AUTO_GUARD_APPROVALS", "OPENCODE_HOOKS_ENABLED"]) {
    if (ORIGINAL[key] === undefined) delete process.env[key]
    else process.env[key] = ORIGINAL[key]
  }
  rmSync(sandbox, { recursive: true, force: true })
})

const shell = (command) => ({ tool: "shell", sessionID: "ses_corpus", id: "call_corpus", input: { command } })

test.skipIf(!Bun.which("python3"))("every corpus case gets its verdict through the plugin", async () => {
  const wrong = []
  for (const c of CORPUS) {
    let outcome = "allow"
    try {
      await hook(shell(c.command))
    } catch (e) {
      const m = /^(BLOCKED|REQUIRES HUMAN APPROVAL) \(auto-guard \[([a-z_]+)\]\)/.exec(e.message)
      outcome = m ? `${m[1] === "BLOCKED" ? "block" : "challenge"}/${m[2]}` : `error: ${e.message}`
    }
    const expected = c.expect === "allow" ? "allow" : `${c.expect}/${c.rule}`
    if (outcome !== expected) wrong.push(`${c.id}: expected ${expected}, got ${outcome}`)
  }
  expect(wrong).toEqual([])
  expect(CORPUS.filter((c) => c.expect === "block").length).toBeGreaterThanOrEqual(50)
  expect(CORPUS.filter((c) => c.expect === "allow").length).toBeGreaterThanOrEqual(50)
}, 120000)
