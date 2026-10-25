---
name: onboarding
description: Set up Receipts for a small business. Asks the owner which bookkeeping, payment and email tools they use and what their payment rules are, then saves the answers to receipts-onboarding.json. Use when the session says Receipts isn't set up for this business, when the owner asks to set up or change Receipts, or right after the Small Business plugin's smb-onboard finishes.
---

# Receipts onboarding

Ask the owner a few questions and save the answers to `receipts-onboarding.json` in the project
folder. Today the file is a record for later: no check reads it yet, and where payment rules
finally live is still being decided. Say that to the owner in one sentence before you start, so
they know why you're asking.

## Before you ask

- If the session already holds a `## Business context` block from the Small Business plugin's
  `smb-onboard`, reuse what it answered (its **Business** one-liner and **Connected tools**).
- If `receipts-onboarding.json` already exists, read it, show the owner what's saved, and ask
  only what they want to change.
- Drop any question below that one of these already answers. If a round has nothing left to
  ask, skip it.

## Round 1: tools (one AskUserQuestion call, up to three questions)

Ask the remaining questions in a single AskUserQuestion call. List options alphabetically; the
owner can pick "Other" to name a different tool. Set `multiSelect: true` on Payments, since a
business can use more than one; the other two are single choice.

| Header | Question | Options |
|---|---|---|
| Bookkeeping | Which bookkeeping software do you use? | QuickBooks · Xero · Zoho Books · None, I use a spreadsheet |
| Payments | How do you pay suppliers or take payments? | PayPal · Square · Stripe · Bank transfer only |
| Email | Where do supplier invoices arrive? | Gmail · Microsoft 365 (Outlook) |

These cover the demo flow: an order, the supplier's invoice by email, and the payment. Don't walk
through every tool the Small Business plugin supports. If the owner names a tool that isn't
connected yet, note it and say that `smb-onboard` can connect it later.

## Round 2: payment rules (one message)

Ask these together in one plain message, and accept short answers. Start the message with:
"For bank accounts, type only the last 4 digits, never the full number."

1. What's the name of your business? (Skip if you already know it.)
2. Payments above what amount should need your written approval? Default: $1,000.
3. What's your monthly budget for supplies? "No limit" is fine.
4. Which suppliers do you pay? For each one: the name, their email domain, and the **last 4
   digits** of the bank account you pay them at.

Never ask for, repeat or save a full account, card or IBAN number. If the owner types one, keep
only the last 4 digits, tell them you did, and say the full number stays in this chat's history.

## How answers are stored

- Each tool answer is stored as the option's label, or the owner's own words for "Other".
  Payments is a list. Tools the owner mentions beyond these questions go in `other`.
- "None, I use a spreadsheet" and "Bank transfer only" are stored as those labels.
- "No limit" for the budget is stored as `null` in `monthly_budget_cents`.

## Save the answers

Show the owner what you're about to save and wait for their yes. Then write
`receipts-onboarding.json` in the project folder with the Write tool, in this shape (money in
integer cents, unknown values as `null`):

```json
{
  "schema": "receipts-onboarding/0",
  "status": "stub",
  "created_at": "2026-10-25T15:00:00-07:00",
  "business": {"name": "Sweet Rose Bakery", "from_smb_onboard": true},
  "integrations": {"bookkeeping": "QuickBooks", "payments": ["Square"], "email": "Gmail", "other": []},
  "payment_rules": {
    "approval_threshold_cents": 100000,
    "monthly_budget_cents": 300000,
    "approved_suppliers": [
      {"name": "Flour Co", "email_domain": "flourco.example", "account_last4": "4471"}
    ]
  }
}
```

End by telling the owner, in plain words, what was saved. Be exact about what is enforced today:
payments over $1,000 ask for their approval, whatever threshold they chose. The threshold they
gave is saved for later and not used yet.
