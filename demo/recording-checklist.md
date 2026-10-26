# Recording checklist

The video is the backup if the live demo fails, and it may be what judges watch. Budget 35 minutes for it: two takes and a quick edit. Target length 3:00, never over.

## Before recording

- [ ] Everything you need has been merged into `main` and pulled. Don't record from an unmerged branch.
- [ ] `make reset` has run, so the database starts clean and the log is empty.
- [ ] `claude plugin list` shows `ledgers-receipts@the-ledgers` and `small-business@knowledge-work-plugins` enabled (steps in the README, "Install the plugin").
- [ ] Claude was started from inside this repo folder, so it loads `CLAUDE.md` and the hooks.
- [ ] Terminal font is large enough to read at 720p. Close other windows and turn off notifications.
- [ ] Nothing private is on screen: no API keys, no email inbox, no browser tabs, and no WiFi password or door code from the whiteboard photo.
- [ ] Only use the seeded Sweet Rose Bakery data and `*.example` addresses.

## Shot list

Follow `storyboard.md`. Each scene is one continuous shot unless noted.

| Scene | Time | Shot | If it goes wrong |
| --- | --- | --- | --- |
| 1 | 0:00 | Three slides, one line each | Read it from the storyboard |
| 2 | 0:20 | Terminal: the three `claude plugin` commands, then the onboarding questions. Record once and speed up | Show `claude plugin list` only |
| 3 | 0:40 | Ask Claude to pay Flour Co's bill. It reads BILL-07 ($800.00, PO-2041) | Use the sample receipt in `docs/mock/order_receipt.json` |
| 4 | 1:00 | Inbox with the bank-change email (account ending 3210) | Same |
| 5 | 1:15 | `pay_bill` to the account ending 3210 is blocked. Zoom on 3210 vs 4471 | Show the check result from `python -m checks.evaluate` (after #18 merges) |
| 6 | 1:40 | Claude's summary against the database record | Use a fixture summary |
| 7 | 2:05 | The receipt: "ISSUES FOUND" and the owner action | Render the sample receipt |
| 8 | 2:30 | Edit one log line and rerun: "UNTRUSTED" | Skip it, and give the time to scene 7 |
| 9 | 2:45 | The three points, one per line, then the name | Same |

## Fallback if the live path isn't ready at the freeze

Record scenes 1, 2 and 9 as planned. For 3 to 7, show the sample receipt in `docs/mock/` and say plainly that it's a pre-generated example. Never show something as live that isn't.

## After recording

- [ ] Watch it once at full speed. Is any text unreadable? Is anything private visible?
- [ ] Trim dead air. Check the length is 3:00 or less.
- [ ] Save the file outside git. Put the link in `assets/README.md`.
- [ ] Keep the raw take until the event is over.
