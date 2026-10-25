# Submission: Receipts, by The Ledgers

*Working name, still to be agreed by the team.*
Built at the Claude Impact Lab Hackathon, Seattle, October 2026.

## One line

Receipts makes an AI agent's work auditable: every action is logged, risky actions are blocked before they run, and plain code checks the agent's story against the real records.

## Who it's for

Small business owners who hand money tasks, like paying a supplier's bill or chasing an invoice, to an AI agent.

## The problem

Owners can't tell whether the agent did the job right or got tricked. In our event survey of small business owners, 16 of 38 named privacy and security as a barrier, and 13 of 38 said AI output is unreliable. Those who tried agents went back to approving every step, because checking the AI cost more than it saved.

## How Receipts solves it

1. **Every action is logged.** Each tool call goes into a tamper-evident hash chain, with personal data masked.
2. **Risky actions are blocked before they run.** Checks compare a payment with the records first: the account on file, the amounts on the order and the bill, double payments, and the sender's domain.
3. **Code checks the work, not the AI.** The agent's summary is compared with the database. The owner gets a one-page receipt that says what really happened and what to do next.

## The demo story

Sweet Rose Bakery asks Claude to pay Flour Co's $800.00 bill (order PO-2041). An email claims Flour Co's bank changed. Receipts blocks the payment because the new account (ending 3210) doesn't match the one on file (ending 4471), and the receipt tells the owner to call Flour Co on a number they already have. Full storyboard: [`storyboard.md`](storyboard.md).

## Getting started

The owner installs it with three `claude plugin` commands and answers a few onboarding questions: tools, the approval threshold, the monthly budget, and approved suppliers (last 4 digits of the account only). Steps are in the README.

## What's built, and what isn't

| Piece | Status |
| --- | --- |
| Hash-chained log and personal-data masking | Merged |
| Plugin, install steps, onboarding skill | Merged |
| Order receipt format, with samples and tests | Merged |
| Payment-stage checks | Merged. The pre-payment checks C4 to C8 are in an open PR |
| BakeSupply, a mock supplier MCP server | Merged |
| Bakery MCP server | Built, on a branch, not merged |
| Owner portal (website) | Open PR |
| Approval hook, claim extraction and the verifier | In progress or not started. We haven't completed the end-to-end run |

We'd rather say that plainly than overstate it. The receipt shown in the demo material is a sample.
