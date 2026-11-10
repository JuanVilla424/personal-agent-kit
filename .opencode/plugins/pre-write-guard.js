// .opencode/plugins/pre-write-guard.js — port of .claude/hooks/pre-write-guard.sh to
// tool.execute.before for OpenCode's "write", "edit" and "patch" tools. Same checks,
// same criteria: secret files, the guard's own settings, versioned filenames, hardcoded
// secrets in the content, and syntax (.sh/.py) before the file touches disk.
//
// ON by default; OPENCODE_HOOKS_ENABLED=false turns it off (same gate as the other guards).

const SECRET_FILE_RE = /\.env(\.[^.]+)?$|\.pem$|\.key$|\.ppk$|\.p12$|\.pfx$|\/secrets\/|\/credentials$/
const SECRET_TEMPLATE_RE = /\.env\.(template|example|sample)$/
// The guard's settings and its approvals: an agent that edits them approves itself.
const GUARD_STATE_RE = /(^|\/)configs\/auto-guard\.json$|(^|\/)auto_guard_(approvals\.json|log\.jsonl)$/
const VERSIONED_NAME_RE = /-v\d+(\.[A-Za-z0-9]+)?$/
const HARDCODED_SECRET_RE =
  /AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|aws_secret_access_key\s*=\s*[A-Za-z0-9/+]{30,}/
// The patch tool names its files inside the patch text.
const PATCH_FILE_RE = /^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$/gm
const WRITE_TOOLS = new Set(["write", "edit", "patch"])

function block(reason) {
  throw new Error(`BLOCKED (pre-write-guard): ${reason}`)
}

function checkPath(filePath) {
  // 1. Never write credential/secret files (templates are allowed).
  if (SECRET_FILE_RE.test(filePath) && !SECRET_TEMPLATE_RE.test(filePath)) {
    block(`credential/secret files are not written: ${filePath} (the value goes into the encrypted .env)`)
  }
  // 1b. Only the human changes what the guard allows.
  if (GUARD_STATE_RE.test(filePath)) {
    block(`the guard's settings and approvals are the human's: ${filePath}`)
  }
  // 2. Versioned filenames — the version belongs in git, not the name.
  if (VERSIONED_NAME_RE.test(filePath)) {
    block(`versioned filename not allowed: ${filePath} (version with git, not -vN)`)
  }
}

export const PreWriteGuard = async ({ $ }) => {
  if (process.env.OPENCODE_HOOKS_ENABLED === "false") {
    return {}
  }
  return {
    "tool.execute.before": async (input, output) => {
      if (!WRITE_TOOLS.has(input.tool)) return
      const patchText = input.tool === "patch" ? String(output.args?.patchText ?? "") : ""
      const paths = patchText
        ? [...patchText.matchAll(PATCH_FILE_RE)].map((m) => m[1].trim())
        : [output.args?.filePath].filter(Boolean)
      if (paths.length === 0) return
      const filePath = paths[0]
      // write carries the full content; edit carries newString (the new fragment).
      const text = patchText || (output.args?.content ?? output.args?.newString ?? "")

      try {
        for (const path of paths) checkPath(path)

        // 3. Hardcoded secrets in the incoming content.
        if (text && HARDCODED_SECRET_RE.test(text)) {
          block("hardcoded secret in the content (AWS key / private key / secret) — use .env")
        }

        // 4. Syntax gate — write only, where we have the full file.
        if (input.tool === "write" && text) {
          if (filePath.endsWith(".py")) {
            try {
              await $`python3 -c ${"import ast,sys; ast.parse(sys.stdin.read())"} < ${new Response(text)}`.quiet()
            } catch {
              block(`python: syntax error in ${filePath}`)
            }
          } else if (filePath.endsWith(".sh")) {
            try {
              await $`bash -n < ${new Response(text)}`.quiet()
            } catch {
              block(`bash: syntax error in ${filePath}`)
            }
          }
        }
      } catch (e) {
        if (e instanceof Error && e.message.startsWith("BLOCKED")) throw e
        // best-effort: an internal guard bug must never block a valid write
      }
    },
  }
}

// OpenCode 2 loads ONLY `export default { id, setup }`. V2 → V1: the file tools say `path` where V1
// said `filePath`. The handler gets a copy, never the live `event.input`, and the V2 `path` is
// authoritative: a `filePath` smuggled into the input never shadows the real target. V2 injects no
// `$`: the syntax gate gets Bun's own shell.
export default {
  id: "pak.pre-write-guard",
  async setup(ctx) {
    const before = (await PreWriteGuard({ $: globalThis.Bun?.$ }))["tool.execute.before"]
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
