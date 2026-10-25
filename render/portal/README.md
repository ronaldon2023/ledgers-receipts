# Owner portal

The website the bakery owner uses: **Dashboard** (summary tiles, needs your attention),
**Activities** (everything Claude did, by time or by order) and **Policies**, plus one
**Order receipt** page per order.
Claude does the work; plain code decides every status. The portal only renders JSON.

```sh
python -m render.portal          # opens http://127.0.0.1:8000/
```

Add `?state=pending|stopped|paid|declined` to the URL to jump to a demo state.

`?state=live` shows a real run: after Claude works, `python -m receipts.verify` writes `feed_live.json` and `receipt_live_<order>.json` here from the log and `bakery.db` (git-ignored).
"Restart demo" goes back to `pending`.

## Data (`fixtures/portal/`, served at `/data/`)

| File | What it is |
| --- | --- |
| `receipt_PO-2041_<state>.json` | The order's one receipt as it stands in each demo state (main's schema: created at submit, updated each step). `stopped` is `docs/mock/order_receipt.json` unchanged |
| `feed_<state>.json` | **Proposed, not a team contract yet.** The running list the dashboard needs: attention cards, events, steps with timestamps, glance numbers, orders |
| `policies.json` | Policies page. ids, kinds, titles and limits match `POLICIES` in `bakery/seed.py` |

Receipts are validated against `docs/mock/order_receipt.schema.json` on main, so a schema
change breaks `tests/test_portal.py` instead of drifting. The dashboard's **weekly
inventory check** card shows off BakeSupply's MCP server (which plays Flour Co): Start check
reveals `list_products` and `get_price` steps and a restock proposal (`PO-2042`, cane sugar);
approving it adds `place_order` and `list_orders`. The run is simulated from fixture data:
items tagged `requires` stay hidden until the owner clicks the card that produces them.

## Saving the owner's rules

The onboarding "Your rules" step saves through `POST /api/onboarding` into
`receipts-onboarding.json` in the business folder (`--business-dir`, or the folder you start the
portal from): the same file Claude Code's onboarding skill writes and the approval hook reads.
Only `payment_rules` is replaced; the rest of an existing file is kept. Only the portal page's
own origin may save, and every value is checked (`render/portal/rules.py`).

## Rules this code keeps

- Every value from data goes through `Portal.esc()`; links from data must start with `#`.
- Masked account numbers (`******3210`) display as `••••3210`.
- The server only exposes this folder and `fixtures/portal/`, on 127.0.0.1.
- `tests/test_portal.py` runs `portal.js` in Node. Without Node those tests skip and pytest
  prints a warning.
