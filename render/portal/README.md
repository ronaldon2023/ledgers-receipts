# Owner portal

The website the bakery owner uses: **Dashboard** (at a glance, needs your attention),
**Activities** (everything Claude did, by time or by order) and **Policies**, plus one
**Order receipt** page per order.
Claude does the work; plain code decides every status. The portal only renders JSON.

```sh
python -m render.portal          # opens http://127.0.0.1:8000/
```

Add `?state=pending|stopped|paid|declined` to the URL to jump to a demo state.
"Restart demo" goes back to `pending`.

## Data (`fixtures/portal/`, served at `/data/`)

| File | What it is |
| --- | --- |
| `receipt_PO-2041_<state>.json` | The order's one receipt as it stands in each demo state (main's schema: created at submit, updated each step). `stopped` is `docs/mock/order_receipt.json` unchanged |
| `feed_<state>.json` | **Proposed, not a team contract yet.** The running list the dashboard needs: attention cards, events, steps with timestamps, glance numbers, orders |
| `policies.json` | Policies page. ids, kinds, titles and limits match `POLICIES` in `bakery/seed.py` |

Receipts are validated against `docs/mock/order_receipt.schema.json` on main, so a schema
change breaks `tests/test_portal.py` instead of drifting. The proposed restock order
(`PO-2042`, cane sugar) is priced with BakeSupply's MCP tools (`list_products`, `get_price`),
which play Flour Co. It has no receipt until it is submitted.

## Rules this code keeps

- Every value from data goes through `Portal.esc()`; links from data must start with `#`.
- Masked account numbers (`******3210`) display as `••••3210`.
- The server only exposes this folder and `fixtures/portal/`, on 127.0.0.1.
- `tests/test_portal.py` runs `portal.js` in Node. Without Node those tests skip and pytest
  prints a warning.
