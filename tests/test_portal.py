"""Owner portal: fixtures match the receipt schema, and portal.js renders them safely.

The rendering tests run render/portal/portal.js in Node, the same code the browser runs.
"""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from render.portal.__main__ import resolve

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "fixtures" / "portal"
JS = ROOT / "render" / "portal" / "portal.js"
STATES = ["pending", "stopped", "paid", "declined"]
SCHEMA = json.loads((DATA / "order_receipt.schema.json").read_text())
XSS = "<script>alert(1)</script>"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="needs Node.js to run portal.js"
)

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


@pytest.mark.parametrize("name", ["receipt_PO-2041_1.json", "receipt_PO-2041_2.json"])
def test_receipts_match_schema(name: str) -> None:
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    assert [e.message for e in validator.iter_errors(load(name))] == []


def test_policies_match_receipt() -> None:
    keys = ("id", "kind", "title", "limit_cents")
    mine = [{k: p[k] for k in keys if k in p} for p in load("policies.json")["policies"]]
    theirs = load("receipt_PO-2041_1.json")["policies"]
    assert sorted(mine, key=lambda p: p["id"]) == sorted(theirs, key=lambda p: p["id"])


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
        for view in ["dashboard", "activities", "policies", "order/PO-2041", "order/BS-1"]:
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
    html = page(data("stopped"), "activities", feedView="order")
    po, bs, other = (html.index(s) for s in ["Order PO-2041", "Order BS-1", "Not tied to an order"])
    assert po < bs < other
    for title in ["Bill BILL-07 from Flour Co arrived", "Payment of $800.00 to Flour Co stopped"]:
        assert po < html.index(title) < bs
    assert bs < html.index("Ordered 8 kg of butter from BakeSupply") < other
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
    html = page(data("pending"))
    start = html.index("Order 100 kg of sugar from BakeSupply")
    card = html[html.rindex("<article", 0, start) : html.index("</article>", start)]
    assert 'class="card ask"' in card
    assert 'class="checks"' not in card
    assert "Steps Claude took (4)" in card
    assert "bakesupply.get_price · ingredient=sugar" in card
    assert "Approve with passkey" in card and "Decline" in card
    tile = html[html.index("Waiting on you") :]
    assert tile.startswith('Waiting on you</span><span class="n">2<')
    assert "Sugar order, $95.00" in tile


@needs_node
def test_dismissed_card_leaves_waiting_count() -> None:
    html = page(data("declined"), dismissed={"att_order": True})
    assert "Order 100 kg of sugar from BakeSupply" not in html
    assert 'Waiting on you</span><span class="n">0<' in html


@needs_node
def test_activities_have_their_own_page() -> None:
    dash, acts = page(data("stopped")), page(data("stopped"), "activities")
    assert 'class="feed"' not in dash and 'href="#activities"' in dash
    assert 'class="feed"' in acts and "Needs your attention" not in acts
    assert '<a href="#activities" aria-current="page">Activities</a>' in acts


@needs_node
def test_approval_cards_have_no_status_line() -> None:
    html = page(data("pending"))
    attn = html[html.index("Needs your attention") : html.index("At a glance")]
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
        assert "<a " not in out["side"]
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
    assert 'value="Flour Co, BakeSupply"' in html
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
