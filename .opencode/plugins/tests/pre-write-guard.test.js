// Coverage for .opencode/plugins/pre-write-guard.js — exercised through its real
// exported factory + `tool.execute.before` handler. The real Bun `$` is passed in
// (not mocked) so the syntax-gate checks exercise the actual python3/bash calls.
import { test, expect, beforeEach, afterEach } from "bun:test"
import { $ } from "bun"
import { PreWriteGuard } from "../pre-write-guard.js"

// Built by concatenation on purpose: a literal contiguous AKIA... string in this
// file would itself trip this repo's own pre-write-guard.sh hook when this test
// file is written or edited (same reason the pytest suite does this).
const FAKE_AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"

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
  expect(Object.keys(await PreWriteGuard({ $ }))).toEqual(["tool.execute.before"])
  process.env.OPENCODE_HOOKS_ENABLED = "false"
  expect(await PreWriteGuard({ $ })).toEqual({})
})

test("the guard's own settings and approvals are never written", async () => {
  const before = (await PreWriteGuard({ $ }))["tool.execute.before"]
  for (const filePath of ["/kit/configs/auto-guard.json", "/kit/logs/auto_guard_approvals.json"]) {
    await expect(before({ tool: "write" }, { args: { filePath, content: "{}" } })).rejects.toThrow(
      /guard's settings and approvals are the human's/,
    )
  }
})

test("the patch tool's files are checked like a write", async () => {
  const before = (await PreWriteGuard({ $ }))["tool.execute.before"]
  const patch = (path, body = "+x") => `*** Begin Patch\n*** Update File: ${path}\n${body}\n*** End Patch`
  await expect(before({ tool: "patch" }, { args: { patchText: patch("app/.env") } })).rejects.toThrow(
    /credential\/secret files/,
  )
  await expect(before({ tool: "patch" }, { args: { patchText: patch("src/a.py", "+" + FAKE_AWS_KEY) } })).rejects.toThrow(
    /hardcoded secret/,
  )
  await expect(before({ tool: "patch" }, { args: { patchText: patch("src/a.py") } })).resolves.toBeUndefined()
  await expect(before({ tool: "patch" }, { args: { patchText: "no file header" } })).resolves.toBeUndefined()
})

test("blocks writing a .env file", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before({ tool: "write" }, { args: { filePath: "/repo/.env", content: "SECRET=1" } })
  ).rejects.toThrow(/BLOCKED/)
})

test("allows writing a .env.template file", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/.env.template", content: "SECRET=<placeholder>" } }
    )
  ).resolves.toBeUndefined()
})

test("blocks a versioned filename", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/deploy-v2.sh", content: "#!/usr/bin/env bash\ntrue\n" } }
    )
  ).rejects.toThrow(/versioned/)
})

test("blocks a hardcoded AWS key in the content", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/config.py", content: `KEY = '${FAKE_AWS_KEY}'` } }
    )
  ).rejects.toThrow(/hardcoded secret/)
})

test("allows clean python content", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/config.py", content: "import os\nX = os.getenv('X')\n" } }
    )
  ).resolves.toBeUndefined()
})

test("blocks invalid python syntax on write", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/broken.py", content: "def f(:\n    pass\n" } }
    )
  ).rejects.toThrow(/syntax/)
})

test("allows valid bash syntax on write", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/deploy.sh", content: "#!/usr/bin/env bash\nset -euo pipefail\ntrue\n" } }
    )
  ).resolves.toBeUndefined()
})

test("blocks invalid bash syntax on write", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "write" },
      { args: { filePath: "/repo/broken.sh", content: "if [ 1 -eq 1 ]; then\n" } }
    )
  ).rejects.toThrow(/syntax/)
})

test("edit checks newString for hardcoded secrets too", async () => {
  const plugin = await PreWriteGuard({ $ })
  const before = plugin["tool.execute.before"]
  await expect(
    before(
      { tool: "edit" },
      { args: { filePath: "/repo/config.py", newString: `KEY = '${FAKE_AWS_KEY}'` } }
    )
  ).rejects.toThrow(/hardcoded secret/)
})
