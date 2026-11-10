// .opencode/plugins/auto-guard.js — the shared guard rules (bin/auto_guard.py, Stage 1) before every
// shell command. Same rules as Claude Code's hook (local/hooks/auto-guard.py): one source of truth,
// BLOCK_RULES. OpenCode has no confirmation dialog, so a challenge blocks and prints the command the
// human types to approve that exact action. A guard that cannot judge blocks too: it never lets a
// command through.
// What to do with each result: protocols/decision-protocol.md §"How to use the guard".
//
// ON by default; OPENCODE_HOOKS_ENABLED=false turns it off.
import { existsSync, realpathSync } from "fs"
import { join, resolve } from "path"

// Stage 1 is pure regex: the real cost is starting Python (50-150 ms).
const GUARD_TIMEOUT_MS = 5000

// The guard lives next to this file, never in the session's directory: a repo the agent works in
// could ship its own bin/auto_guard.py that allows everything.
export function guardRoot() {
  return resolve(realpathSync(import.meta.dir), "..", "..")
}

// Absolute: the plugin loads in every project, and another repo has no protocols/ of its own.
const WHERE = `(${join(guardRoot(), "protocols", "decision-protocol.md")} §How to use the guard)`

function makeCliRunner(repoRoot) {
  const cli = join(repoRoot, "bin", "auto_guard.py")
  const venvPython = join(repoRoot, ".venv", "bin", "python3")
  return (command) => {
    const python = existsSync(venvPython) ? venvPython : Bun.which("python3")
    if (!python || !existsSync(cli)) return null
    // stdin, not argv: argv has a size limit, and a padded command must not fall out of the guard
    const proc = Bun.spawnSync([python, cli, "--stdin", "--stage1-only", "--json", "--engine", "opencode"], {
      stdin: Buffer.from(command),
      stdout: "pipe",
      stderr: "ignore",
      timeout: GUARD_TIMEOUT_MS,
      env: { ...process.env },
    })
    try {
      return JSON.parse(proc.stdout.toString())
    } catch {
      return null
    }
  }
}

function guardMessage(resp) {
  if (resp.action === "challenge") {
    return (
      `REQUIRES HUMAN APPROVAL (auto-guard [${resp.rule}]): ${resp.description}. ` +
      `Ask the human to run it, or to approve it in a terminal with \`${resp.approve?.cmd}\`, and then ` +
      `retry the exact same command. Do NOT rephrase or split it to get past the guard. ${WHERE}`
    )
  }
  return `BLOCKED (auto-guard [${resp.rule}]): ${resp.description}. ${resp.instruction} ${WHERE}`
}

// A challenge may be approved: the session's repository is copied first, outside it
// (bin/snapshot.py), so what the approved command destroys comes back. In the background: the
// guard's answer never waits for the copy.
export function snapshotInBackground(directory, reason, root = guardRoot(), spawn = Bun.spawn) {
  const script = join(root, "bin", "snapshot.py")
  const python = Bun.which("python3")
  if (!directory || !python || !existsSync(script)) return false
  try {
    spawn([python, script, "take", directory, "--reason", reason], {
      stdin: "ignore",
      stdout: "ignore",
      stderr: "ignore",
    })?.unref?.()
    return true
  } catch {
    return false
  }
}

export const AutoGuard = async ({ runGuard, directory, snapshot = snapshotInBackground } = {}) => {
  if (process.env.OPENCODE_HOOKS_ENABLED === "false") {
    return {}
  }
  const check = runGuard ?? makeCliRunner(guardRoot())
  return {
    "tool.execute.before": async (input, output) => {
      if (input?.tool !== "bash") return
      const command = output?.args?.command
      if (!command) return
      const resp = check(command)
      if (resp === null) {
        throw new Error(
          "BLOCKED (auto-guard): the guard could not judge this command, so it does not run. " +
            `Fix the guard, or ask the human: python3 bin/auto_guard.py --status ${WHERE}`,
        )
      }
      if (resp.allowed === false) {
        if (resp.action === "challenge") snapshot(directory, `challenge:${resp.rule}`)
        throw new Error(guardMessage(resp))
      }
    },
  }
}

// OpenCode 2 loads ONLY `export default { id, setup }`. V2 → V1: `shell` is the V1 `bash`, and the
// file tools say `path` where V1 said `filePath`. The handler gets a copy, never the live
// `event.input`, and the V2 `path` is authoritative: a `filePath` smuggled into the input never
// shadows the real target.
export default {
  id: "pak.auto-guard",
  async setup(ctx) {
    const before = (await AutoGuard({ directory: ctx.location?.directory }))["tool.execute.before"]
    if (!before) return
    await ctx.tool.hook("execute.before", (event) => {
      const input = event.input && typeof event.input === "object" ? event.input : {}
      return before(
        { tool: event.tool === "shell" ? "bash" : event.tool, sessionID: event.sessionID, callID: event.id },
        { args: "path" in input ? { ...input, filePath: input.path } : input },
      )
    })
  },
}
