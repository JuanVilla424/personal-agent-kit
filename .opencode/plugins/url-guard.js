// .opencode/plugins/url-guard.js — every `webfetch` URL and every `websearch` query go through
// bin/url_guard.py. Same checks as Claude Code's hook (local/hooks/url-guard.py): one source of
// truth. A guard that cannot judge blocks: it never lets a call through.
//
// ON by default; OPENCODE_HOOKS_ENABLED=false turns it off.
import { existsSync, realpathSync } from "fs"
import { join, resolve } from "path"

// The URL check resolves the name, with a 2 s limit of its own.
const GUARD_TIMEOUT_MS = 5000
const WEB_TOOLS = new Set(["webfetch", "websearch"])

function makeCliRunner(repoRoot) {
  const cli = join(repoRoot, "bin", "url_guard.py")
  const venvPython = join(repoRoot, ".venv", "bin", "python3")
  return (tool, args) => {
    const python = existsSync(venvPython) ? venvPython : Bun.which("python3")
    if (!python || !existsSync(cli)) return null
    const proc = Bun.spawnSync([python, cli], {
      stdin: Buffer.from(JSON.stringify({ tool, args })),
      stdout: "pipe",
      stderr: "ignore",
      timeout: GUARD_TIMEOUT_MS,
    })
    try {
      return JSON.parse(proc.stdout.toString())
    } catch {
      return null
    }
  }
}

export const UrlGuard = async ({ runGuard } = {}) => {
  if (process.env.OPENCODE_HOOKS_ENABLED === "false") {
    return {}
  }
  // The guard lives next to this file, never in the session's directory.
  const check = runGuard ?? makeCliRunner(resolve(realpathSync(import.meta.dir), "..", ".."))
  return {
    "tool.execute.before": async (input, output) => {
      if (!WEB_TOOLS.has(input?.tool)) return
      const resp = check(input.tool, output?.args ?? {})
      if (resp === null) throw new Error("BLOCKED (url-guard): the guard could not judge this call")
      if (resp.allowed === false) throw new Error(resp.reason)
    },
  }
}

// OpenCode 2 loads ONLY `export default { id, setup }`. The handler gets a copy of the live input.
export default {
  id: "pak.url-guard",
  async setup(ctx) {
    const before = (await UrlGuard())["tool.execute.before"]
    if (!before) return
    await ctx.tool.hook("execute.before", (event) => {
      const input = event.input && typeof event.input === "object" ? event.input : {}
      return before({ tool: event.tool, sessionID: event.sessionID, callID: event.id }, { args: { ...input } })
    })
  },
}
