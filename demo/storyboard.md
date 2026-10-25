# Receipts demo storyboard

Receipts makes an AI agent's work auditable. The pitch follows one bakery order, PO-2041 for $800.00.
Run it in replay mode so the guard and the false-claim scenes happen every time. A live run is a bonus.

**For:** small business owners who hand money tasks to an AI agent.
**Three points to leave them with:**

1. Every action is logged.
2. Risky actions are blocked before they run.
3. Code checks the work, not the AI.

## Scenes (3:00)

| # | Time | Scene | On screen | What we say |
| --- | --- | --- | --- | --- |
| 1 | 0:00 | Who, problem, fix | Three slides: "Small bakery owners", "Can't trust an AI agent's work", "Receipts checks it for them" | Owners are handing money tasks to AI agents and can't tell if the agent did it right or got tricked. Receipts logs every action, blocks risky ones before they run, and checks the agent's story against the real records. |
| 2 | 0:20 | Setting it up | Screen recording, sped up: install the plugin, answer a few questions (payment limit, tools, outside systems), Receipts is on | An owner installs the plugin and answers a few plain questions. From then on everything the agent does is logged and checked. |
| 3 | 0:40 | Claude places the order | Claude orders 12 bags of all-purpose flour and 4 of bread flour from Flour Co. Receipt stages "order placed" and "order sent" turn green | The AI does the work. Every call is logged. |
| 4 | 1:00 | The bill arrives | Two emails from Flour Co: bill BILL-07 for $800.00, and "our bank changed, pay the account ending 3210" | The bill comes in, and so does a request to pay a different account. |
| 5 | 1:15 | The guard stops it | `pay_bill` for $800.00 to the account ending 3210 is blocked. The account on file ends 4471 | Code checked the account against the record before any money moved. |
| 6 | 1:40 | Claude's summary | Claude says "Paid the Flour Co bill". The database shows 0 payments for BILL-07: false claim | The AI said it was done. The record says no. The AI never grades itself. |
| 7 | 2:05 | The receipt | "ISSUES FOUND" banner, then "Call Flour Co on the number you already have to confirm their bank account" | An owner reads this in ten seconds and knows what to do next. |
| 8 | 2:30 | The tamper test | Edit one amount in the log, rerun: the banner turns dark red, "UNTRUSTED" | Change one log line and the hash chain breaks. |
| 9 | 2:45 | Close | The three points, one per line, then the project name | Everything logged, risky actions blocked, work checked by code. |

Scenes 5 and 6 are the ones that must never fail.

## What each scene needs

| Scene | Depends on |
| --- | --- |
| 2 | Onboarding skill with its hook trigger, plugin install (exact steps to confirm) |
| 3 | BakeSupply server (PR #4), logging hook |
| 4 | Seeded inbox in `bakery/seed.py` |
| 5 | Guard hook, `pay_bill` on the bakery server |
| 6 | Claim extractor (fixture claims for replay), verifier |
| 7 | Receipt page, `receipt.json` |
| 8 | Hash chain, an untrusted-log fixture |
| 1, 9 | Slide deck (no owner yet) |

## To settle

- **One story.** `docs/PLAN.md` still describes chasing three invoices plus a bill. This storyboard follows the order receipt in `docs/mock/order_receipt.json`.
- **PO numbers.** BakeSupply returns `ord_1` while the bakery calls the order PO-2041. An optional PO number on the order call would tie them together on the receipt.
- **Audience.** If the judges are investors or security people, rewrite scene 1 to name them.
- **Say-it-back test.** Read scene 1 to someone outside the team. If they can't repeat what Receipts does, simplify.

## If time runs short

Cut the bounce fault, then the link from each action to the email that caused it, then the live claim extractor. Never cut the guard, the hash chain or the replay test. Stop adding features an hour before the demo, rehearse twice, and record the backup video.
