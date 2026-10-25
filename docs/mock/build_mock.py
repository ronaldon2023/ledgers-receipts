"""Build the mock receipt page from a sample receipt.json.

Usage: python docs/mock/build_mock.py docs/mock/receipt_issues.json -o docs/mock/receipt.html

A design mock for team feedback, not the real renderer (that is render/render.py).
Every value is escaped: receipt text includes attacker-written email content.
"""

import argparse
import json
from html import escape
from pathlib import Path

STAGES = [
    ("guard", "Guard", "before it ran"),
    ("records", "Records", "what really happened"),
    ("summary", "Summary", "what Claude claimed"),
]

# status -> (CSS class, short label, plain-English meaning)
STATUS = {
    "verified": ("ok", "Verified", "checked against the records"),
    "blocked": ("stop", "Blocked", "stopped before it ran, no harm done"),
    "phantom": ("bad", "Phantom", "the tool said ok, but nothing was saved"),
    "false_claim": ("bad", "False claim", "the summary says more than happened"),
    "silent_action": ("bad", "Silent action", "done but never mentioned"),
    "not_done": ("bad", "Not done", "expected work is missing"),
    "unknown_recipient": ("bad", "Wrong recipient", "sent to an address not on file"),
}
ORDER = {"stop": 0, "bad": 1, "ok": 2}

VERDICT = {
    "VERIFIED": ("ok", "Verified", "Every action matches the records and Claude's summary."),
    "ISSUES_FOUND": (
        "bad",
        "Issues found",
        "Some actions need your attention before you rely on them.",
    ),
    "UNTRUSTED": (
        "bad",
        "Untrusted",
        "The log was tampered with, so nothing on this receipt can be trusted.",
    ),
}


def status_info(status: str) -> tuple[str, str, str]:
    return STATUS.get(status, ("unknown", "Unknown", "unrecognised status"))


def flow_rows(checks: list[dict]) -> list[tuple[str, dict[str, str]]]:
    """One row per action: each stage is a status, 'pass', or 'skipped' after a block."""
    actions: dict[str, dict[str, str]] = {}
    for c in checks:
        actions.setdefault(c["action"], {})[c.get("stage", "summary")] = c["status"]
    rows = []
    for action, marks in actions.items():
        cells, stopped = {}, False
        for key, _, _ in STAGES:
            if stopped:
                cells[key] = "skipped"
            elif key in marks and marks[key] != "verified":
                cells[key] = marks[key]
                stopped = marks[key] == "blocked"
            else:
                cells[key] = "pass"
        rows.append((action, cells))
    worst = {"stop": 0, "bad": 1}

    def rank(row):
        classes = [status_info(v)[0] for v in row[1].values() if v not in ("pass", "skipped")]
        return min((worst.get(c, 2) for c in classes), default=2)

    return sorted(rows, key=rank)


def cell_html(value: str) -> str:
    if value == "pass":
        return '<td class="cell pass"><span class="dot"></span><span class="lbl">Passed</span></td>'
    if value == "skipped":
        return '<td class="cell skip"><span class="lbl">Never ran</span></td>'
    cls, label, _ = status_info(value)
    return f'<td class="cell {cls}"><span class="dot"></span><span class="lbl">{escape(label)}</span></td>'


def render(r: dict) -> str:
    e = escape
    vcls, vword, vline = VERDICT.get(r["verdict"], ("bad", r["verdict"], ""))
    checks = sorted(r["checks"], key=lambda c: ORDER.get(status_info(c["status"])[0], 3))
    counts = {k: sum(1 for c in r["checks"] if status_info(c["status"])[0] == k) for k in ORDER}
    logs = r.get("log_excerpts", {})

    flow = "".join(
        f"<tr><th scope='row'>{e(action)}</th><td class='cell pass'><span class='dot'></span>"
        f"<span class='lbl'>Requested</span></td>{''.join(cell_html(cells[k]) for k, _, _ in STAGES)}</tr>"
        for action, cells in flow_rows(r["checks"])
    )
    stage_heads = "".join(
        f"<th scope='col'>{e(n)}<small>{e(sub)}</small></th>" for _, n, sub in STAGES
    )

    items = []
    for c in checks:
        cls, label, meaning = status_info(c["status"])
        ev = "".join(
            f"<details><summary>{e(ref)}</summary><code>{e(logs.get(ref, 'no excerpt'))}</code></details>"
            for ref in c.get("evidence", [])
        )
        cause = ""
        if c.get("caused_by"):
            cause = f"<p class='cause'>Triggered by {e(c['caused_by']['ref'])}: &ldquo;{e(c['caused_by']['quote'])}&rdquo;</p>"
        items.append(
            f"<li class='check {cls}'><span class='tag'>{e(label)}</span>"
            f"<div class='body'><p class='ttl'>{e(c['title'])}</p>"
            f"<p class='meta'>{e(c['action'])} &middot; {e(meaning)}</p>{cause}{ev}</div></li>"
        )

    read = "".join(f"<li><span>{e(x['source'])}</span><b>{x['count']}</b></li>" for x in r["read"])
    left = (
        "".join(
            f"<li><span>{e(x['action'].replace('_', ' '))}</span><b>{e(x['to'])}</b><small>{e(x['summary'])}</small></li>"
            for x in r["left_business"]
        )
        or "<li><span>Nothing left the business</span></li>"
    )
    pii = "".join(
        f"<li><span>{e(x['entity'].replace('_', ' ').title())}</span><b>{e(x['action'])}</b><small>{e(x['where'])}</small></li>"
        for x in r["pii"]
    )
    chain = r["chain"]
    chain_txt = "intact" if chain["ok"] else "BROKEN"

    return TEMPLATE.format(
        css=CSS,
        business=e(r["business"]),
        task=e(r["task"]),
        when=e(r["generated_at"]),
        run=e(r["run_id"]),
        vcls=vcls,
        vword=e(vword),
        vline=e(vline),
        n_stop=counts["stop"],
        n_bad=counts["bad"],
        n_ok=counts["ok"],
        stage_heads=stage_heads,
        flow=flow,
        checks="".join(items),
        read=read,
        left=left,
        pii=pii,
        chain_txt=chain_txt,
        entries=chain["entries"],
        head=e(chain["head"]),
    )


CSS = """
/* Layout: one narrow receipt column; the flow grid may scroll sideways on phones. */
:root{
  --paper:#fbfbf9; --ink:#1d2430; --muted:#5d6675; --rule:#d9dde3; --panel:#f1f3f6;
  --ok:#1f7a4d; --ok-bg:#e3f2ea; --bad:#b42318; --bad-bg:#fbe9e7; --stop:#9a5b00; --stop-bg:#fdf1dc;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#14181e; --ink:#e7eaef; --muted:#9aa3b2; --rule:#2c333d; --panel:#1b2028;
  --ok:#5cc58f; --ok-bg:#16301f; --bad:#ff8a7a; --bad-bg:#3a1714; --stop:#f0b45a; --stop-bg:#352610; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#14181e; --ink:#e7eaef; --muted:#9aa3b2; --rule:#2c333d; --panel:#1b2028;
  --ok:#5cc58f; --ok-bg:#16301f; --bad:#ff8a7a; --bad-bg:#3a1714; --stop:#f0b45a; --stop-bg:#352610; color-scheme:dark}
body{background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:24px 48px}
.wrap{max-width:760px;margin:0 auto;display:grid;gap:28px}
.mocknote{font:12px/1.4 var(--mono);color:var(--muted);border:1px dashed var(--rule);padding:8px 12px;border-radius:6px}
header{display:grid;gap:4px;border-bottom:2px dashed var(--rule);padding-bottom:16px}
.eyebrow{font:600 12px/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{font:600 30px/1.15 var(--serif);margin:0;text-wrap:balance}
.task{margin:0;color:var(--muted)}
.stamp{font:12px var(--mono);color:var(--muted)}
.verdict{display:grid;gap:6px;padding:18px 20px;border-radius:10px;border:2px solid}
.verdict.bad{background:var(--bad-bg);border-color:var(--bad);color:var(--bad)}
.verdict.ok{background:var(--ok-bg);border-color:var(--ok);color:var(--ok)}
.verdict .word{font:700 26px/1 var(--serif);text-transform:uppercase;letter-spacing:.04em}
.verdict p{margin:0;color:var(--ink)}
.tally{display:flex;flex-wrap:wrap;gap:8px 18px;font:600 14px var(--sans);color:var(--ink)}
.tally span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.tally .stop::before{background:var(--stop)} .tally .bad::before{background:var(--bad)} .tally .ok::before{background:var(--ok)}
h2{font:600 19px/1.2 var(--serif);margin:0 0 4px}
.lede{margin:0 0 12px;color:var(--muted)}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:600px;font-size:14px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--rule)}
tr:last-child th,tr:last-child td{border-bottom:0}
thead th{font:600 12px var(--sans);letter-spacing:.05em;text-transform:uppercase;color:var(--muted);background:var(--panel)}
thead th small{display:block;text-transform:none;letter-spacing:0;font-weight:400}
tbody th{font-weight:600}
.cell{position:relative;white-space:nowrap}
.cell .dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;vertical-align:-1px;background:var(--rule)}
.cell.pass .dot{background:var(--ok)} .cell.pass .lbl{color:var(--muted)}
.cell.ok .dot{background:var(--ok)}
.cell.bad{background:var(--bad-bg)} .cell.bad .dot{background:var(--bad)} .cell.bad .lbl{color:var(--bad);font-weight:700}
.cell.stop{background:var(--stop-bg)} .cell.stop .dot{background:var(--stop)} .cell.stop .lbl{color:var(--stop);font-weight:700}
.cell.skip .lbl{color:var(--muted);font-style:italic}
.cell.unknown .lbl{color:var(--muted)}
ol.checks{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.check{display:grid;grid-template-columns:110px 1fr;gap:12px;padding:12px 14px;border:1px solid var(--rule);border-radius:10px}
.check .body{min-width:0}
.tag{font:700 12px/1.2 var(--sans);text-transform:uppercase;letter-spacing:.05em;padding:4px 8px;border-radius:999px;align-self:start;justify-self:start}
.check.stop .tag{background:var(--stop-bg);color:var(--stop)}
.check.bad .tag{background:var(--bad-bg);color:var(--bad)}
.check.ok .tag{background:var(--ok-bg);color:var(--ok)}
.check.unknown .tag{background:var(--panel);color:var(--muted)}
.ttl{margin:0;font-weight:600}
.meta,.cause{margin:2px 0 0;color:var(--muted);font-size:13px}
details{margin-top:6px;font-size:13px}
summary{cursor:pointer;font:12px var(--mono);color:var(--muted)}
summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
details code{display:block;margin-top:4px;padding:8px 10px;background:var(--panel);border-radius:6px;font:12px/1.5 var(--mono);white-space:pre-wrap;word-break:break-word}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.cols section{min-width:0}
.cols ul{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.cols li{display:grid;gap:1px;padding-bottom:8px;border-bottom:1px dotted var(--rule);font-size:14px}
.cols li b{font:500 13px var(--mono);word-break:break-all;font-variant-numeric:tabular-nums}
.cols li small{color:var(--muted)}
footer{border-top:2px dashed var(--rule);padding-top:14px;font:12px/1.6 var(--mono);color:var(--muted)}
.ask{background:var(--panel);border-radius:10px;padding:14px 18px}
.ask ol{margin:6px 0 0;padding-left:20px}
@media (max-width:480px){.check{grid-template-columns:1fr}h1{font-size:25px}}
"""

TEMPLATE = """<title>Receipts Mock</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{css}</style>
<main class="wrap">
<p class="mocknote">Design mock with sample data, for team feedback. Generated from docs/mock/receipt_issues.json.</p>
<header>
  <span class="eyebrow">AI work receipt &middot; {business}</span>
  <h1>Monday money task</h1>
  <p class="task">{task}</p>
  <span class="stamp">Run {run} &middot; {when}</span>
</header>

<section class="verdict {vcls}" aria-label="Verdict">
  <span class="word">{vword}</span>
  <p>{vline}</p>
  <div class="tally"><span class="stop">{n_stop} blocked</span><span class="bad">{n_bad} problems</span><span class="ok">{n_ok} verified</span></div>
</section>

<section>
  <h2>Where each problem was caught</h2>
  <p class="lede">Every action Claude tried passes three checkpoints. A mark shows where it stopped.</p>
  <div class="scroll"><table>
    <thead><tr><th scope="col">Action</th><th scope="col">Claude<small>asked to do it</small></th>{stage_heads}</tr></thead>
    <tbody>{flow}</tbody>
  </table></div>
</section>

<section>
  <h2>Checks</h2>
  <p class="lede">Blocked first, then problems, then what was verified. Open a reference to see the log entry.</p>
  <ol class="checks">{checks}</ol>
</section>

<div class="cols">
  <section><h2>What Claude read</h2><ul>{read}</ul></section>
  <section><h2>What left the business</h2><ul>{left}</ul></section>
  <section><h2>Sensitive data</h2><ul>{pii}</ul></section>
</div>

<section class="ask">
  <h2>Tell us what you think</h2>
  <ol>
    <li>Could a bakery owner tell what happened within 10 seconds?</li>
    <li>Does the &ldquo;where it was caught&rdquo; grid help, or should it be on a slide instead?</li>
    <li>Is any wording confusing (Phantom, False claim, Blocked)?</li>
    <li>What is missing that an owner would want to know?</li>
  </ol>
</section>

<footer>Log chain {chain_txt} &middot; {entries} entries &middot; head {head}<br>Checked by code against the bakery's records. The AI never grades itself.</footer>
</main>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("receipt")
    ap.add_argument("-o", "--out", default="receipt.html")
    args = ap.parse_args()
    data = json.loads(Path(args.receipt).read_text())
    Path(args.out).write_text(render(data))


if __name__ == "__main__":
    main()
