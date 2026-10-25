# Owner portal

The website the bakery owner uses: **Dashboard** (needs your attention, at a glance),
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
| `receipt_PO-2041_1.json` | Anthony's order receipt sample (PR #2), unchanged: the stopped payment |
| `receipt_PO-2041_2.json` | Same order after paying the account on file; `supersedes` the first |
| `order_receipt.schema.json` | Copy of the schema from PR #2. Replace with `contracts/` once promoted |
| `feed_<state>.json` | **Proposed, not a team contract yet.** The running list the dashboard needs: attention cards, events, steps with timestamps, glance numbers, orders |
| `policies.json` | Policies page. ids, titles and limits match `receipt.policies` |

The BakeSupply order (`BS-1`) uses the tool names and fields of Owen's BakeSupply MCP
(PR #4). It has no receipt yet: the receipt schema needs a bill and a vendor on file.

## Rules this code keeps

- Every value from data goes through `Portal.esc()`; links from data must start with `#`.
- Masked account numbers (`******3210`) display as `••••3210`.
- The server only exposes this folder and `fixtures/portal/`, on 127.0.0.1.
- `tests/test_portal.py` runs `portal.js` in Node (skipped if Node isn't installed).
