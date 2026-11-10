// Coverage for .opencode/plugins/rm-guard.js — exercised through its real exported
// factory + `tool.execute.before` handler (the actual OpenCode calling contract),
// not by re-implementing its internals.
import { test, expect, beforeEach, afterEach } from "bun:test"
import { RmGuard } from "../rm-guard.js"

const ORIGINAL = process.env.OPENCODE_HOOKS_ENABLED

beforeEach(() => {
  process.env.OPENCODE_HOOKS_ENABLED = "true"
})
afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.OPENCODE_HOOKS_ENABLED
  else process.env.OPENCODE_HOOKS_ENABLED = ORIGINAL
})

test("is on by default and off only with OPENCODE_HOOKS_ENABLED=false", async () => {
  delete process.env.OPENCODE_HOOKS_ENABLED
  expect(Object.keys(await RmGuard())).toEqual(["tool.execute.before"])
  process.env.OPENCODE_HOOKS_ENABLED = "false"
  expect(await RmGuard()).toEqual({})
})

test("blocks rm -rf on a sensitive directory", async () => {
  const plugin = await RmGuard()
  const before = plugin["tool.execute.before"]
  await expect(
    before({ tool: "bash" }, { args: { command: "rm -rf .venv" } })
  ).rejects.toThrow(/BLOCKED/)
})

test("blocks rm -rf on node_modules subpath", async () => {
  const plugin = await RmGuard()
  const before = plugin["tool.execute.before"]
  await expect(
    before({ tool: "bash" }, { args: { command: "rm -rf node_modules/some-pkg" } })
  ).rejects.toThrow(/BLOCKED/)
})

test("allows rm -rf on a non-sensitive path", async () => {
  const plugin = await RmGuard()
  const before = plugin["tool.execute.before"]
  await expect(
    before({ tool: "bash" }, { args: { command: "rm -rf /home/user/output" } })
  ).resolves.toBeUndefined()
})

test("allows reading inside .venv (no rm at all)", async () => {
  const plugin = await RmGuard()
  const before = plugin["tool.execute.before"]
  await expect(
    before({ tool: "bash" }, { args: { command: "cat .venv/bin/activate" } })
  ).resolves.toBeUndefined()
})

test("ignores non-bash tools entirely", async () => {
  const plugin = await RmGuard()
  const before = plugin["tool.execute.before"]
  await expect(
    before({ tool: "write" }, { args: { command: "rm -rf .venv" } })
  ).resolves.toBeUndefined()
})
