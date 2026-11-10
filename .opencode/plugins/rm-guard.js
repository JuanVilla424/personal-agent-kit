// .opencode/plugins/rm-guard.js — port of .claude/hooks/rm-guard.sh to tool.execute.before
// for the "bash" tool. Blocks recursive+forced rm targeting generated/sensitive
// directories (.git, .venv, venv, node_modules, __pycache__, dist, build) when they appear as a
// COMPLETE path segment — never by substring (so ".venv/bin/python3" is never blocked).
//
// ON by default; OPENCODE_HOOKS_ENABLED=false turns it off (same gate as the other guards).

const RM_RF_RE = /\brm[ \t]+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\b|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\b|-r\b[ \t]+-f\b|-f\b[ \t]+-r\b)/
const SENSITIVE_DIR_RE = /(^|[ \t/])(\.git|\.venv|venv|node_modules|__pycache__|dist|build)([ \t/]|$)/

export const RmGuard = async () => {
  if (process.env.OPENCODE_HOOKS_ENABLED === "false") {
    return {}
  }
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return
      const command = output.args?.command
      if (!command) return
      if (RM_RF_RE.test(command) && SENSITIVE_DIR_RE.test(command)) {
        throw new Error(
          "BLOCKED (rm-guard): recursive/forced rm on a generated/sensitive directory — check the path"
        )
      }
    },
  }
}

// OpenCode 2 loads ONLY `export default { id, setup }`. V2 → V1: `shell` is the V1 `bash`, and the
// handler gets a copy, never the live `event.input`.
export default {
  id: "pak.rm-guard",
  async setup(ctx) {
    const before = (await RmGuard())["tool.execute.before"]
    if (!before) return
    await ctx.tool.hook("execute.before", (event) => {
      const input = event.input && typeof event.input === "object" ? event.input : {}
      return before(
        { tool: event.tool === "shell" ? "bash" : event.tool, sessionID: event.sessionID, callID: event.id },
        { args: { ...input } },
      )
    })
  },
}
