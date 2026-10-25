# Plan: checks, guards, verify, skills and hooks (Anthony's lane)

Revision 2, 2026-10-25 ~13:00 PT, after Anthony's answers. Written for Anthony and for the agent session working in
the team repo (this repo). Read it cold: paths are absolute or repo-relative to that
repo. The open questions left are in §8. Their defaults are labeled.

## 1 · What this builds

The bakery Monday task, run as an order lifecycle. Sweet Rose Bakery orders ingredients from a supplier, the
supplier fulfills the order and invoices, and the agent pays. Every read and write goes through the MCP server to
the SQLite DB. Anthony owns the deterministic **checks and guards**, the **verify** step that builds the receipt,
and the **skills and hooks** around them.

- **Checks library (`checks/`):** pure Python with no AI and no network. **The MCP server imports it and runs
  it inside its write tools**, so a failing check refuses the write before anything persists. We provide the
  logic; Luke and Owen call it.
- **Hooks:**
  - a thin PreToolUse hook that forces the human permission prompt for over-threshold payments;
  - PostToolUse hooks that open and update the order receipt and append to the log;
  - a Stop hook that runs claim extraction and verify;
  - a SessionStart hook that starts onboarding.
- **Verify (`verify/`):** builds the final order receipt JSON from the log, the DB, the policy and the agent's
  claims. The website renders it.
- **Claim extraction (core):** pulls what the agent says it did out of its final message, then compares that
  with the DB. Starts from Anthony's local extraction draft, which is not in this repo yet; task 6 commits it.
- **Skills:** onboarding (owner Q&A, which writes `policy.json`), the order workflow, the payment workflow, and
  working with the DB through MCP.

Source: the team whiteboard (4 photos, 2026-10-25 ~12:40) and PR #1's redraw (`docs/whiteboard/2026-10-25-flow.html`,
branch `docs/whiteboard`). The original phone photos show the door code and Wi-Fi password.
**Never commit them.** PR #1's copy is already redacted.

### Whiteboard, as text

| Board area | What it says |
|---|---|
| Roles | Lana: website. Luke + Owen: MCP + proxy. Anthony: checks, skills, hooks. Ronaldo: DB |
| Order lifecycle | order → DB. Who authorized it, with what permissions, agent or human? A passkey or hash for auth |
| Black box | supplier fulfills the order and sends an invoice → DB. **The MCP server plays the supplier too** (Anthony, 13:15): Luke and Owen simulate fulfillment and the invoice |
| Payment (demo stage 1) | payment-ready trigger (time or request) → DB: payment + order data → validate → hook → final order receipt → JSON → shown in UI |
| Outcome | the receipt is saved to the DB, with the order info |
| Governing policies | payment · order · budget (monthly, bank account total) |
| Skills | interact with the DB via MCP · order workflow · payment workflow · onboarding with a hook trigger |
| Hooks | order receipt generation (JSON) · guards: email spoofing, policy, security |
| Onboarding (starred) | open Claude (Desktop? Code?) → run onboarding → plugin install (+ SMB plugin) → Q&A → policy, tools, external systems. Developer onboarding: SQL, MCP |
| Assumptions | owner uses Claude Code · guardrail is a payment threshold · checks verify order sent and payment sent · the order receipt is generated at order start · build around the MCP proxy and the Claude SMB plugin |
| What we build | website (dashboard, policies + alerts, order receipts) · MCP (bank, inventory, payments: simulated) · DB (SQLite, the ledger) · checks (deterministic, no AI, behind MCP) |

## 2 · Decisions

| # | Decision | From | Rejected, and its cost |
|---|---|---|---|
| D1 | Checks run inside the MCP server's write tools, which import our library. A block returns `{"ok": false, "blocked": [...]}` and writes nothing. If the checks crash, the tool refuses: fail closed in code we control | Anthony, 13:00 | A PreToolUse command hook as the only gate: it duplicates DB access outside the server |
| D2 | Human approval over the payment threshold comes from a thin PreToolUse hook that returns `permissionDecision: "ask"`. It forces the prompt even in auto mode, and the agent can't answer it (hooks.md:1960, 1971). The server can't prompt a human, so this one check also lives in a hook, calling the same library function | default | Passkey or hash auth: Future |
| D3 | One receipt per order, in one JSON file. It's created the moment the order is submitted, from the server's response: the order confirmation plus the supplier's invoice. It's updated at each step after that (approval, payment, read-back) and finalized at Stop with claims and verdict | Anthony, 13:25 | A receipt only at the end, which loses the board's "generated at order start" |
| D4 | The policy is `policy.json`, written by the onboarding skill. A deny rule blocks agent edits afterwards. The MCP server and website read it | Anthony, 13:00 | A DB table: waits on the schema, and the agent could call the write tool |
| D5 | Claim extraction is core. The final message goes in, claims come out, and verify compares them with the DB | Anthony, 13:00 | — |
| D6 | Build against fixtures until the DB and MCP land. Checks read records through one `Source` interface: `FixtureSource` now, `SqliteSource(conn)` when Ronaldo's schema lands, using the server's own connection | default | Waiting on the DB |
| D7 | Payment-ready trigger in the demo: the owner asks. SessionStart also lists invoices due within N days | default | cron or launchd: Future |
| D8 | Our plugin depends on and wraps the Claude for Small Business plugin (`small-business@knowledge-work-plugins`, v1.35.1 at 33d3dea). We use its skills: `smb-onboard`, `ap-processor` and `pay-the-bills` (which never sends money) and `inventory-planner`. We add the execution through MCP, the checks and the receipt. Install: `"dependencies": [{"name": "small-business", "marketplace": "knowledge-work-plugins"}]` in our `plugin.json`, plus `"allowCrossMarketplaceDependenciesOn": ["knowledge-work-plugins"]` in our `marketplace.json`. Installing ours then installs theirs (plugin-dependencies.md:58, 89). Without the allowlist entry, the install completes without the dependency and our plugin fails to load (:110). There's no version range, because a range resolves against git tags (`small-business--v<ver>`) that their repo may not have (:51, 143). The install doc keeps the two-command manual path as a fallback | Anthony, 13:25 (goal); docs read 13:30 | Manual install instructions only: one more step for a non-developer owner |

**Conflict to settle (D1):** `docs/PLAN.md` says "The server never checks policy. Blocking is the guard's job" and gives
Ronaldo a PreToolUse `guard.py`. D1 moves policy checks into the MCP write tools instead. Anthony and Ronaldo decide;
either way the check logic is the shared `checks/` library, so only the call site changes.

## 3 · Dependencies and interfaces

### Schema on main (read 2026-10-25 ~14:05, `bakery/seed.py` at 1dcb36a)

Ronaldo's seed replaces the assumed shapes below. Names in this plan map to it as follows:

| This plan says | `bakery.db` on main |
|---|---|
| supplier | `vendors (id, name, email, bank_account)`. C8's domain comes from `vendors.email` |
| order | `orders (id, vendor_id, order_date, status placed/received/cancelled, total_cents)` + `order_items` |
| supplier invoice | `bills (id, vendor_id, amount_cents, due_date, status, order_id)`. The `invoices` table is customer receivables, not this |
| bank balance | `accounts (id, name, balance_cents)`, e.g. `ACC-OPS` |
| policy | **`policies (id, kind, title, limit_cents)`**: POL-PAY-THRESHOLD ($500), POL-PAY-ACCOUNT, POL-BUDGET-MONTHLY, POL-BANK-FLOOR, POL-ORDER-VENDOR |

**Conflict to settle (D4):** the plan says the policy is a `policy.json` written by onboarding. Main already keeps it
in a DB `policies` table that the guard reads, with ids the order receipt cites. The options:
- **Keep the table.** Onboarding writes the rows through an MCP tool, and the receipt's `policy.sha256` becomes a
  hash over those rows.
- **Keep the JSON file.** Onboarding writes it, and the seed loads the table from it.

Anthony and Ronaldo decide. Until then, check IDs cite the `POL-*` ids.


| Party | We need | We give | Until it lands |
|---|---|---|---|
| Ronaldo (DB) | Tables and columns for suppliers, orders, invoices, payments, bank balance | `SqliteSource` written against his schema | `checks/fixtures/*.json` in the assumed shape below |
| Luke + Owen (MCP + proxy) | Tool names and argument shapes; a call to `checks.evaluate(...)` at the top of each write tool; a `blocked` field in the response; the proxy's role. **The supplier simulation**: after an order, the server writes the invoice itself, with demo fault modes for a spoofed sender domain, a changed pay-to account, an amount that differs from the order, and a dropped write | The library, its signature, an example call site, tests they can run, and the fault cases §5 needs | Assumed tool names below; fixtures stand in for supplier invoices |
| Lana (website) | Which receipt fields the page renders; file or Supabase (PR #1 options A/B) | `contracts/samples/order_receipt.json` plus its schema | The sample in §6 |

The interface we hand Luke and Owen. Task 1 freezes it.

```python
from checks import evaluate, load_policy
results = evaluate(action="pay_invoice", args={...}, source=SqliteSource(conn), policy=load_policy(path))
# -> list[CheckResult(id, status: "pass"|"block"|"ask"|"unknown", title, evidence: list[str])]
# The tool writes only if no result is "block". "ask" is enforced by the PreToolUse hook (D2).
```

The assumed record shapes, until Ronaldo's schema replaces them. Record each change here.

```
suppliers (id, name, email_domain, bank_account)
orders    (id, supplier_id, items_json, total_cents, status, created_by, created_at)
invoices  (id, order_id, supplier_id, amount_cents, from_addr, pay_to_account, received_at)
payments  (id, invoice_id, amount_cents, to_account, status, created_at)
bank      (balance_cents, as_of)
```

Assumed MCP tools: `create_order(supplier_id, items)`, `pay_invoice(invoice_id, amount_cents, to_account)`,
`list_invoices(status)`, `get_balance()`. `create_order` returns the order confirmation **and** the supplier's
invoice in one response, and writes both to the DB (Anthony, 13:25). The shape is assumed:
`{"ok": true, "order": {"id", "status": "confirmed", "total_cents"}, "invoice": {"id", "amount_cents", "from_addr", "pay_to_account", "due_date"}}`.
The demo's bad invoices are fault modes on this response.

## 4 · Tasks, in order

Every task follows the same flow: a branch, a PR, a reviewer subagent, then a person's review. Nothing reaches
`main` without that person. Team repo rules apply:
- post a 3-bullet plan and wait for a yes before code;
- commits of ≤ 300 lines;
- `make test` before every commit;
- edit only the folders agreed as yours (§8 Q-folders).

| # | Task | Subagent | Done when | Blocked by |
|---|---|---|---|---|
| 0 | Research note. Covers: the plugin layout, copied from an installed official plugin (`~/.claude/plugins/cache/claude-plugins-official/*/.claude-plugin/plugin.json`); `hooks/hooks.json` and `${CLAUDE_PLUGIN_ROOT}` (hooks.md:629, 480); marketplace install from a GitHub repo; SessionStart stdout as context (hooks.md:814); Stop's `last_assistant_message` | researcher (sonnet) | A one-page note with a file:line for every claim | — |
| 1 | Contracts: `policy.schema.json`; `order_receipt.schema.json` (opened, updated, final); `CheckResult`; the `evaluate` signature; samples for each | executor (opus) | Samples validate (`jsonschema`); Lana, Ronaldo, Luke and Owen say yes in the team channel | — |
| 2 | Checks library `checks/`: `Source`, `FixtureSource`, checks C1–C10 (§5), `evaluate`, `load_policy`. A corrupt or missing policy gives `block` | executor (opus) | §5 table tests pass in `make test`; nothing imports `anthropic` or networking | 1 |
| 3 | MCP hand-off: an example call site, plus `tests/test_server_checks.py` that Luke and Owen run against their tools. A blocked call writes no row; a crashing check refuses | executor (opus), with Luke + Owen | Their server passes the tests on a fixture DB | 2, MCP tool names |
| 4 | Approval hook: PreToolUse on the pay tool. Calls C1, returns `ask` over the threshold, and has `onFailure: "block"` (needs Claude Code v2.1.295 or later) | executor (opus) | Pipe tests: under the threshold gives no decision; over it gives `ask`; a missing policy blocks | 2 |
| 5 | Receipt and log hooks: PostToolUse on create order opens `receipts/<order_id>.json`; on pay it updates the receipt. The log is main's `receipts/hook_log.py`, already wired to every call in `.claude/settings.json`; task 5 reads it and adds no second log entry. Writes are atomic (temp file + rename) under a file lock | executor (opus) | Replaying a fixture event stream gives the sample receipt; two parallel calls lose no update; the chain verifies | 1, 2 |
| 6 | Claims: port `extraction/` to contract 3 (the actions now include `create_order` and `pay_invoice`; amounts in integer cents; `target` is the name as the summary says it). Use `messages.parse` on Haiku 5.5 with no `temperature`. This deliberately differs from PLAN.md's temperature 0, because Haiku 5.5 returns 400 on a non-default temperature (claude-api model-migration.md:2295). Drop any claim whose quote isn't in the summary | executor (opus) | Unit tests offline; golden set (live, `RUN_LIVE=1`, with Anthony's go on spend) at 9/10, stable across 3 runs | 1 |
| 7 | Verify: `verify.py`. Step 0: chain intact. Step 1: log against DB (`phantom`). Step 2: expected order against actual (`not_done`). Step 3: claims against DB (`false_claim`, `silent_action`). Step 4: rerun the pre-payment checks as of just before the payment (§6a) and compare with the recorded results. Then the verdict. The Stop hook runs extract and verify, then finalizes the receipt; `make receipt` reruns them when Stop didn't fire | executor (opus) | One fixture set per status gives that status; the tampered-log fixture gives `UNTRUSTED` | 5, 6 |
| 8 | Onboarding: SessionStart hook (no `policy.json` → tell Claude to run the onboarding skill; otherwise a short policy summary plus invoices due soon). Onboarding skill: Q&A for threshold, monthly budget, bank floor, approved suppliers (bank account, email domain), tools, external systems; writes `policy.json`. It runs after the SMB plugin's `smb-onboard` and skips what that already asked (Q-smb-onboard) | executor (opus) | In a fresh `CLAUDE_CONFIG_DIR` with the plugin installed, onboarding starts unprompted and writes a policy that validates | 0, 1 |
| 9 | Workflow skills: order, payment, and DB via MCP. Each names which tool to call when, reads back after every write, and never pays an account that differs from the one on file | executor (opus) | A dry run follows each skill to the end; a reviewer confirms every tool it names exists | 0, MCP tool names |
| 10 | Plugin packaging: the manifest, with the SMB plugin in `dependencies` and our `marketplace.json` allowlist (D8). Done-test addition: one `claude plugin install` in a clean config dir installs both plugins; `hooks.json` with `${CLAUDE_PLUGIN_ROOT}`; deny rules on `policy.json`, `receipts/**`, `logs/**`, `Bash(sqlite3:*)`; an install page for owners and for developers (SQL, MCP) | executor (opus) | Installs from the repo in a clean config dir; `/plugin` lists it; hooks fire on a stub call | 4–9 |
| 11 | Swap `FixtureSource` for `SqliteSource` on Ronaldo's DB; rerun every test with the real tools; one live run | executor (opus) | The same tests pass on the real DB; the live run gives the expected receipt | DB + MCP |

Tasks 0, 1 and 2 can start now. 4, 5, 6 and 8 run in parallel after 1–2. 3, 9 and 11 wait on the MCP and DB.

**Stop and come back to Anthony** at the first thing that changes this plan:
- Ronaldo's schema differs from §3;
- the tool names don't fit;
- the proxy already blocks calls;
- a contract owner says no in task 1.

## 5 · Checks and their test cases

The checks are deterministic. They read only the policy and the records, through `Source`.

| ID | Check | Runs in | Fails as |
|---|---|---|---|
| C1 | payment amount ≤ policy threshold | approval hook | `ask` (human prompt) |
| C2 | month-to-date paid + this payment ≤ monthly budget | MCP pay tool | block |
| C3 | bank balance − payment ≥ bank floor | MCP pay tool | block |
| C4 | `to_account` equals the supplier's account on file | MCP pay tool | block |
| C5 | invoice amount equals the order total | MCP pay tool | block |
| C6 | invoice links to a known order from the same supplier | MCP pay tool | block |
| C7 | no live payment exists for this invoice | MCP pay tool | block |
| C8 | invoice sender domain equals the supplier's domain on file (spoofing) | MCP pay tool | block |
| C9 | supplier is on the approved list, and order total ≤ order limit | MCP create-order tool | block |
| C10 | after the call, the order and payment rows exist with the logged values | verify | `phantom` |

| Test | Input | Expected |
|---|---|---|
| clean payment | $800 to the account on file, threshold $1,000 | all pass, receipt `VERIFIED` |
| over threshold | $1,500, threshold $1,000 | C1 → `ask` |
| budget exceeded | MTD $4,500 + $800, budget $5,000 | C2 → block |
| below bank floor | balance $1,000 − $800, floor $500 | C3 → block |
| changed account | invoice says ••3210, file says ••4471 | C4 → block |
| amount mismatch | invoice $880, order $800 | C5 → block |
| orphan invoice | invoice with no order | C6 → block |
| double pay | second payment for one invoice | C7 → block |
| spoofed sender | `billing@flourco-payments.example` vs `flourco.example` | C8 → block |
| unapproved supplier | order to a supplier not in the policy | C9 → block |
| dropped write | pay returns ok, no payment row | C10 → `phantom` |
| overclaim | summary "paid Flour Co and Mill Co", one payment row | `false_claim` |
| silent action | payment row the summary never mentions | `silent_action` |
| check crash | policy file missing or corrupt | the tool refuses (fail closed) |

The values above are illustrative. Tests on seed data use main's policies: threshold $500, monthly budget $3,000, bank
floor $2,000, balance $4,800. BILL-07 is $800, so a clean payment of it reaches C1 `ask` before it passes.
Names on main: the pay tool is `pay_bill(bill_id, amount_cents, to_account)` (PLAN.md), `payments` keys on `bill_id`,
and `orders.status` is `placed`/`received`/`cancelled`. Read `pay_invoice`, `invoice_id` and `confirmed` in this plan as those.

## 6 · Order receipt JSON (default shape, finalized in task 1)

Superseded in part by §6a: the stage-1 receipt also carries `order`, `invoice`, `checks_version` and `checks[].inputs`.
Task 1 writes the real sample.

```json
{"order_id": "ORD-1", "opened_at": "2026-10-25T13:00:00Z", "closed_at": null,
 "expected": {"supplier": "Flour Co", "items": [{"sku": "flour-50lb", "qty": 4}], "total_cents": 80000},
 "authorized": {"by": "human", "how": "permission_prompt", "at": "..."},
 "policy": {"sha256": "...", "threshold_cents": 100000},
 "events": [{"ts": "...", "tool": "mcp__bank__pay_invoice", "result": "ok", "ref": "pay_1", "log": 7}],
 "claims": [{"action": "pay_invoice", "target": "flour co", "amount_cents": 80000, "quote": "Paid Flour Co $800"}],
 "checks": [{"id": "C4", "status": "block", "title": "Account differs from Flour Co's on file", "evidence": ["log:7", "invoices:INV-7"]}],
 "chain": {"ok": true, "entries": 12, "head": "..."},
 "verdict": "ISSUES_FOUND"}
```

Every account number is masked to its last 4 before writing. Synthetic data only.

## 6a · Demo stage 1 slice (focus, 13:50)

One payment, end to end, with checks. Nothing else is needed for stage 1.

1. The owner asks for an order. `create_order` returns the confirmation and the invoice, and the receipt is created.
2. The owner asks to pay the invoice. The pay tool runs the payment checks. A block refuses the payment; over the
   threshold, the owner is prompted.
3. After the payment, C10 confirms the payment row exists, and the receipt gets each check's result and the verdict.
4. The website shows the receipt JSON.

The checks for stage 1: **C1** (threshold → ask), **C4** (pay-to account matches the one on file), **C5** (invoice amount
equals the order), **C7** (no double payment), **C8** (sender domain matches the supplier's), **C10** (payment row exists).
Demo runs: one clean payment (`VERIFIED`), one with the changed account (C4 blocks), one with the spoofed sender
(C8 blocks). The receipt schema needs only `order`, `invoice`, `events`, `checks[]`, `verdict`, `checks_version` and
`policy.sha256` for this slice.

**Check logic never lives in the receipt (13:55).** The receipt stores results; the logic lives only in `checks/`.
- **Each `checks[]` entry:** `id`, `status`, `title`, `evidence` (refs such as `invoices:INV-7`, `log:7`) and
  `inputs`, which holds the masked values the check compared, e.g. `{"pay_to": "••3210", "on_file": "••4471"}`.
- **`checks_version`:** the git commit of the checks library that ran.
- **`policy.sha256`:** the hash of the `policy.json` that ran.
- **Verify reruns the checks at finalize.** It recomputes each pre-payment check from the DB as it stood just before the
  payment under test (that payment's own row and later writes excluded, or C7 would always fail), with the same version and policy. A stored result that differs from the rerun is a finding of its own, and the verdict can't be `VERIFIED`.
- **The website renders `title`, `evidence` and `inputs` as given** and evaluates nothing.
- Rejected: logic in the receipt or in the hook that writes it. Whatever writes the receipt would then be grading itself.

## 7 · Must / nice / future

- **Must (demo stage 1):**
  - tasks 1–8 and 10;
  - checks C1, C4, C5, C7, C8 and C10;
  - claims vs DB;
  - the opened-and-finalized receipt;
  - onboarding through the SessionStart hook.
- **Nice:**
  - checks C2, C3 and C9;
  - workflow skills (task 9);
  - the "due soon" list;
  - `run_status.json` progress for the website (PR #1), with the receipt hook as its one writer.
- **Future:** passkey or hash auth, scheduled payment runs, Claude Desktop (Cowork) install, copying the policy and
  receipts into the DB through MCP.

## 8 · Open questions

- **Q-folders:** which team-repo folders are Anthony's? Proposed: `checks/`, `verify/`, `hooks/`, `skills/`, `.claude-plugin/`.
  Main's CLAUDE.md gives `claims/` to Person 2 and `receipts/` to Ronaldo, so task 6's folder and task 5's
  `receipts/<order_id>.json` output path are questions for them. Settle it in the team channel before task 1's PR.
- **Q-proxy:** does Luke and Owen's proxy log or block calls too? If it logs, task 5's log may duplicate it.
- **Q-db-write:** who saves the final receipt into the DB ("Outcome receipt → DB")? Default: an MCP tool
  `save_receipt(json)` that Luke and Owen add, called by the Stop hook.
- **Q-supplier-tools (settled 13:25):** the invoice comes back from `create_order` itself, so the agent has no
  tool that writes invoices. The checks don't run on the supplier's side of that response. They run when the agent
  pays (C1–C8) and when it orders (C9).
- **Q-smb-onboard:** the SMB plugin's `smb-onboard` saves its business profile to "the Cowork session memory
  directory" (`small-business/skills/smb-onboard/SKILL.md:41`). Where that lands under Claude Code is untested.
  Task 8 must check it, so our onboarding can read the profile and skip questions it already asked.
- **Q-ask-in-server:** default D2 keeps the human prompt in a hook. Alternative: the server refuses any
  over-threshold payment unless the call carries an approval the owner gave. That is Future: it needs auth.
