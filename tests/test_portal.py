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
from render.portal.__main__ import host_allowed, resolve

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
@pytest.mark.parametrize("order", ["PO-2041", "PO-2038", "PO-2039"])
def test_receipts_match_schema(state: str, order: str) -> None:
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    receipt = load(f"receipt_{order}_{state}.json")
    assert [e.message for e in validator.iter_errors(receipt)] == []
    assert receipt["order"]["order_number"] == order
    assert receipt["receipt_id"] == f"rcpt_{order}_1"  # one receipt per order, updated in place


def test_receipts_keep_mains_sample_shape() -> None:
    # The demo moved the bad cases off BILL-07, so the receipt no longer equals main's sample,
    # but it keeps the sample's fields, ids and versions.
    mine = load("receipt_PO-2041_stopped.json")
    assert mine.keys() == SAMPLE.keys()
    for key in ["receipt_id", "business", "checks_version", "policy", "order", "bill"]:
        assert mine[key] == SAMPLE[key], key


@pytest.mark.parametrize("state", STATES)
def test_bill_07_is_the_happy_flow(state: str) -> None:
    receipt = load(f"receipt_PO-2041_{state}.json")
    assert receipt["verdict"] == "VERIFIED"
    assert {c["status"] for c in receipt["checks"]} == {"verified"}
    assert receipt["payment"]["status"] == ("sent" if state == "paid" else "not_started")
    assert "3210" not in json.dumps(receipt)


@pytest.mark.parametrize("state", STATES)
def test_bills_08_and_09_are_the_bad_cases(state: str) -> None:
    b08, b09 = load(f"receipt_PO-2038_{state}.json"), load(f"receipt_PO-2039_{state}.json")
    for r in (b08, b09):
        assert r["verdict"] == "ISSUES_FOUND" and r["payment"]["status"] == "blocked"
    assert b08["payment"]["requested_to_account"] != b08["payment"]["account_on_file"]
    assert b09["bill"]["from"] == "billing@flourco-payments.example"
    assert b09["payment"]["requested_to_account"] == b09["payment"]["account_on_file"]
    claims = state == "stopped"  # Claude's summary says they were paid
    assert any(c["status"] == "false_claim" for c in b08["checks"]) is claims


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


def test_server_serves_only_the_onboarding_file_from_the_business_folder(tmp_path: Path) -> None:
    assert resolve("/data/onboarding.json", business=tmp_path) is None  # not onboarded yet
    (tmp_path / "receipts-onboarding.json").write_text("{}")
    (tmp_path / "bakery.db").write_text("")
    assert (
        resolve("/data/onboarding.json", business=tmp_path) == tmp_path / "receipts-onboarding.json"
    )
    assert resolve("/data/receipts-onboarding.json", business=tmp_path) is None
    assert resolve("/data/../bakery.db", business=tmp_path) is None


def test_onboarding_symlink_cannot_lead_elsewhere(tmp_path: Path) -> None:
    business, outside = tmp_path / "business", tmp_path / "outside"
    business.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("token=abc123")
    (business / "receipts-onboarding.json").symlink_to(outside / "secret.txt")
    assert resolve("/data/onboarding.json", business=business) is None
    loop = tmp_path / "loop"
    loop.mkdir()
    (loop / "receipts-onboarding.json").symlink_to(loop / "receipts-onboarding.json")
    assert resolve("/data/onboarding.json", business=loop) is None


def test_server_answers_only_to_this_machines_names() -> None:
    assert host_allowed("127.0.0.1:8000", 8000) and host_allowed("localhost:8000", 8000)
    for host in ["evil.example:8000", "127.0.0.1:9000", "127.0.0.1", None]:
        assert not host_allowed(host, 8000), host


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
    stopped = next(c for c in d["feed"]["attention"] if c["id"] == "att_bill08")
    d["feed"]["events"][0]["title"] = XSS
    stopped["quote"]["text"] = XSS
    d["feed"]["steps"][0]["quote"] = XSS
    d["receipt"]["checks"][0]["title"] = XSS
    d["policies"]["policies"][0]["title"] = XSS
    stopped["actions"][0]["href"] = "javascript:alert(1)"
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
    po, po38, po39, restock, other = (
        html.index(s)
        for s in [
            "Order PO-2041",
            "Order PO-2038",
            "Order PO-2039",
            "Order PO-2042",
            "Not tied to an order",
        ]
    )
    assert po < po38 < po39 < restock < other
    assert po < html.index("Bill BILL-07 from Flour Co arrived") < po38
    assert po38 < html.index("Payment of $200.00 for BILL-08 stopped") < po39
    assert po39 < html.index("Payment of $150.00 for BILL-09 stopped") < restock
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
    assert ">Approve<" in card


@needs_node
def test_stopped_trail_shows_pay_bill_then_check() -> None:
    html = page(data("stopped"))
    for bill, check in [("BILL-08", "Check C4"), ("BILL-09", "Check C8")]:
        start = html.index(f"payment for {bill} was not sent")
        card = html[html.rindex("<article", 0, start) : html.index("</article>", start)]
        assert 'class="card stop"' in card
        listed, call, why = (
            card.index(s) for s in ["list_bills · 3 open bills", f"pay_bill · bill={bill}", check]
        )
        assert listed < call < why
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
    assert ">Approve<" in card and "Decline" in card
    tile = html[html.index("Waiting on you") :]
    assert tile.startswith('Waiting on you</span><span class="n">2</span></div>')


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
    assert 'href="#activities" title="Activities" aria-current="page">' in acts


@needs_node
def test_approval_cards_have_no_status_line() -> None:
    html = page(data("pending"), **CHECKED)
    attn = html[html.index("Needs your attention") :]
    assert attn.count('<article class="card ask">') == 2
    for part in attn.split('<article class="card ask">')[1:]:
        assert 'class="metaRow"' not in part[: part.index("</article>")]
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


# The shape the Claude Code onboarding skill writes (receipts-onboarding/0).
ANSWERS = {
    "schema": "receipts-onboarding/0",
    "payment_rules": {
        "approval_threshold_cents": 25000,
        "monthly_budget_cents": 400000,
        "approved_suppliers": [
            {"name": "Flour Co", "email_domain": "flourco.example", "account_last4": "4471"},
            {"name": XSS, "email_domain": "x.example", "account_last4": "0000"},
        ],
    },
}


@needs_node
def test_policies_and_rules_follow_the_onboarding_file() -> None:
    d = data("pending")
    d["onboarding"] = ANSWERS
    policies = page(d, "policies")
    assert "Payments over $250 need owner approval" in policies and "$250 limit" in policies
    assert "$4,000 / month" in policies and "Approved: Flour Co, " in policies
    assert "$500" not in policies
    rules = run([{"data": d, "ui": {"view": "onboarding", "onboard": {"step": 2}}}])[0]["main"]
    assert 'inputmode="numeric" value="250"' in rules
    assert "<script" not in policies + rules


@needs_node
@pytest.mark.parametrize(
    "answers",
    [
        None,
        {},
        {"payment_rules": {"approval_threshold_cents": None, "monthly_budget_cents": "1"}},
        {"payment_rules": {"monthly_budget_cents": 1e300, "approved_suppliers": []}},
        {"payment_rules": {"approved_suppliers": [{"name": 7}]}},
    ],
)
def test_missing_or_odd_onboarding_answers_keep_the_policies_file(answers: object) -> None:
    d = data("pending")
    d["onboarding"] = answers
    policies = page(d, "policies")
    assert "Payments over $500 need owner approval" in policies and "$3,000 / month" in policies


@needs_node
def test_no_budget_limit_from_onboarding_shows_as_no_limit() -> None:
    d = data("pending")
    d["onboarding"] = {"payment_rules": {"monthly_budget_cents": None}}
    policies = page(d, "policies")
    assert "No limit" in policies and "$3,000 / month" not in policies
    form = run([{"data": d, "ui": {"view": "onboarding", "onboard": {"step": 2}}}])[0]["main"]
    assert re.search(r'id="r-budget"[^>]*value=""[^>]*placeholder="No limit"', form)
    # What Save rules stores from an empty budget box; the summary must still say no limit.
    saved = {"suppliers": "Flour Co", "threshold_cents": 50000, "floor_cents": 200000}
    saved |= {"budget_cents": None, "no_budget": True}
    summary = onboarding(3, saved)["main"]
    assert "No monthly budget limit" in summary and "$3,000 a month" not in summary


@needs_node
@pytest.mark.parametrize("bad", ["250", 25050.5, -100, 1e300, True])
def test_an_invalid_saved_threshold_shows_every_payment_asks(bad: object) -> None:
    # The approval hook (#15) asks about every payment when the saved amount isn't valid.
    d = data("pending")
    d["onboarding"] = {"payment_rules": {"approval_threshold_cents": bad}}
    policies = page(d, "policies")
    assert "Every payment needs owner approval" in policies and "$500" not in policies


@needs_node
def test_threshold_shows_to_the_cent() -> None:
    d = data("pending")
    d["onboarding"] = {"payment_rules": {"approval_threshold_cents": 25050}}
    assert "Payments over $250.50 need owner approval" in page(d, "policies")


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
        assert 'class="btn" data-onb="again" title="Start onboarding">' in page(
            data("stopped"), view
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
def test_summary_card_names_the_unpaid_bills() -> None:
    stopped = page(data("stopped"))
    assert "Claude says BILL-08 and BILL-09 were paid. They weren&#39;t." in stopped
    assert "BILL-07 is waiting for your approval." in stopped
    for state in ["pending", "paid", "declined"]:
        assert "BILL-08 and BILL-09 were paid" not in page(data(state))


@needs_node
@pytest.mark.parametrize("state", ["pending", "paid"])
def test_bill_07_flow_shows_only_bill_07(state: str) -> None:
    # pending (the default) and paid (after Approve) are BILL-07's happy flow.
    for view in ["dashboard", "activities"]:
        html = page(data(state), view, **CHECKED)
        for hidden in ["BILL-08", "BILL-09", "PO-2038", "PO-2039"]:
            assert hidden not in html, (view, hidden)
        assert "BILL-07" in html
    for other in ["stopped", "declined"]:
        assert "BILL-08" in page(data(other)), other


@needs_node
def test_approving_bill_07_ends_in_success() -> None:
    pending = load("feed_pending.json")
    approve = next(c for c in pending["attention"] if c["id"] == "att_approve")
    assert approve["actions"][0]["next"] == "paid"
    html = page(data("paid"))
    attn = html[html.index("Needs your attention") :]
    assert "Paid $800.00 to Flour Co for BILL-07" in attn
    assert "was not sent" not in attn  # approving BILL-07 ends in success, nothing stopped
    assert 'class="card mismatch"' not in html and "Doesn&#39;t match" not in html


@needs_node
def test_decline_asks_before_acting() -> None:
    html = page(data("pending"), confirming={"card": "att_approve", "action": 1})
    card = html[html.index("Pay Flour Co $800.00 for bill BILL-07") :]
    card = card[: card.index("</article>")]
    assert "<strong>Decline this payment?</strong>" in card
    assert 'data-act="confirm" data-card="att_approve">Decline</button>' in card


@needs_node
def test_needs_action_matches_open_cards() -> None:
    html = page(data("stopped"), "activities", filter="action")
    for title in [
        "Claude asks to pay Flour Co $800.00 for BILL-07",
        "Payment of $200.00 for BILL-08 stopped",
        "Payment of $150.00 for BILL-09 stopped",
        "Claude&#39;s summary said BILL-08 and BILL-09 were paid",
    ]:
        assert title in html
    assert "Email to billing-help@outside.example stopped" not in html
    done = page(data("stopped"), "activities", filter="action", dismissed={"att_mismatch": True})
    assert "Claude&#39;s summary said BILL-08 and BILL-09 were paid" not in done


@needs_node
def test_order_page_details_from_review() -> None:
    proposed = page(data("pending"), "order/PO-2042", **CHECKED)
    assert "· proposed Sun 25 Oct" in proposed and "· placed" not in proposed
    receipt = page(data("stopped"), "order/PO-2041", **{"from": "activities"})
    assert '<details class="steps"><summary>Steps Claude took on this order (' in receipt
    assert 'href="#activities" title="Activities" aria-current="page">' in receipt


@needs_node
def test_passkey_only_on_onboarding_sign_in() -> None:
    for state in STATES:
        for view in ["dashboard", "activities", "policies", "order/PO-2041"]:
            assert "passkey" not in page(data(state), view).lower(), (state, view)
    assert "Sign in with your passkey" in onboarding(0)["main"]
    for step in (1, 2, 3):
        assert "passkey" not in onboarding(step)["main"].lower()
    html = page(data("pending"), confirming={"card": "att_approve", "action": 0})
    assert "<strong>Approve this payment?</strong>" in html
    assert 'data-act="confirm" data-card="att_approve">Approve</button>' in html


@needs_node
def test_balance_matches_the_seed() -> None:
    assert ">$4,800<" in page(data("pending"))
    assert ">$4,000<" in page(data("paid"))


@needs_node
def test_cleaned_up_glance_tiles_and_activities_bar() -> None:
    html = page(data("pending"), **CHECKED)
    assert "of $3,000 · 98% used</span></span>" in html
    assert "Sugar order, $120.00" not in html and "BILL-07, $800.00" not in html
    assert "blocked by the guard" not in html and "see all activities" not in html
    acts = page(data("stopped"), "activities")
    row = acts[acts.index('<div class="sh feedtop">') :]
    row = row[: row.index('<div class="feed">')]
    assert row.index('class="filters"') < row.index('class="viewtoggle"')
    assert 'class="feedbar"' not in acts


@needs_node
def test_sidebar_is_collapsible() -> None:
    side = run([{"data": data("pending"), "ui": {"view": "dashboard", "filter": "all"}}])[0]["side"]
    assert 'data-act="nav" aria-expanded="true" aria-label="Collapse sidebar"' in side
    for label in ["Dashboard", "Activities", "Policies", "Start onboarding", "Restart demo"]:
        assert f'title="{label}"' in side and f'<span class="lbl">{label}</span>' in side
    assert side.count('<svg class="ico"') == 6  # five items plus the toggle
    folded = run([{"data": data("pending"), "ui": {"view": "dashboard", "navCollapsed": True}}])[0]
    assert 'aria-expanded="false" aria-label="Expand sidebar"' in folded["side"]


@needs_node
def test_by_order_headers_show_only_order_and_link() -> None:
    html = page(data("pending"), "activities", feedView="order", **CHECKED)
    assert 'class="chain"' not in html
    for gone in [
        "16 bags of flour · $800.00 · bill BILL-07",
        "3 bags of cane sugar · $120.00",
        "Other actions Claude tried during its runs",
    ]:
        assert gone not in html
    assert '<b>Order PO-2041 · Flour Co</b></div><a href="#order/PO-2041"' in html


@needs_node
def test_greeting_names_the_business_and_sidebar_drops_it() -> None:
    out = run([{"data": data("pending"), "ui": {"view": "dashboard", "filter": "all"}}])[0]
    assert "<h1>Good afternoon, Sweet Rose Bakery</h1>" in out["main"]
    assert '<div class="brand"><b>Ledger</b></div>' in out["side"]
    assert "Sweet Rose Bakery" not in out["side"]


def _js(expr: str) -> object:
    code = (
        'const vm=require("vm"),fs=require("fs");const c={};vm.createContext(c);'
        "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);"
        f"process.stdout.write(JSON.stringify({expr}));"
    )
    proc = subprocess.run(
        ["node", "-e", code.replace("Portal", "c.Portal"), str(JS)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


@needs_node
def test_order_receipt_file_names_are_safe() -> None:
    assert _js('Portal.orderReceiptFile("live", "PO-2038")') == "receipt_live_PO-2038.json"
    assert _js('Portal.orderReceiptFile("stopped", "PO-2038")') == "receipt_PO-2038_stopped.json"
    for num in ["../policies", "PO 2038", "", "a/b", "x" * 41]:
        assert _js(f"Portal.orderReceiptFile('live', {json.dumps(num)})") is None
        assert _js(f"Portal.orderReceiptFile('paid', {json.dumps(num)})") is None
    assert _js('Portal.orderReceiptFile("../x", "PO-2041")') is None
    for state in STATES:  # every demo order has its own file
        for num in ["PO-2041", "PO-2038", "PO-2039"]:
            assert (DATA / _js(f'Portal.orderReceiptFile("{state}", "{num}")')).is_file()


@needs_node
def test_each_order_opens_its_own_receipt() -> None:
    d = data("stopped")
    other = copy.deepcopy(d["receipt"])
    other["order"]["order_number"] = "PO-2038"
    other["verdict_reason"] = "This is PO-2038's own receipt."
    d["feed"]["orders"].append(dict(d["feed"]["orders"][0], order_number="PO-2038"))
    own = page({**d, "orderReceipt": other}, "order/PO-2038")
    assert "This is PO-2038&#39;s own receipt." in own
    assert "PO-2038&#39;s own receipt" not in page({**d, "orderReceipt": other}, "order/PO-2041")
    fallback = page(d, "order/PO-2038")  # no file for this order: the feed row, no crash
    assert "Order receipt · PO-2038" in fallback and "No receipt yet" in fallback


@needs_node
def test_rules_step_shows_saving_and_escaped_errors() -> None:
    def step(onboard: dict) -> str:
        out = run([{"data": data("pending"), "ui": {"view": "onboarding", "onboard": onboard}}])
        return out[0]["main"]

    busy = step({"step": 2, "saving": True})
    assert 'data-onb="rules" disabled aria-busy="true">Saving…</button>' in busy
    failed = step({"step": 2, "error": XSS})
    assert '<p class="banner" role="alert">Your rules weren\'t saved: &lt;script&gt;' in failed
    assert "<script" not in failed
    assert ">Save rules</button>" in failed
