# Plan: checks, guards, verify, skills and hooks (Anthony's lane)

Revision 3, 2026-10-25 ~14:35 PT: brought in line with PRs #2, #4, #10 and #13 as merged (§0) and the decisions made
since revision 2. Revision 3.1, 14:42: §8 Q-supplier-tools and Q-policy-seed settled by Anthony. Written for Anthony and for the agent session working in the team repo (this repo). Read it cold:
paths are repo-relative. The open questions left are in §8. Their defaults are labeled. **Where §0 and a later
section disagree, §0 wins.**

## 0 · Main as merged (read at 47423e6, 14:30)

| Merged | What it put on main | What it changes in this plan |
|---|---|---|
| PR #2, receipt schema and sample | `docs/mock/order_receipt.schema.json` (`order-receipt/v0`) and `order_receipt.json`. Verdict `VERIFIED` / `ISSUES_FOUND` / `UNTRUSTED`. Six stages, `order_placed` → `order_sent` → `fulfilled` → `bill_received` → `payment_ready` → `payment_sent`. Each `checks[]` entry requires `id`, `status`, `lifecycle_stage`, `kind`, `title` and `evidence` (refs shaped `s1:log:7`, `inbox:5` or `summary`); `guard` and `inputs` are optional. Top level carries `checks_version` and `policy.sha256` | The receipt half of task 1 is done. §6 and §6a defer to this schema. Check results use its `status` enum (`verified`, `blocked`, `flagged`, `needs_approval`, `phantom`, `false_claim`, …), not `pass`/`block`/`ask` |
| PR #4, BakeSupply (Owen) | A second MCP server, `bakesupply`, playing Flour Co with its own `bakesupply.db`. Tools: `list_products`, `get_price`, `place_order(sku, quantity)`, `list_orders`. `place_order` takes one SKU and returns `{ok, id: "ord_N", sku, quantity, unit_price_cents, total_cents, created_at}` | **No tool returns an invoice, and `create_order` exists nowhere.** D3 and §6a assumed both. See §8 Q-supplier-tools |
| PR #13 | `tests/test_order_receipt.py` reads the seed DB | None |
| PR #10, install docs (Anthony) plus two seed commits (Ronaldo, 092e29b 14:20, 7bf070f 14:23) | README install steps. `bills` gains `from_addr` and `pay_to_account`, what the supplier's bill itself says; BILL-07 is the clean case (`billing@flourco.example`, account ending 4471). `policies` (POL-PAY-THRESHOLD $500, POL-BUDGET-MONTHLY $3,000, POL-BANK-FLOOR $2,000, POL-ORDER-VENDOR, POL-PAY-ACCOUNT) and `accounts` (ACC-OPS $4,800) are back, after c7740c4 (13:53) had removed them as "on hold" | C4 and C8 now have bill data to compare with `vendors`. The policy data exists again, but D4 still defers policy checks to #9: **the seed and D4 disagree**, see §8 Q-policy-seed |

`make test` on main at 18f27c0: `100 passed in 0.46s`. Not rerun at 47423e6.

Not merged yet, but other work depends on it:
- **`local-server` (Ronaldo):** the `bakery-local` server with `list_invoices`, `list_bills`, `list_orders`, `read_inbox`,
  `save_draft`, `send_email` and `pay_bill(bill_id, amount_cents, to_account)`. Commit fc2e67f (13:55) dropped
  `create_order`. Its `.mcp.json` registers only `bakery-local`. If `bakesupply` is registered under that name, its
  tools appear as `mcp__bakesupply__place_order`, so hooks must match both servers.
- **`feature/payment-checks`:** `checks/payment.py` holds seven checks (`PAY-PAYEE`, `PAY-BILL-ORDER`, …) that read
  only a finished receipt and return `pass`/`fail`/`warn`/`skip`. Its docstring says reconciliation against
  `bakery.db` is a separate set. These are after-the-fact consistency checks, not the pre-payment block:
  `payee_on_file` skips unless the payment was sent and compares last 4 digits only, so it is not C4. C4, C5, C7,
  C8 and C10 against the DB aren't in it. Verify needs a mapping from `pass`/`fail`/`warn`/`skip` to the receipt's
  status enum.
- **`plugin/skeleton`:** the plugin manifest and install note (PR #7, open).

Findings on the merged work. Each one names the check that would catch it:
- **F1:** the schema's top-level description says the receipt is created by "the PostToolUse hook on create_order",
  but no server has that tool. The fix waits on Q-supplier-tools. Check: grep the schema for a tool name that
  isn't in `bakesupply/server.py` (main) or `bakery/server.py` (`local-server`).
- **F2:** `policy.sha256` is required and described as "Hash of the policy.json that ran", but there is no
  `policy.json`. **Default for stage 1:** the sha256 of the `policies` rows as seeded (sorted by id, as JSON),
  labeled that way in the receipt. Check: the schema test runs on a stage-1 receipt.
- **F3:** sample checks `chk_1` (approved supplier), `chk_2` (budget, "$2,940 of $3,000") and `chk_6` (bank floor)
  are `kind: "policy"`, and `test_matches_seed` doesn't compare them with the `policies` rows. Check: extend
  `test_matches_seed` to every `kind: "policy"` check.
- **F4:** the sample's PO-2041 has two lines, all-purpose and bread flour. `place_order` takes one SKU per call
  and returns `ord_N` ids that nothing links to `PO-2041`. Check: a test that places PO-2041's lines through
  BakeSupply and joins the results to `orders`.

Merged since this section was read (14:33–14:59, not reviewed here): PRs #12 (payment checks), #7 (plugin skeleton),
#15 (approval hook), #24 (onboarding), #18 (DB checks), the `local-server` merge (both servers registered), and
347248d (C4–C8 inside `pay_bill`). Next revision of §0 reads them.

## 1 · What this builds

The bakery Monday task, run as an order lifecycle. Sweet Rose Bakery orders ingredients from a supplier, the
supplier fulfills the order and invoices, and the agent pays. Every read and write goes through the MCP server to
the SQLite DB. Anthony owns the deterministic **checks and guards**, the **verify** step that builds the receipt,
and the **skills and hooks** around them.

- **Checks library (`checks/`):** pure Python with no AI and no network. **The MCP server imports it and runs
  it inside its write tools**, so a failing check refuses the write before anything persists. We provide the
  logic; Luke and Owen call it.
- **Hooks:**
  - a thin PreToolUse hook that forces the human permission prompt on every payment (D2);
  - PostToolUse hooks that open and update the order receipt and append to the log;
  - a Stop hook that runs claim extraction and verify;
  - a SessionStart hook that starts onboarding.
- **Verify (`verify/`):** builds the final order receipt JSON from the log, the DB, the policy and the agent's
  claims. The website renders it.
- **Claim extraction (core):** pulls what the agent says it did out of its final message, then compares that
  with the DB. Starts from Anthony's local extraction draft, which is not in this repo yet; task 6 commits it.
- **Skills:** onboarding (owner Q&A; the policy part waits on #9), the order workflow, the payment workflow, and
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
| D2 | **The owner approves every `pay_bill` (stage 1).** A thin PreToolUse hook matching `mcp__bakery-local__pay_bill` returns `permissionDecision: "ask"` on every call, with no threshold until #9. This is the SMB plugin's own rule ("Do not auto-pay anything, ever"). The hook forces the prompt even in auto mode, and the agent can't answer it (hooks.md:1960, 1971). Bypass-permissions mode skips it, so the install page says not to use that mode, and SessionStart warns when it's on | Anthony, 14:30 | Passkey or hash auth: Future. A threshold: deferred to #9 |
| D3 | One receipt per order, in one JSON file (PR #2's schema). It's created the moment the order is submitted and updated at each step after that (approval, payment, read-back), then finalized at Stop with claims and verdict. **Which call creates it outside stage 1 is open** (§0 F1, F4; task 5). Stage 1 creates it on the first `pay_bill` (§6a) | Anthony, 13:25 | A receipt only at the end, which loses the board's "generated at order start" |
| D4 | **Policies and thresholds are deferred to issue #9** (Anthony, 14:25). The seed has a `policies` table again (7bf070f, 14:23), but stage 1 runs no policy checks (§8 Q-policy-seed), and C1 is the approval in D2. The SMB plugin v1.35.1 has no policy skill and no thresholds, only prose approval gates (`pay-the-bills/SKILL.md:29, :56, :80`; `ap-processor/SKILL.md:70, :78, :128`). Issue #9 starts from that | Anthony, 14:25 | `policy.json` from onboarding (revision 2), superseded |
| D5 | Claim extraction is core. The final message goes in, claims come out, and verify compares them with the DB | Anthony, 13:00 | — |
| D6 | Build against fixtures until the DB and MCP land. Checks read records through one `Source` interface: `FixtureSource` now, `SqliteSource(conn)` when Ronaldo's schema lands, using the server's own connection | default | Waiting on the DB |
| D7 | Payment-ready trigger in the demo: the owner asks. SessionStart also lists invoices due within N days | default | cron or launchd: Future |
| D8 | Our plugin depends on and wraps the Claude for Small Business plugin (`small-business@knowledge-work-plugins`, v1.35.1 at 33d3dea). We use its skills: `smb-onboard`, `ap-processor` and `pay-the-bills` (which never sends money) and `inventory-planner`. We add the execution through MCP, the checks and the receipt. Install: `"dependencies": [{"name": "small-business", "marketplace": "knowledge-work-plugins"}]` in our `plugin.json`, plus `"allowCrossMarketplaceDependenciesOn": ["knowledge-work-plugins"]` in our `marketplace.json`. Installing ours installs theirs only when the user has already added the `anthropics/knowledge-work-plugins` marketplace; otherwise the dependency is skipped (plugin-dependencies.md:58, 89, 110; tested by the plugin session). **The install is three steps:** add the knowledge-work-plugins marketplace, add ours, install `ledgers-receipts`. There's no version range, because a range resolves against git tags (`small-business--v<ver>`) that their repo may not have (:51, 143). A plugin's `settings.json` honours only `agent` and `subagentStatusLine`, so deny rules ship on the install page as project settings, not in the plugin | Anthony, 13:25 (goal); tested 14:20 | Manual install instructions only: one more step for a non-developer owner |

**D1 as built (main at 347248d, 14:59):** `pay_bill` calls `checks/gate.py`'s `evaluate()`, which runs C4–C8, and on a
block it refuses and saves nothing. That is D1's call site. Whether `docs/PLAN.md`'s guard hook stays alongside it is
Ronaldo's call.

## 3 · Dependencies and interfaces

### Schema on main (read at 47423e6, 14:30: `bakery/seed.py`, `bakesupply/seed.py`)

Ronaldo's seed replaces the assumed shapes below. Names in this plan map to it as follows:

| This plan says | On main |
|---|---|
| supplier | `bakery.db` `vendors (id, name, email, bank_account)`: V-1 Flour Co, `billing@flourco.example`, account on file ends 4471. C8's domain comes from `vendors.email` |
| order | `bakery.db` `orders (id, vendor_id, order_date, status placed/received/cancelled, total_cents)` + `order_items`. PO-2041 ($800, `placed`) is the demo order |
| supplier's own order | `bakesupply.db` `orders (id, sku, quantity, unit_price_cents, total_cents, created_at)`, one SKU per row, with no link to `bakery.db` |
| supplier invoice | `bakery.db` `bills (id, vendor_id, amount_cents, due_date, status open/paid, order_id, from_addr, pay_to_account)`. BILL-07 ($800, PO-2041, due 2026-10-27, from `billing@flourco.example`, pay to the account ending 4471) is seeded. C8 compares `from_addr`'s domain with `vendors.email`'s, and C4 compares `pay_to_account` and the `pay_bill` `to_account` with `vendors.bank_account`. The `invoices` table is customer receivables, not this |
| bank balance, policy | `accounts (id, name, balance_cents)`: ACC-OPS $4,800. `policies (id, kind, title, limit_cents)`: POL-PAY-THRESHOLD $500, POL-BUDGET-MONTHLY $3,000, POL-BANK-FLOOR $2,000, POL-ORDER-VENDOR, POL-PAY-ACCOUNT. Restored 14:23 (7bf070f); unused in stage 1 (D4) |

The assumed shapes and tool names below are revision 2's. Read them through this table and §0.


| Party | We need | We give | Until it lands |
|---|---|---|---|
| Ronaldo (DB) | Tables and columns for suppliers, orders, invoices, payments, bank balance | `SqliteSource` written against his schema | `checks/fixtures/*.json` in the assumed shape below |
| Luke + Owen (MCP + proxy) | Tool names and argument shapes; a call to `checks.evaluate(...)` at the top of each write tool; a `blocked` field in the response; the proxy's role. **The supplier simulation**: after an order, the server writes the invoice itself, with demo fault modes for a spoofed sender domain, a changed pay-to account, an amount that differs from the order, and a dropped write | The library, its signature, an example call site, tests they can run, and the fault cases §5 needs | Assumed tool names below; fixtures stand in for supplier invoices |
| Lana (website) | Which receipt fields the page renders; file or Supabase (PR #1 options A/B) | `docs/mock/order_receipt.json` plus its schema (merged, PR #2) | The merged sample |

The interface we hand Luke and Owen. Task 1 freezes it.

```python
from checks import evaluate, load_policy

results = evaluate(
    action="pay_invoice", args={...}, source=SqliteSource(conn), policy=load_policy(path)
)
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

MCP tools as built (§0): `mcp__bakery-local__pay_bill(bill_id, amount_cents, to_account)`, `list_bills`, `list_orders`,
`read_inbox`, `save_draft`, `send_email`, `list_invoices` (branch `local-server`), and `mcp__bakesupply__place_order(sku,
quantity)`, `get_price`, `list_products`, `list_orders` (main). There's no `create_order` and no `get_balance`.
Anthony asked (13:25) for the order call to return the confirmation **and** the supplier's invoice. Nothing built
does that yet: §8 Q-supplier-tools.

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
| 4 | Approval hook: PreToolUse on the pay tool. Returns `ask` on every `pay_bill` (D2) and has `onFailure: "block"` (needs Claude Code v2.1.295 or later) | executor (opus) | Pipe tests: every `pay_bill` call gives `ask`; other tools get no decision; a hook crash blocks (`onFailure`) | 2 |
| 5 | Receipt and log hooks: PostToolUse on the first `pay_bill` for an order opens `receipts/<order_id>.json` (on `place_order` once F4 settles how an order maps to its calls); later calls update it. The log is main's `receipts/hook_log.py`, already wired to every call in `.claude/settings.json`; task 5 reads it and adds no second log entry. Writes are atomic (temp file + rename) under a file lock | executor (opus) | Replaying a fixture event stream gives the sample receipt; two parallel calls lose no update; the chain verifies | 1, 2 |
| 6 | Claims: port `extraction/` to contract 3 (the actions now include `place_order` and `pay_bill`; amounts in integer cents; `target` is the name as the summary says it). Use `messages.parse` on Haiku 5.5 with no `temperature`. This deliberately differs from PLAN.md's temperature 0, because Haiku 5.5 returns 400 on a non-default temperature (claude-api model-migration.md:2295). Drop any claim whose quote isn't in the summary | executor (opus) | Unit tests offline; golden set (live, `RUN_LIVE=1`, with Anthony's go on spend) at 9/10, stable across 3 runs | 1 |
| 7 | Verify: `verify.py`. Step 0: chain intact. Step 1: log against DB (`phantom`). Step 2: expected order against actual (`not_done`). Step 3: claims against DB (`false_claim`, `silent_action`). Step 4: rerun the pre-payment checks as of just before the payment (§6a) and compare with the recorded results. Then the verdict. The Stop hook runs extract and verify, then finalizes the receipt; `make receipt` reruns them when Stop didn't fire | executor (opus) | One fixture set per status gives that status; the tampered-log fixture gives `UNTRUSTED` | 5, 6 |
| 8 | Onboarding: SessionStart hook (no `policy.json` → tell Claude to run the onboarding skill; otherwise a short policy summary plus invoices due soon). Onboarding skill: Q&A for threshold, monthly budget, bank floor, approved suppliers (bank account, email domain), tools, external systems; writes `policy.json`. It runs after the SMB plugin's `smb-onboard` and skips what that already asked (Q-smb-onboard) | executor (opus) | In a fresh `CLAUDE_CONFIG_DIR` with the plugin installed, onboarding starts unprompted and writes a policy that validates | 0, 1 |
| 9 | Workflow skills: order, payment, and DB via MCP. Each names which tool to call when, reads back after every write, and never pays an account that differs from the one on file | executor (opus) | A dry run follows each skill to the end; a reviewer confirms every tool it names exists | 0, MCP tool names |
| 10 | Plugin packaging: the manifest, with the SMB plugin in `dependencies` and our `marketplace.json` allowlist (D8). Done-test addition: one `claude plugin install` in a clean config dir installs both plugins; `hooks.json` with `${CLAUDE_PLUGIN_ROOT}`; an install page with the three install steps (D8), the project-settings deny rules on `receipts/**`, `logs/**` and `Bash(sqlite3:*)`, the "don't use bypass-permissions mode" line, and a developer section (SQL, MCP) | executor (opus) | Installs from the repo in a clean config dir; `/plugin` lists it; hooks fire on a stub call | 4–9 |
| 11 | Swap `FixtureSource` for `SqliteSource` on Ronaldo's DB; rerun every test with the real tools; one live run | executor (opus) | The same tests pass on the real DB; the live run gives the expected receipt | DB + MCP |

Tasks 0, 1 and 2 can start now. 4, 5, 6 and 8 run in parallel after 1–2. 3, 9 and 11 wait on the MCP and DB.
As of 14:30 (§0): task 1's receipt schema is merged (PR #2). Task 2's receipt-only checks are on
`feature/payment-checks`, and its reconciliation checks (C7, C8, C10 against `bakery.db`) aren't started. Task 8's
policy questions wait on #9.

**Stop and come back to Anthony** at the first thing that changes this plan:
- Ronaldo's schema differs from §3;
- the tool names don't fit;
- the proxy already blocks calls;
- a contract owner says no in task 1.

## 5 · Checks and their test cases

The checks are deterministic. They read only the policy and the records, through `Source`.

| ID | Check | Runs in | Fails as |
|---|---|---|---|
| C1 | owner approval. Stage 1: every `pay_bill` (D2); the threshold waits on #9 | approval hook | `ask` (human prompt) |
| C2 | month-to-date paid + this payment ≤ monthly budget. **Deferred to #9** | MCP pay tool | block |
| C3 | bank balance − payment ≥ bank floor. **Deferred to #9** | MCP pay tool | block |
| C4 | `to_account` equals the supplier's account on file | MCP pay tool | block |
| C5 | invoice amount equals the order total | MCP pay tool | block |
| C6 | invoice links to a known order from the same supplier | MCP pay tool | block |
| C7 | no live payment exists for this invoice | MCP pay tool | block |
| C8 | invoice sender domain equals the supplier's domain on file (spoofing) | MCP pay tool | block |
| C9 | supplier is on the approved list, and order total ≤ order limit | MCP order tool. **Deferred to #9** | block |
| C10 | after the call, the order and payment rows exist with the logged values | verify | `phantom` |

| Test | Input | Expected |
|---|---|---|
| clean payment | $800 to the account on file, threshold $1,000 | all pass, receipt `VERIFIED` |
| over threshold | $1,500, threshold $1,000 | C1 → `ask` |
| budget exceeded | MTD $4,500 + $800, budget $5,000 | C2 → block |
| below bank floor | balance $1,000 − $800, floor $500 | C3 → block |
| changed account | invoice says ******3210, file says ********4471 | C4 → block |
| amount mismatch | invoice $880, order $800 | C5 → block |
| orphan invoice | invoice with no order | C6 → block |
| double pay | second payment for one invoice | C7 → block |
| spoofed sender | `billing@flourco-payments.example` vs `flourco.example` | C8 → block |
| unapproved supplier | order to a supplier not in the policy | C9 → block |
| dropped write | pay returns ok, no payment row | C10 → `phantom` |
| overclaim | summary "paid Flour Co and Mill Co", one payment row | `false_claim` |
| silent action | payment row the summary never mentions | `silent_action` |
| check crash | policy file missing or corrupt | the tool refuses (fail closed) |

The values above are illustrative. Stage 1 runs no policy checks (D4), so tests on seed data cover C4–C8 and C10 only,
and C1 is `ask` on every payment. BILL-07 as seeded is the clean case; the changed-account and spoofed-sender runs
change its `pay_to_account` or `from_addr` in a test fixture. Names on main: the pay tool is `pay_bill(bill_id, amount_cents, to_account)`, `payments`
keys on `bill_id`, and `orders.status` is `placed`/`received`/`cancelled`. Read `pay_invoice`, `invoice_id` and
`confirmed` in this plan as those. Stored results use the receipt's status names: `verified`, `blocked`,
`needs_approval`, `phantom`.

## 6 · Order receipt JSON (default shape, finalized in task 1)

**Superseded by PR #2** (`docs/mock/order_receipt.schema.json` and `order_receipt.json` on main). Kept below only as
the revision-2 record.

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

Revision 3: stage 1 starts from the seeded order and bill (PO-2041, BILL-07), so it needs no order tool and doesn't
wait on Q-supplier-tools.

1. The owner asks Claude to pay Flour Co's bill. Claude reads it with `list_bills` and calls
   `mcp__bakery-local__pay_bill("BILL-07", 80000, to_account)`.
2. The approval hook returns `ask`, and the owner approves or declines (C1). The pre-payment checks C4, C5, C7 and C8
   run against `bakery.db`, and a failure refuses the payment. Where they're called from is D1, still open.
3. The PostToolUse hook on `pay_bill` creates the receipt for PO-2041 if none exists, then records the payment and each
   check's result. C10 confirms the payment row exists.
4. At Stop, claims are extracted, verify runs `checks/payment.py` and the reconciliation checks, and the receipt gets
   its verdict. The website shows the receipt JSON.

The checks for stage 1: **C1** (owner approves every payment), **C4** (pay-to account matches the one on file), **C5**
(bill amount equals the order), **C7** (no double payment), **C8** (sender domain matches the supplier's), **C10**
(payment row exists). Demo runs: one clean payment (`VERIFIED`), one with the changed account (C4 blocks), one with the
spoofed sender (C8 blocks). For this slice the receipt fills `order`, `bill`, `payment`, `events` (stages from
`bill_received` on), `checks[]` (at least one), `verdict`, `checks_version` and `policy.sha256` (F2 default), plus
`receipt_type`, `receipt_id`, `generated_at` and `business`. Three schema and test rules bind this slice:
- `sessions` needs at least one hash-chain entry (`s1`, `ok`, `entries`, a 64-hex `head`);
- `evidence` is a map with an entry for every ref a check cites;
- `VERIFIED` needs `summary_check.status: "checked"`, so until claims run the verdict is `ISSUES_FOUND`
  (`ledger_problems` in `tests/test_order_receipt.py`).

`read`, `left_business` and `pii` may be empty.

**Check logic never lives in the receipt (13:55).** The receipt stores results; the logic lives only in `checks/`.
- **Each `checks[]` entry:** required `id`, `status`, `lifecycle_stage`, `kind`, `title` and `evidence` (refs shaped
  `s1:log:7`, `inbox:5` or `summary`), plus optional `guard`, `inputs`, `caused_by` and `quote`. `inputs` holds the masked values the check
  compared, e.g. `{"pay_to": "******3210", "on_file": "********4471"}`.
- **`checks_version`:** the git commit of the checks library that ran.
- **`policy.sha256`:** the hash of the policy that ran. Until #9 lands, that's the F2 default: the hash of the seeded `policies` rows.
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
- **Q-supplier-tools (settled 14:40, Anthony):** use a real invoice when there is one, and the order receipt as a
  stand-in until there is. Nobody has to change `place_order`.
  - **If `place_order`'s response carries invoice fields** (amount, due date, sender, pay-to account), they become the
    `bills` row and the receipt's `bill`, with a logged `bill_received` event.
  - **If it doesn't**, the receipt's `bill` is filled from the order response: a new `bill_id` (default
    `BILL-<order id>`), `references_order`, `vendor_id`, and `amount_cents` from `total_cents`. `due_date` is a
    placeholder, the date part of the order's `created_at`. `from` and `received_at` are left out, because no
    supplier sent anything.
  - **The `bills` row behind it (settled 15:00, Anthony):** `pay_bill` needs a `bills` row (`payments.bill_id`
    references `bills.id`). The stand-in row copies what already exists on file: `from_addr` is the vendor's
    `vendors.email` and `pay_to_account` is `vendors.bank_account`. There's no schema change. Empty values
    wouldn't work, because the gate on main (`checks/gate.py`, 347248d) blocks a blank account in C4 and a blank
    sender in C8.
    - Cost: on a stand-in, C8 and the bill half of C4 compare the file with itself, so they pass without proving
      anything. The `pay_bill` `to_account` half of C4 still means something. That's why a stand-in receipt can't be
      `VERIFIED` (below).
    - Still open: which `bakery-local` tool writes the stand-in row. Only the server writes `bakery.db`, and the
      agent has no tool that writes invoices. This goes with F4 (Luke, Owen, Ronaldo).
  - **The receipt shows the stand-in.** The `bill_received` event gets `source: "unverified"`, which the schema
    says the UI marks (Lana to confirm the website does). The schema's `bill` has `additionalProperties: false`, so there's no stand-in flag on the bill
    itself. Empty `from` and `received_at` are the stand-in's signature.
  - **A real invoice replaces the stand-in when it arrives.** That covers a later `place_order` field, an inbox
    message, or a seeded `bills` row. C5 and C8 then rerun against it.
  - **Checks on a stand-in (default):** C5 would compare the order with itself, and C8 has no sender to check. So
    neither may be recorded as `verified`, and the verdict can't be `VERIFIED` while the bill is a stand-in.
    **None of this is enforced yet.** Today a stand-in receipt marked `VERIFIED` passes the schema,
    `xref_problems` and `ledger_problems`. `PAY-BILL-ORDER` passes it, and `PAY-ON-TIME` warns on the placeholder
    due date (reviewer run on `feature/payment-checks`). The work:
    - a `ledger_problems` rule: `VERIFIED` with a `bill_received` event whose `source` is `unverified` is a
      problem;
    - `bill_matches_order` and `paid_on_time` skip when the `bill_received` event is `unverified`, because
      nothing on the bill itself marks a stand-in. Stage 1
    isn't affected: seeded BILL-07 is a real bill with `from_addr` and `pay_to_account` (§6a).
  - Still open: how one order of several SKUs maps to `place_order` calls (F4).
- **Q-smb-onboard:** the SMB plugin's `smb-onboard` saves its business profile to "the Cowork session memory
  directory" (`small-business/skills/smb-onboard/SKILL.md:41`). Where that lands under Claude Code is untested.
  Task 8 must check it, so our onboarding can read the profile and skip questions it already asked.
- **Q-ask-in-server:** default D2 keeps the human prompt in a hook. Alternative: the server refuses any
  over-threshold payment unless the call carries an approval the owner gave. That is Future: it needs auth.
- **Q-policy-seed (settled 14:40, Anthony):** onboarding generates the policies. The demo may use some of their
  values, but mostly they support future functionality.
  - The seeded `policies` rows (7bf070f) stand in for what onboarding would write.
  - Stage 1 enforces none of them, and C1 still asks on every payment (D2).
  - `policy.sha256` hashes the policy rows that exist when the receipt is written (F2).
  - Which values the demo shows, and where (e.g. the website's Policies page on `feat/portal`), is Lana's and
    Anthony's call.
  - Where onboarding stores them stays issue #9.
