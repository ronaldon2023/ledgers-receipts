"""Owner portal: fixtures match the receipt schema, and portal.js renders them safely.

The rendering tests run render/portal/portal.js in Node, the same code the browser runs.
"""

import copy
import json
import re
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from bakery.seed import POLICIES
from render.portal.__main__ import resolve

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "fixtures" / "portal"
JS = ROOT / "render" / "portal" / "portal.js"
STATES = ["pending", "stopped", "paid", "declined"]
# The team's schema on main: if it changes, these tests break instead of drifting silently.
SCHEMA = json.loads((ROOT / "docs" / "mock" / "order_receipt.schema.json").read_text())
SAMPLE = json.loads((ROOT / "docs" / "mock" / "order_receipt.json").read_text())
XSS = "<script>alert(1)</script>"
# The owner has clicked "Start check" on the weekly inventory card.
CHECKED = {"ran": {"att_inventory": True}, "dismissed": {"att_inventory": True}}

NO_NODE = shutil.which("node") is None
if NO_NODE:
    warnings.warn(
        "Node.js is not installed: the portal rendering tests in test_portal.py are SKIPPED. "
        "Install Node (https://nodejs.org) to run them.",
        stacklevel=1,
    )
needs_node = pytest.mark.skipif(NO_NODE, reason="needs Node.js to run portal.js")

HARNESS = """
const vm = require("vm"), fs = require("fs");
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const jobs = JSON.parse(fs.readFileSync(0, "utf8"));
const out = jobs.map(j => j.maps ? {CHECK: ctx.Portal.CHECK, RESULT: ctx.Portal.RESULT, LEVEL: ctx.Portal.LEVEL}
  : ctx.Portal.page(j.data, j.ui));
process.stdout.write(JSON.stringify(out));
"""


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def data(state: str) -> dict:
    feed = load(f"feed_{state}.json")
    receipt = load(feed["receipt"]) if feed["receipt"] else None
    return {"feed": feed, "receipt": receipt, "policies": load("policies.json")}


def run(jobs: list[dict]) -> list:
    proc = subprocess.run(
        ["node", "-e", HARNESS, str(JS)],
        input=json.dumps(jobs),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def page(d: dict, view: str = "dashboard", **ui) -> str:
    out = run([{"data": d, "ui": {"view": view, "filter": "all", "feedView": "time", **ui}}])[0]
    return out["side"] + out["main"]


# ---------- fixtures ----------


@pytest.mark.parametrize("state", STATES)
def test_receipts_match_schema(state: str) -> None:
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    receipt = load(f"receipt_PO-2041_{state}.json")
    assert [e.message for e in validator.iter_errors(receipt)] == []
    assert receipt["receipt_id"] == SAMPLE["receipt_id"]  # one receipt per order, updated in place


def test_stopped_receipt_is_mains_sample() -> None:
    mine = load("receipt_PO-2041_stopped.json")
    assert {k: v for k, v in mine.items() if k != "$schema"} == {
        k: v for k, v in SAMPLE.items() if k != "$schema"
    }


def test_policies_match_seed() -> None:
    mine = sorted(
        (p["id"], p["kind"], p["title"], p.get("limit_cents"))
        for p in load("policies.json")["policies"]
    )
    assert mine == sorted(POLICIES)


@pytest.mark.parametrize("state", STATES)
def test_feed_references_resolve(state: str) -> None:
    feed = load(f"feed_{state}.json")
    ids = [s["id"] for s in feed["steps"]]
    assert len(ids) == len(set(ids))
    for thing in feed["events"] + feed["attention"]:
        assert set(thing["steps"]) <= set(ids), thing["id"]
    orders = {o["order_number"] for o in feed["orders"]}
    assert {e["order"] for e in feed["events"] if e["order"]} <= orders
    if feed["receipt"]:
        assert (DATA / feed["receipt"]).is_file()


def test_no_unmasked_numbers_in_fixtures() -> None:
    for path in DATA.glob("*.json"):
        text = re.sub(r'"head": "[0-9a-f]{64}"', "", path.read_text())
        assert not re.search(r"\d{8,}", text), path.name


def test_server_serves_only_portal_files() -> None:
    assert resolve("/") == ROOT / "render" / "portal" / "index.html"
    assert resolve("/data/feed_pending.json") == DATA / "feed_pending.json"
    assert resolve("/data/../../bakery/seed.py") is None
    assert resolve("/../bakery.db") is None
    assert resolve("/__main__.py") is None


# ---------- rendering ----------


@needs_node
def test_every_state_and_view_renders() -> None:
    jobs = []
    for state in STATES:
        d = data(state)
        for view in ["dashboard", "activities", "policies", "order/PO-2041", "order/PO-2042"]:
            for feed_view in ["time", "order"]:
                ui = {"view": view, "filter": "all", "feedView": feed_view}
                jobs.append({"data": d, "ui": ui})
    for out in run(jobs):
        assert "<h1>" in out["main"]


@needs_node
def test_status_maps_cover_schema_and_fixtures() -> None:
    maps = run([{"maps": True}])[0]
    statuses = SCHEMA["properties"]["checks"]["items"]["properties"]["status"]["enum"]
    assert set(maps["CHECK"]) - {"_unknown"} == set(statuses)
    labels = [v[0] for k, v in maps["CHECK"].items() if k not in ("_unknown", "false_claim")]
    assert len(labels) == len(set(labels))
    for state in STATES:
        feed = load(f"feed_{state}.json")
        assert {s["result"] for s in feed["steps"]} <= set(maps["RESULT"])
        assert {e["level"] for e in feed["events"] + feed["attention"]} <= set(maps["LEVEL"])


@needs_node
def test_unknown_status_renders_as_unknown() -> None:
    d = data("stopped")
    d["receipt"]["checks"][0]["status"] = "constructor"
    d["receipt"]["verdict"] = "SOMETHING_NEW"
    d["feed"]["events"][0]["level"] = "brand_new"
    html = page(d, "order/PO-2041") + page(d, "activities")
    assert html.count(">Unknown<") >= 3


@needs_node
def test_data_is_escaped() -> None:
    d = copy.deepcopy(data("stopped"))
    stopped = next(c for c in d["feed"]["attention"] if c["id"] == "att_stopped")
    d["feed"]["events"][0]["title"] = XSS
    stopped["quote"]["text"] = XSS
    d["feed"]["steps"][0]["quote"] = XSS
    d["receipt"]["checks"][0]["title"] = XSS
    d["policies"]["policies"][0]["title"] = XSS
    stopped["actions"][1]["href"] = "javascript:alert(1)"
    html = "".join(page(d, v) for v in ["dashboard", "activities", "order/PO-2041", "policies"])
    assert "<script" not in html
    assert "javascript:" not in html
    assert "&lt;script&gt;" in html


@needs_node
def test_bank_numbers_show_last_four_only() -> None:
    for state in STATES:
        html = "".join(
            page(data(state), v) for v in ["dashboard", "activities", "order/PO-2041", "policies"]
        )
        assert not re.search(r"\d{5,}", html)
        assert not re.search(r"\*{4,}\d{4}", html)
        assert "••••4471" in html


@needs_node
def test_by_order_groups_each_order() -> None:
    html = page(data("stopped"), "activities", feedView="order", **CHECKED)
    po, restock, other = (
        html.index(s) for s in ["Order PO-2041", "Order PO-2042", "Not tied to an order"]
    )
    assert po < restock < other
    for title in ["Bill BILL-07 from Flour Co arrived", "Payment of $800.00 to Flour Co stopped"]:
        assert po < html.index(title) < restock
    assert restock < html.index("Claude asks to order 3 bags of cane sugar") < other
    assert other < html.index("Email to billing-help@outside.example stopped")


@needs_node
def test_policies_page_shows_rules_only() -> None:
    html = page(data("stopped"), "policies")
    for p in load("policies.json")["policies"]:
        assert p["title"] in html
    assert not re.search(r'class="b b-', html)


@needs_node
def test_approval_card_has_no_check_list() -> None:
    html = page(data("pending"))
    card = html[html.index('<article class="card ask">') :]
    card = card[: card.index("</article>")]
    assert 'class="checks"' not in card
    assert "Approve with passkey" in card


@needs_node
def test_stopped_trail_shows_pay_bill_then_guard() -> None:
    html = page(data("stopped"))
    card = html[html.index('<article class="card stop">') :]
    card = card[: card.index("</article>")]
    flag, call, guard = (
        card.index(s) for s in ["chk_5", "pay_bill · bill=BILL-07", "Guard: the account"]
    )
    assert flag < call < guard
    assert card.index(">Blocked<") > call


@needs_node
def test_restock_order_card_needs_approval() -> None:
    html = page(data("pending"), **CHECKED)
    start = html.index("Order 3 bags of cane sugar from Flour Co")
    card = html[html.rindex("<article", 0, start) : html.index("</article>", start)]
    assert 'class="card ask"' in card
    assert 'class="checks"' not in card
    assert "Steps Claude took (6)" in card
    assert "bakesupply.get_price · sku=SUG-CN-50 · quantity=3" in card
    assert "Approve with passkey" in card and "Decline" in card
    tile = html[html.index("Waiting on you") :]
    assert tile.startswith('Waiting on you</span><span class="n">2<')
    assert "Sugar order, $120.00" in tile


@needs_node
def test_dismissed_card_leaves_waiting_count() -> None:
    html = page(data("declined"), dismissed={"att_order": True})
    assert "Order 3 bags of cane sugar from Flour Co" not in html
    assert 'Waiting on you</span><span class="n">0<' in html


@needs_node
def test_activities_have_their_own_page() -> None:
    dash, acts = page(data("stopped")), page(data("stopped"), "activities")
    assert 'class="feed"' not in dash and 'href="#activities"' in dash
    assert 'class="feed"' in acts and "Needs your attention" not in acts
    assert '<a href="#activities" aria-current="page">Activities</a>' in acts


@needs_node
def test_approval_cards_have_no_status_line() -> None:
    html = page(data("pending"), **CHECKED)
    attn = html[html.index("Needs your attention") :]
    assert attn.count('<article class="card ask">') == 2
    assert 'class="metaRow"' not in attn
    stopped = page(data("stopped"))
    assert '<span class="b b-stop">Stopped</span>' in stopped
    assert "<b>Ledger</b>" in html


INSTALL_PR7 = [
    "/plugin marketplace add anthropics/knowledge-work-plugins",
    "/plugin marketplace add ronaldon2023/ledgers-receipts",
    "/plugin install ledgers-receipts@the-ledgers",
]


def onboarding(step: int, rules: dict | None = None) -> dict:
    out = run(
        [
            {
                "data": data("pending"),
                "ui": {"view": "onboarding", "onboard": {"step": step, "rules": rules}},
            }
        ]
    )
    return out[0]


@needs_node
def test_onboarding_steps_render_without_sidebar_links() -> None:
    titles = ["Sign in with your passkey", "Connect Claude Code", "Your rules", "You're set"]
    for step, title in enumerate(titles):
        out = onboarding(step)
        assert title.replace("'", "&#39;") in out["main"]
        assert out["side"] == ""
        assert f"step {step + 1} of 4" in out["main"]


@needs_node
def test_onboarding_install_commands_match_plugin_pr() -> None:
    html = onboarding(1)["main"]
    positions = [html.index(f"<code>{c}</code>") for c in INSTALL_PR7]
    assert positions == sorted(positions)
    assert "<code>claude</code>" in html


@needs_node
def test_onboarding_rules_default_from_policies_and_escape_input() -> None:
    html = onboarding(2)["main"]
    assert 'value="Flour Co"' in html
    assert 'id="r-threshold" type="number" min="0" step="1" inputmode="numeric" value="500"' in html
    rules = {
        "suppliers": XSS,
        "threshold_cents": 50000,
        "budget_cents": 300000,
        "floor_cents": 200000,
    }
    done = onboarding(3, rules)["main"] + onboarding(2, rules)["main"]
    assert "<script" not in done
    assert "Anything over $500" in done


@needs_node
def test_by_order_is_first_and_default_and_time_moved_to_sidebar() -> None:
    out = run([{"data": data("stopped"), "ui": {"view": "activities", "filter": "all"}}])[0]
    html = out["main"]
    assert html.index('data-feedview="order"') < html.index('data-feedview="time"')
    assert 'data-feedview="order" aria-pressed="true"' in html
    assert "Not tied to an order" in html
    dash = page(data("stopped"))
    assert "Claude is working on your bills" not in dash
    meta = out["side"][out["side"].index('class="meta"') :]
    assert meta.index("Sun 25 Oct · 2:02 PM") < meta.index("Agent: Claude")


@needs_node
def test_every_page_has_a_start_onboarding_button() -> None:
    for view in ["dashboard", "activities", "policies", "order/PO-2041"]:
        assert (
            '<button type="button" class="btn" data-onb="again">Start onboarding</button>'
            in page(data("stopped"), view)
        )


@needs_node
def test_receipt_page_follows_mains_receipt() -> None:
    for state in STATES:
        html = page(data(state), "order/PO-2041")
        assert html.index('href="#dashboard">← Back to dashboard</a>') < html.index("<h1>")
        assert html.count("<li><b>") >= 6  # one stage per event
        assert "Approvals" not in html and "Replaces receipt" not in html
    assert "hasn't written its summary yet" in page(data("pending"), "order/PO-2041")
    assert ">Rerun differs<" in page(_with_status("rerun_mismatch"), "order/PO-2041")


def _with_status(status: str) -> dict:
    d = copy.deepcopy(data("stopped"))
    d["receipt"]["checks"][0]["status"] = status
    return d


@needs_node
def test_glance_comes_before_attention() -> None:
    html = page(data("pending"))
    assert html.index('class="glance"') < html.index("Needs your attention")
    assert ">At a glance<" not in html


@needs_node
def test_glance_tiles_drop_budget_left_and_balance_note() -> None:
    html = page(data("pending"))
    assert "98% used</span>" in html
    assert " left</span>" not in html
    assert "Floor $2,000" not in html and "if BILL-07 is paid" not in html


@needs_node
def test_rules_step_has_no_notes() -> None:
    html = onboarding(2)["main"]
    assert 'class="muted small"' not in html
    assert 'class="note"' not in html
    assert "Separate names with commas" not in html


@needs_node
def test_demo_buttons_sit_in_sidebar_above_the_date() -> None:
    out = run([{"data": data("pending"), "ui": {"view": "dashboard", "filter": "all"}}])[0]
    side = out["side"]
    assert (
        side.index(">Start onboarding<") < side.index(">Restart demo<") < side.index("Sun 25 Oct")
    )
    assert "Start onboarding" not in out["main"] and "Restart demo" not in out["main"]
    assert "Run setup again" not in side


@needs_node
def test_inventory_check_card_comes_first_and_reveals_the_order() -> None:
    before = page(data("pending"))
    attn = before[before.index("Needs your attention") :]
    assert attn.index("Start this week&#39;s inventory check") < attn.index("Pay Flour Co $800.00")
    assert ">Start check<" in attn and ">Not now<" in attn
    assert "cane sugar" not in before
    after = page(data("pending"), **CHECKED)
    assert "Start this week&#39;s inventory check" not in after
    assert "Order 3 bags of cane sugar from Flour Co" in after


@needs_node
def test_approving_the_restock_shows_every_bakesupply_tool() -> None:
    ran = {"att_inventory": True, "att_order": True}
    html = page(data("pending"), "order/PO-2042", ran=ran, dismissed=ran)
    tools = ["list_products", "get_price", "place_order", "list_orders"]
    positions = [html.index("bakesupply." + t) for t in tools]
    assert positions == sorted(positions)
    acts = page(data("pending"), "activities", ran=ran, dismissed=ran)
    assert "Ordered 3 bags of cane sugar from Flour Co, $120.00" in acts
    assert '<span class="b b-mute">Answered</span>' in acts


@needs_node
def test_declining_the_restock_places_nothing() -> None:
    d = {"att_inventory": True, "att_order": True}
    html = page(data("pending"), "activities", ran={"att_inventory": True}, dismissed=d)
    assert "bakesupply.place_order" not in html
    assert "You declined" in html


@needs_node
def test_start_check_shows_the_mcp_running() -> None:
    running = {"card": "att_inventory", "action": 0, "step": 1}
    html = page(data("pending"), running=running)
    card = html[html.index("Start this week&#39;s inventory check") :]
    card = card[: card.index("</article>")]
    assert 'role="status" aria-live="polite"' in card
    assert "Running the check through the BakeSupply MCP…" in card
    assert card.index("<code>inventory</code>") < card.index(
        "<code>bakesupply.list_products</code>"
    )
    assert (
        '<li class="done">' in card and '<li class="now">' in card and '<li class="todo">' in card
    )
    assert ">Start check<" not in card


@needs_node
def test_running_labels_are_escaped() -> None:
    d = copy.deepcopy(data("pending"))
    action = d["feed"]["attention"][0]["actions"][0]
    action["running"] = XSS
    action["progress"][0]["label"] = XSS
    html = page(d, running={"card": "att_inventory", "action": 0, "step": 0})
    assert "<script" not in html


@needs_node
def test_finished_check_dissolves_and_order_card_appears() -> None:
    leaving = page(
        data("pending"),
        running={"card": "att_inventory", "action": 0, "step": 4},
        leaving="att_inventory",
    )
    assert '<article class="card  leaving">' in leaving
    entering = page(data("pending"), entering={"att_order": True}, **CHECKED)
    assert '<article class="card ask entering">' in entering


@needs_node
def test_onboarding_uses_a_stepper() -> None:
    html = onboarding(1)["main"]
    stepper = html[html.index('<ol class="stepper"') : html.index("</ol>")]
    assert stepper.count("<li ") == 4
    assert '<li class="done"><span class="num" aria-hidden="true">✓</span>' in stepper
    assert (
        '<li class="on" aria-current="step"><span class="num" aria-hidden="true">2</span>'
        in stepper
    )
    assert stepper.count('<li class="todo">') == 2
    assert 'class="stages"' not in html


@needs_node
def test_youre_set_lists_items_vertically() -> None:
    html = onboarding(3)["main"]
    assert html.count('<ol class="summary"><li><b>Claude does the work</b>') == 1
    assert html.count("<li><b>") == 4
    assert 'class="quote"' not in html


@needs_node
def test_bill_card_has_no_subtitle() -> None:
    html = page(data("pending"))
    card = html[html.index("Pay Flour Co $800.00 for bill BILL-07") :]
    card = card[: card.index("</article>")]
    assert 'class="muted"' not in card
    assert "16 bags of flour · due" not in card


@needs_node
def test_paid_state_summary_card_is_past_tense() -> None:
    html = page(data("paid"))
    assert "Claude says Flour Co was paid. It wasn&#39;t." not in html
    assert "said Flour Co was paid before it was" in html
    assert "Don&#39;t tell Flour Co" not in html


@needs_node
def test_decline_asks_before_acting() -> None:
    html = page(data("pending"), confirming={"card": "att_approve", "action": 1})
    card = html[html.index("Pay Flour Co $800.00 for bill BILL-07") :]
    card = card[: card.index("</article>")]
    assert "<strong>Decline this payment?</strong>" in card
    assert 'data-act="passkey" data-card="att_approve">Decline</button>' in card


@needs_node
def test_needs_action_matches_open_cards() -> None:
    html = page(data("stopped"), "activities", filter="action")
    for title in [
        "Payment of $800.00 to Flour Co stopped",
        "Claude&#39;s summary said Flour Co was paid",
    ]:
        assert title in html
    assert "Email to billing-help@outside.example stopped" not in html
    done = page(data("stopped"), "activities", filter="action", dismissed={"att_mismatch": True})
    assert "Claude&#39;s summary said Flour Co was paid" not in done


@needs_node
def test_order_page_details_from_review() -> None:
    proposed = page(data("pending"), "order/PO-2042", **CHECKED)
    assert "· proposed Sun 25 Oct" in proposed and "· placed" not in proposed
    receipt = page(data("stopped"), "order/PO-2041", **{"from": "activities"})
    assert '<details class="steps"><summary>Steps Claude took on this order (' in receipt
    assert '<a href="#activities" aria-current="page">' in receipt
