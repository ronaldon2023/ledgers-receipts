# T00 research note: Receipts plugin mechanics

Date 2026-10-25. Claude Code 2.1.310 installed. Docs fetched live from `https://code.claude.com/docs/en/<page>.md`. Tags: PRIMARY = opened this session; SECONDARY = someone's summary. "Lead" = the session building the plugin (Anthony's lane), whose install tests are cited as such.
Status: findings as of the date above; docs and Claude Code versions move, so re-check a claim before building on it.
Base rate (outside view): plugin features documented on code.claude.com mostly work as written, but cross-feature edges (hook "ask" in bypass mode, MCP cwd) are where docs are silent.
Protocol: acceptable = official docs (.md mirrors), installed binary strings, the lead's runs, maintainer-authored GitHub comments. Aggregator mirrors are SECONDARY.

Already established by lead (not re-researched): CLAUDE_PLUGIN_ROOT/DATA/PROJECT_DIR; plugin `settings.json` honours only `agent` and `subagentStatusLine`; no `..` in paths; omit `version` to track commits; private-repo auth; `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1`.

## Q1. Cross-marketplace dependency when knowledge-work-plugins is NOT added
**Answer:** No. It is not fetched. Install completes, small-business is skipped with a warning, and `ledgers-receipts` will not load until the user adds `anthropics/knowledge-work-plugins`; adding it afterwards installs the dependency.
**Evidence:**
- Lead's install test, 2026-10-25, Claude Code 2.1.310 (PRIMARY, lead): `claude plugin install ledgers-receipts@the-ledgers` printed `Warning: dependency "small-business@knowledge-work-plugins" was not installed (no marketplace you have added lists it). "ledgers-receipts" will not load without it`. Then `claude plugin marketplace add anthropics/knowledge-work-plugins` printed `(+ 1 dependency: small-business)`; both enabled.
- plugins/install.md: "Claude Code has to know about a marketplace before you can install from it."
- plugins/troubleshooting.md "Dependency errors": "If the dependency's marketplace isn't registered yet, add it and run `/reload-plugins` in your session, which installs the missing dependencies it can resolve."
- Binary 2.1.310 strings (static read, not executed): `Dependency "<dep>" (required by <plugin>) not found. Is the "<marketplace>" marketplace added?` and ` Add the dependency's marketplace, then re-run install.`
- plugins/dependencies.md "Depend on a plugin from another marketplace": allowlist field and, when the allowlist is missing, "When it's declared in `plugin.json`, the install completes without the dependency and your plugin then fails to load." Entry-declared: install refused with `...which is not in the allowlist`.
- Null search: no doc sentence says a cross-marketplace dependency auto-adds the target marketplace. Searched "dependency marketplace not added / not found".
- SMB's own README (kwp copy, small-business/README.md:23-27) tells Claude Code users: `claude plugin marketplace add anthropics/knowledge-work-plugins` then `claude plugin install small-business@knowledge-work-plugins`.
- Gotcha, GitHub anthropics/claude-code#86493 (open; maintainer comment read via `gh`, PRIMARY): "Claude Code resolves dependencies from its locally cached `marketplace.json`"; a stale cache of the DECLARING marketplace gives the same "Is the ... marketplace added?" message and "persists across installs and `/reload-plugins`". Workaround: `claude plugin marketplace update the-ledgers` after editing marketplace.json.
- Install guidance for the README (inference): the one-step form `/plugin install ledgers-receipts --marketplace <owner>/<repo>` (install.md, v2.1.275+) adds only OUR marketplace; users still add knowledge-work-plugins (or install small-business first, which skips the allowlist check per dependencies.md "already enabled").
- `claude plugin validate .` on the lead's worktree passed (PRIMARY, run here): warnings are no `version`, root CLAUDE.md, missing icon.
**Contradiction/refinement of the brief:** the brief's "allowlist + plugin.json" wiring is necessary but not sufficient; the second marketplace must also be registered. The allowlist only gates a dependency whose marketplace is already known.
**Confidence basis:** measured by the lead's run on the exact version; docs and binary agree.

## Q2. Plugin MCP tool name and matcher
**Answer:** `mcp__plugin_<plugin>_<server>__<tool>`; for ours, matcher `mcp__plugin_ledgers-receipts_bakery-local__.*`.
**Evidence:** mcp.md "Plugin MCP tool names": "The full form is `mcp__plugin_<plugin-name>_<server-name>__<tool-name>`, where any character outside `A-Z`, `a-z`, `0-9`, `_`, and `-` is replaced with `_`." hooks.md "Match MCP tools": "A matcher written against the bare server key never fires for these tools." and "`mcp__plugin_my-plugin_db__.*`". The `.*` is required ("a matcher like `mcp__memory` ... matches no tool"). Server registers as `plugin:<plugin>:<server>`. Live tool list in this session shows the same shape (`mcp__plugin_github_github__get_me`).
Also: PreToolUse/PostToolUse input carries `mcp_server` with `source` (`plugin`, `user`, ...), hooks.md "PreToolUse input" (use for trust decisions). A pay tool from SMB is a different server (SMB `.mcp.json` has 35 remote servers, e.g. stripe, paypal, square, ramp, airwallex-agentos; python read of small-business/.mcp.json), so a pay matcher spanning servers needs `mcp__.*__<toolname-pattern>` (hooks.md: `mcp__.*__write.*` form) plus the user's own `mcp__claude_ai_*` copy of the same connector (SMB README: "you may see it listed twice").
**Confidence basis:** documented in three places, consistent.

## Q3. Plugin stdio MCP: cwd, `${CLAUDE_PROJECT_DIR}`, finding bakery.db
**Answer:** The lead's reading is contradicted: `${CLAUDE_PROJECT_DIR}` DOES resolve in plugin stdio `command`/`args`/`env`, and the server also gets `CLAUDE_PROJECT_DIR` in its environment. Working directory is not documented.
**Evidence:**
- mcp.md "Plugin MCP features": "`${CLAUDE_PLUGIN_ROOT}` ..., `${CLAUDE_PLUGIN_DATA}` ..., and `${CLAUDE_PROJECT_DIR}` to the stable project root. Substitution applies to: `stdio` servers: `command`, `args`, `env`".
- mcp.md Option 3: "Claude Code sets `CLAUDE_PROJECT_DIR` in the spawned server's environment ... so your server can resolve project-relative paths without depending on the working directory." and "Plugin-provided MCP configurations substitute `${CLAUDE_PROJECT_DIR}` directly and don't need the default."
- Conflict between pages: plugins/manifest-reference.md "Where each variable resolves" lists MCP stdio "Exported to the process: `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`" (no PROJECT_DIR). plugins/components.md says all three variables "are also exported to hook, MCP, and LSP processes". This is the likely source of the lead's reading. mcp.md (the page about MCP) is more specific.
- cwd: no sentence found for stdio plugin servers (grep "working directory|cwd|spawn" in mcp.md, components.md, manifest-reference.md). Only the headersHelper cwd is specified.
**Recommendation (inference):** server reads `os.environ["CLAUDE_PROJECT_DIR"]` first, falls back to `ROOT/..` arg and finally cwd; pass `"env": {"CLAUDE_PROJECT_DIR": "${CLAUDE_PROJECT_DIR}", "PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}"}` explicitly so a doc/impl mismatch still works; do not rely on cwd for `python -m bakery.server`. Log the resolved path at startup.
**Confidence basis:** documented (two pages conflict on export, one explicit on substitution); NOT run. A 1-minute check: print `os.environ.get("CLAUDE_PROJECT_DIR")` and `os.getcwd()` from the server.

## Q4. Python deps for hooks/MCP; first-run timeouts
**Answer:** No documented Python recipe. Docs say install Python deps "from a hook into the persistent data directory"; only a Node SessionStart example exists. Hook default timeout is 600 s (command), so a first-run install fits; the real risk is the MCP server starting before deps exist.
**Evidence:**
- plugins/loading.md "When the dependency install fails or is skipped": "install it from a hook into the persistent data directory. That includes packages that need their lifecycle scripts to build, Python dependencies, ...". Automatic install covers only npm/Bun `package.json` with lockfile.
- plugins/components.md "Install dependencies into the data directory": SessionStart hook that `diff -q` package.json against `${CLAUDE_PLUGIN_DATA}` copy, then `npm install`; "An MCP server can then set `NODE_PATH` ... in its `env`". Docs mention "virtual environments" as a use of CLAUDE_PLUGIN_DATA (components.md path-variables list).
- hooks.md "Common fields": `timeout` "Defaults: 600 for `command`"; SessionStart hooks "run in the background" in interactive start, "Claude's first response still waits for the hooks to finish" (hooks.md SessionStart).
- Race: matching hooks "run in parallel" (hooks.md line ~398); no sentence orders SessionStart hooks before MCP connection. mcp.md: "When a stdio plugin server's connection failed less than 15 minutes earlier, Claude Code skips the connection" (matches the `Skipping connection (recent failure cached ...)` notice seen in this session for playwright).
- Web search (SECONDARY): no official `uv`/venv-in-DATA example found.
**Recommendation (inference):** make the MCP `command` a small bootstrap script that creates `${CLAUDE_PLUGIN_DATA}/venv` and `pip install -r requirements.txt` on first run (idempotent, lock-guarded), then execs the server; hooks that need `anthropic` do the same via the same bootstrap. Avoids the SessionStart-vs-MCP race and the 15-minute skip.
**Confidence basis:** docs for the pieces; the race and recommendation are untested inference.

## Q5. SessionStart
**Answer:** Plain stdout on exit 0 becomes context; JSON `hookSpecificOutput.additionalContext` is the structured alternative. Matchers: startup, resume, clear, compact, fork.
**Evidence:** hooks.md line ~814: "The exceptions are `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and `PostModelSwitch`, where Claude Code adds plain-text stdout as context that Claude can see and act on." SessionStart section: "A hook that only adds context can print it without building JSON"; matcher table `startup | resume | clear | compact | fork`; `additionalContext` "String added to Claude's context at the start of the conversation, before the first prompt". Cap: "additionalContext, systemMessage, and initialUserMessage strings, and its plain stdout, are capped at 10,000 characters." Print "nothing but the JSON object" if using JSON. Lead's skeleton matcher `startup|resume|clear` omits `compact` and `fork` (observation: add `compact` if the instruction should survive compaction).
**Confidence basis:** documented practice, one page, unambiguous.

## Q6. PreToolUse `permissionDecision: "ask"`, `onFailure`
**Answer:** `onFailure` is real: values `"continue"` (default) or `"block"`, needs v2.1.295+ (installed 2.1.310 OK). `"ask"` is documented to prompt in auto mode; for bypassPermissions the docs only guarantee `"deny"`, so "ask" there is UNDOCUMENTED.
**Evidence:**
- hooks.md Common fields: "`onFailure` | Whether the action that triggered the hook goes ahead when the hook fails: `"continue"` or `"block"` ... Requires Claude Code v2.1.295 or later". Applies to `command` and `http` hooks; "The field has no effect on ... `Stop`, `SubagentStop`, `TaskCompleted`, and `TeammateIdle`". Failure = cannot start, exit other than 0/2 ("even if it printed JSON that allows the action"), timeout, invalid JSON. Plain-text stdout is not a failure.
- hooks.md PreToolUse decision control: `permissionDecision` is allow/deny/ask/defer; "`"ask"` prompts the user to confirm"; `defer` needs `-p`. "Deny and ask rules are still evaluated regardless of what the hook returns".
- permission-modes.md (~line 187): prompts forced by "a hook" are still shown in auto mode: "because auto mode still shows you those prompts".
- hooks-guide.md "Hooks and permission modes": "a hook that returns `permissionDecision: "deny"` blocks the tool even in `bypassPermissions` mode or with `--dangerously-skip-permissions`." The "actions no mode auto-approves" list (permission-modes.md) names explicit ask RULES, org-ask connectors and `requiresUserInteraction` MCP tools; hook "ask" is not listed. In `-p` runs an unanswerable ask is denied (hooks.md `permissionDecisionReason` row).
- Timeout caveat: hooks.md "Timeouts": on PreToolUse a timed-out hook "doesn't block the tool call, except for hooks whose failure blocks the action" so keep `onFailure: "block"` on the guard.
- Alternative (documented): mcp.md "Require approval for a specific tool": `_meta["anthropic/requiresUserInteraction"]: true` on a tool prompts "even in `acceptEdits`, `auto`, and `bypassPermissions`". Only for tools of a server WE write (bakery pay tool), and unconditional (no threshold).
**Recommendation (inference):** over-threshold in bypass mode: return `deny` with a reason telling the agent to ask the owner, rather than relying on `ask`.
**Confidence basis:** documented; bypass+ask not run.

## Q7. PostToolUse concurrency; Stop input
**Answer:** Yes, PostToolUse fires concurrently for parallel tool calls (use a file lock for the hash chain). `last_assistant_message` and `stop_hook_active` are real Stop input fields.
**Evidence:** hooks.md PostToolBatch: "`PostToolUse` fires once per tool, which means it fires concurrently when Claude makes parallel tool calls. `PostToolBatch` fires exactly once with the full batch". Also "When an event fires, its matching hooks run in parallel." Stop input: "Stop hooks receive `stop_hook_active`, `last_assistant_message`, `background_tasks`, and `session_crons`. The `stop_hook_active` field is `true` when Claude Code is already continuing as a result of a stop hook." `last_assistant_message` "contains the text content of Claude's final response". Also: 8-consecutive-continuation cap (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`); Stop does not fire on user interrupt; `onFailure` does nothing on Stop.
**Confidence basis:** documented, explicit.

## Q8. Protecting policy.json and logs/** from a plugin
**Answer:** Confirmed: a plugin cannot ship `permissions.deny`. Supported route is a plugin PreToolUse hook (`hooks/hooks.json`) on `Edit|Write|NotebookEdit` plus `Bash` inspection; it is leaky for Bash. Project `.claude/settings.json` deny rules are the stronger route.
**Evidence:** plugins/components.md "Default settings": "Two keys take effect, `agent` and `subagentStatusLine`, and every other key is dropped." permissions.md "Extend permissions with hooks": precedence covers "hooks in settings files and in a plugin's `hooks/hooks.json`". hooks-guide.md "Block edits to protected files" (exit 2 on `tool_input.file_path`). hooks.md PreToolUse input: file-tool paths are absolute and `~`/relative expanded "so a hook that matches on paths can't be bypassed via `~` or a relative spelling". hooks-guide.md: hook deny holds "even in `bypassPermissions`". permissions.md ~line 289: "Bash permission patterns that try to constrain command arguments are fragile". Lead's own repo `.claude/settings.json` (lines 2-11) holds deny rules for dev only; it is not a plugin component (manifest-reference.md "Standard layout" lists no `.claude/`).
**Recommendation (inference):** hook denies Write/Edit to `policy.json`, `logs/**`, `bakery.db`; for Bash, deny commands whose text names those paths or `sqlite3`; state in docs that Bash coverage is best-effort; ship the deny list for the business project via the onboarding skill writing `.claude/settings.json` (user-approved), if a hard guarantee is wanted.
**Confidence basis:** documented; Bash-bypass leakiness is documented as fragility of patterns, not tested for hooks.

## Q9. smb-onboard "Cowork session memory directory"
**Answer:** No Claude Code equivalent is defined. The nearest thing is Claude Code auto memory, which the model manages itself; so the profile may land there, in `CLAUDE.md`-style memory, or nowhere. UNVERIFIED by a run.
**Evidence:** small-business/skills/smb-onboard/SKILL.md:41: "Write the block to the Cowork session memory directory under the heading `## Business context` using the exact format in [reference/onboard-checklist.md]". SKILL.md:32: "Check memory for a `## Business context` block **first**." Same phrase at reference/onboard-checklist.md:75 and shared/document-format.md:13, reference/examples/happy-path.md:95. smb-router/SKILL.md:34: "Check session memory for `## Business context`." Frontmatter `allowed-tools: Read, WebFetch` (SKILL.md:11; no Write listed). No `CLAUDE.md`/`~/.claude` mention in the plugin (grep). Claude Code side, memory.md "Auto memory": "Each project gets its own memory directory at `~/.claude/projects/<project>/memory/`", with `MEMORY.md` index; settable via `autoMemoryDirectory`. Machine-local.
**Consequence (inference):** the lead's own `onboarding` skill should store the policy in `policy.json` (project) and not depend on SMB's profile persisting; treat SMB's "## Business context" as best-effort.
**Confidence basis:** skill text read PRIMARY; Claude Code behaviour for this phrase not tested.

## Q10. Plugin root = repo root
**Answer:** Works; nothing breaks, but four things to know.
**Evidence:**
- Root `CLAUDE.md` is not loaded: manifest-reference.md "Standard layout": "A `CLAUDE.md` at the plugin root isn't loaded as context, and `claude plugin validate` warns". Confirmed by running `claude plugin validate .` (here): "root: CLAUDE.md at the plugin root is not loaded as project context." Result "Validation passed with warnings". The team guide therefore does not reach plugin users (expected).
- Root `.mcp.json` would auto-load as plugin MCP config: manifest-reference.md "Claude Code loads `.mcp.json` at the plugin root first, then each declared shape". The worktree has none today (`ls -a`). Same for root `settings.json`, `.lsp.json`, `skills/`, `agents/`, `commands/`, `bin/` (Standard layout table): don't create a root `settings.json` or `bin/` by accident.
- `.claude/` is not a plugin component location (Standard layout); the repo's `.claude/settings.json` (PostToolUse `receipts.hook_log`, deny rules) is not applied to plugin users. In THIS repo while the plugin is also installed, the dev PostToolUse hook and the plugin hook would both run (hooks.md: same handler in settings is deduped, "A plugin's or skill's copy of the same handler stays separate").
- Size/clone: install copies the plugin dir to `cache/<marketplace>/<plugin>/<version>/` (loading.md "In-place and copied plugins"). A GitHub clone has only tracked files: `git ls-files | wc -l` = 39; the 206 MB working dir is `.venv` etc. (gitignored). `source: "./"` and submodules: marketplace-reference.md ~line 187 "gets every submodule in the repository or none".
- Version: validate warns "No version specified"; omitting it tracks commits (lead's finding); after pushing, users need `claude plugin marketplace update the-ledgers` (see Q1 stale catalog).
- Dependency side-effect: small-business ships a 35-server `.mcp.json` (python read), so installing ours adds 35 remote MCP servers (most need auth) alongside bakery-local.
**Confidence basis:** documented plus one validate run; install-time cache copy not inspected.

## Gaps
- Q3: stdio cwd undocumented; PROJECT_DIR substitution vs the manifest-reference "exported" table conflict, not run.
- Q4: SessionStart-vs-MCP startup order undocumented; no official Python venv example.
- Q6: hook "ask" under bypassPermissions not documented and not run; Q9: Claude Code behaviour for "Cowork session memory directory" not run.
- Q1 error text from binary strings is static; superseded by the lead's run. Issue #86493 first read via an aggregator mirror (SECONDARY), then confirmed with `gh` (PRIMARY).
- Not checked: Windows path quirks; managed-settings effects; `claude plugin install` behaviour with a dependency declared in BOTH plugin.json and the marketplace entry (duplicates?).

## Leads
1. Empirical test of hook `ask` in `--permission-mode bypassPermissions` and `auto` (scratch dir, `claude -p` with a stub hook): decides whether the over-threshold gate may use `ask`.
2. MCP server env probe (cwd, `CLAUDE_PROJECT_DIR`) via a 10-line stub server plugin; also whether the server starts before a SessionStart install finishes.
3. Declaring the dependency in the marketplace entry (clearer install-time refusal per dependencies.md) vs plugin.json only: test both in a clean CLAUDE_CONFIG_DIR.
4. Pay-tool names across SMB's stripe/paypal/square/ramp/airwallex servers, to write the PreToolUse matcher.
