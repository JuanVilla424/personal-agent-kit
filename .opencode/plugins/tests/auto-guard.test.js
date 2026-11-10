// Coverage for .opencode/plugins/auto-guard.js — its factory and handler with an injected runner.
// The real CLI is exercised by guard-corpus.test.js, which runs every corpus case through the
// plugin's V2 hook and bin/auto_guard.py.
import { test, expect, beforeEach, afterEach } from "bun:test"
import { join, resolve } from "path"
import { AutoGuard, guardRoot, snapshotInBackground } from "../auto-guard.js"

const ORIGINAL = process.env.OPENCODE_HOOKS_ENABLED
beforeEach(() => {
  delete process.env.OPENCODE_HOOKS_ENABLED
})
afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.OPENCODE_HOOKS_ENABLED
  else process.env.OPENCODE_HOOKS_ENABLED = ORIGINAL
})

const responses = {
  "git push --force origin dev": {
    allowed: false,
    action: "block",
    rule: "force_push",
    description: "Force push rewrites shared history",
    instruction: "Agents never run this action.",
  },
  "git push origin --delete feature-x": {
    allowed: false,
    action: "challenge",
    rule: "delete_shared",
    description: "Deleting a shared remote branch",
    instruction: "Ask the human first.",
    approve: { cmd: "python3 /kit/bin/auto_guard.py approve 0123456789abcdef" },
  },
}
const fakeRunner = (command) => responses[command] ?? { allowed: true }

async function handler(runGuard = fakeRunner) {
  return (await AutoGuard({ runGuard }))["tool.execute.before"]
}

test("is on by default and off only with OPENCODE_HOOKS_ENABLED=false", async () => {
  expect(Object.keys(await AutoGuard({ runGuard: fakeRunner }))).toEqual(["tool.execute.before"])
  process.env.OPENCODE_HOOKS_ENABLED = "false"
  expect(await AutoGuard({ runGuard: fakeRunner })).toEqual({})
})

test("a block names its rule and where it is explained", async () => {
  const run = await handler()
  await expect(run({ tool: "bash" }, { args: { command: "git push --force origin dev" } })).rejects.toThrow(
    /BLOCKED \(auto-guard \[force_push\]\).*\/protocols\/decision-protocol\.md §How to use the guard/,
  )
})

test("a challenge blocks and gives the human the exact approve command", async () => {
  const run = await handler()
  await expect(run({ tool: "bash" }, { args: { command: "git push origin --delete feature-x" } })).rejects.toThrow(
    /REQUIRES HUMAN APPROVAL \(auto-guard \[delete_shared\]\).*python3 \/kit\/bin\/auto_guard\.py approve 0123456789abcdef/,
  )
})

test("harmless commands and other tools pass", async () => {
  const run = await handler()
  await expect(run({ tool: "bash" }, { args: { command: "git status" } })).resolves.toBeUndefined()
  await expect(run({ tool: "bash" }, { args: {} })).resolves.toBeUndefined()
  await expect(run({ tool: "edit" }, { args: { filePath: "x" } })).resolves.toBeUndefined()
})

test("a guard that cannot judge blocks the command", async () => {
  const run = await handler(() => null)
  await expect(run({ tool: "bash" }, { args: { command: "git status" } })).rejects.toThrow(
    /the guard could not judge this command/,
  )
})

test("the guard is the one next to this plugin, never the session directory's", () => {
  expect(guardRoot()).toBe(resolve(join(import.meta.dir, "..", "..", "..")))
})

test("a challenge snapshots the session's repository first; a block does not", async () => {
  const calls = []
  const before = (
    await AutoGuard({ runGuard: fakeRunner, directory: "/work/app", snapshot: (dir, why) => calls.push([dir, why]) })
  )["tool.execute.before"]
  await expect(before({ tool: "bash" }, { args: { command: "git push origin --delete feature-x" } })).rejects.toThrow(
    "REQUIRES HUMAN APPROVAL",
  )
  await expect(before({ tool: "bash" }, { args: { command: "git push --force origin dev" } })).rejects.toThrow("BLOCKED")
  expect(calls).toEqual([["/work/app", "challenge:delete_shared"]])
})

test("snapshotInBackground runs bin/snapshot.py take on the directory, and nothing without one", () => {
  const spawned = []
  const spawn = (argv) => spawned.push(argv)
  expect(snapshotInBackground("/work/app", "session-start", guardRoot(), spawn)).toBe(true)
  expect(spawned[0].slice(1)).toEqual([join(guardRoot(), "bin", "snapshot.py"), "take", "/work/app", "--reason", "session-start"])
  expect(snapshotInBackground(undefined, "session-start", guardRoot(), spawn)).toBe(false)
  expect(snapshotInBackground("/work/app", "x", "/no/kit/here", spawn)).toBe(false)
  expect(spawned.length).toBe(1)
})
