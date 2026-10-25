/* Receipts owner portal. Renders the JSON it is given and decides no statuses itself:
   the feed file says what happened, the verifier's receipt says whether it checks out.
   Every value from data goes through Portal.esc() before it reaches HTML.
   Pure functions build HTML strings (tests run them in Node); the browser start-up is at the end. */
"use strict";
var Portal = {};

/* ---------- helpers ---------- */
Portal.esc = function (s) {
  // Masked account numbers (******3210) show as ••••3210, then everything is HTML-escaped.
  return String(s == null ? "" : s).replace(/\*{4,}(\d{4})/g, "••••$1").replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
};
Portal.money = function (c) {
  return "$" + (c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
Portal.dollars = function (c) { return "$" + Math.round(c / 100).toLocaleString("en-US"); };
// Only in-page links: data never gets to choose a URL scheme.
Portal.href = function (h) { return /^#[\w\/-]*$/.test(h || "") ? h : "#"; };

/* Dates are read straight from the ISO string, so the viewer's time zone never shifts them. */
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
Portal.time = function (at) {
  var h = +at.slice(11, 13);
  return (h % 12 || 12) + ":" + at.slice(14, 16) + " " + (h < 12 ? "AM" : "PM");
};
Portal.short = function (at) { return +at.slice(8, 10) + " " + MONTHS[+at.slice(5, 7) - 1]; };
Portal.day = function (at) {
  var wd = new Date(Date.UTC(+at.slice(0, 4), +at.slice(5, 7) - 1, +at.slice(8, 10))).getUTCDay();
  return WEEKDAYS[wd] + " " + Portal.short(at);
};

/* Status maps. Each value has its own label and class; anything unknown renders as "Unknown". */
Portal.status = function (map, key) {
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : map._unknown;
};
// Check statuses from order_receipt.schema.json: [label, badge, icon, icon class]
Portal.CHECK = {
  verified: ["Passed", "b-ok", "✓", "ic-ok"], blocked: ["Blocked", "b-stop", "✕", "ic-stop"],
  flagged: ["Flag", "b-flag", "⚑", "ic-flag"], needs_approval: ["Needs approval", "b-ask", "!", "ic-ask"],
  phantom: ["Didn't happen", "b-odd", "≠", "ic-odd"], false_claim: ["Doesn't match", "b-odd", "≠", "ic-odd"],
  silent_action: ["Not in summary", "b-odd", "≠", "ic-odd"], not_done: ["Not done", "b-stop", "✕", "ic-stop"],
  unknown_recipient: ["Unknown recipient", "b-stop", "✕", "ic-stop"], rerun_mismatch: ["Rerun differs", "b-stop", "≠", "ic-stop"],
  _unknown: ["Unknown", "b-mute", "?", "ic-mute"]
};
// Step results: [label, badge, timeline dot]
Portal.RESULT = {
  passed: ["Passed", "b-ok", "r-ok"], done: ["Done", "b-ok", "r-ok"], read: ["Read", "b-mute", ""],
  flagged: ["Flagged", "b-flag", "r-flag"], asked: ["Asked you", "b-ask", "r-ask"], blocked: ["Blocked", "b-stop", "r-stop"],
  mismatch: ["Doesn't match", "b-odd", "r-odd"], approved: ["Approved", "b-you", ""], declined: ["Declined", "b-mute", ""],
  received: ["Received", "b-mute", ""], _unknown: ["Unknown", "b-mute", ""]
};
// Feed and card levels: [label, badge]
Portal.LEVEL = {
  approve: ["Needs approval", "b-ask"], approved: ["You approved", "b-you"], declined: ["You declined", "b-mute"],
  resolved: ["Approved", "b-mute"], done: ["Done", "b-ok"], paid: ["Paid", "b-ok"], flag: ["Flag", "b-flag"],
  stop: ["Stopped", "b-stop"], mismatch: ["Doesn't match", "b-odd"], failed: ["Failed", "b-stop"],
  untrusted: ["Untrusted", "b-stop"], info: ["Info", "b-mute"], task: ["To do", "b-you"], _unknown: ["Unknown", "b-mute"]
};
Portal.VERDICT = {
  VERIFIED: ["Verified", "b-ok"], ISSUES_FOUND: ["Issues found", "b-stop"], UNTRUSTED: ["Untrusted", "b-stop"],
  _unknown: ["Unknown", "b-mute"]
};
Portal.STAGE = {
  order_placed: "Order placed", order_sent: "Order sent", fulfilled: "Fulfilled", bill_received: "Bill received",
  payment_ready: "Payment ready", payment_sent: "Payment sent", _unknown: "Unknown stage"
};
Portal.LIFE = {
  done: ["Done", "ic-ok"], blocked: ["Stopped", "ic-stop"], failed: ["Failed", "ic-stop"],
  not_reached: ["Not reached", "ic-mute"], _unknown: ["Unknown", "ic-mute"]
};
Portal.PAYMENT = { not_started: "Not started", blocked: "Stopped", sent: "Sent", failed: "Failed", _unknown: "Unknown" };
// Who did a step: Claude in brown, the owner in blue, code in default ink.
Portal.ACTORS = {
  claude: ["Claude", "AI agent", "ai"], checks: ["Checks", "Code", ""], guard: ["Guard", "Code", ""],
  verifier: ["Verifier", "Code", ""], you: ["You", "Passkey", "you"], trigger: ["Schedule", "Trigger", ""],
  supplier: ["Supplier", "Supplier", ""], _unknown: ["Unknown", "", ""]
};

/* ---------- steps Claude took (from the hash-chain log) ---------- */
Portal.pick = function (feed, ids) {
  var by = {};
  (feed.steps || []).forEach(function (s) { by[s.id] = s; });
  return (ids || []).map(function (id) { return by[id]; }).filter(Boolean);
};
Portal.trail = function (list, days) {
  var esc = Portal.esc, h = '<ol class="trail">';
  list.forEach(function (s) {
    var a = Portal.status(Portal.ACTORS, s.actor), r = Portal.status(Portal.RESULT, s.result);
    h += '<li class="step ' + r[2] + '"><span class="t">' + (days ? esc(Portal.short(s.at)) + "<br>" : "") + esc(Portal.time(s.at)) + '</span>' +
      '<span class="who ' + a[2] + '"><b>' + esc(s.who || a[0]) + '</b><span>' + esc(a[1]) + '</span></span>' +
      '<span class="what"><span>' + esc(s.text) + '</span><span class="tool">' + esc(s.call) + ' · ' + esc(s.id) + '</span>' +
      (s.quote ? '<span class="q">"' + esc(s.quote) + '"</span>' : '') +
      (s.note ? '<span class="muted small">' + esc(s.note) + '</span>' : '') + '</span>' +
      '<span class="res"><span class="b ' + r[1] + '">' + esc(r[0]) + '</span></span></li>';
  });
  return h + '</ol>';
};
Portal.stepsBlock = function (feed, ids) {
  var list = Portal.pick(feed, ids);
  return '<details class="steps"><summary>Steps Claude took (' + list.length + ')</summary>' + Portal.trail(list) + '</details>';
};
Portal.legend = '<div class="legend"><span><b>Claude</b> · AI agent, does the work</span>' +
  '<span><b>Checks, Guard, Verifier</b> · plain code, no AI</span><span><b>You</b> · passkey approvals</span></div>';

/* ---------- needs your attention ---------- */
Portal.quote = function (q) {
  var t = q.plain ? Portal.esc(q.text) : '"' + Portal.esc(q.text) + '"';
  return '<div class="quote"><b>' + Portal.esc(q.label) + '</b>' + t + '</div>';
};
Portal.passkey = function (card, text) {
  return '<div class="passkey" role="group" aria-label="Confirm with passkey"><strong>Confirm with your passkey</strong><span>' + Portal.esc(text) + '</span>' +
    '<div class="actions"><button type="button" class="btn primary" data-act="passkey" data-card="' + Portal.esc(card) + '">Use passkey</button>' +
    '<button type="button" class="btn ghost" data-act="cancel">Cancel</button></div></div>';
};
Portal.card = function (feed, c, ui) {
  var esc = Portal.esc, lv = Portal.status(Portal.LEVEL, c.level);
  var cls = { approve: "ask", stop: "stop", failed: "stop", mismatch: "odd" }[c.level] || "";
  // Approval and task cards skip the status line: their buttons say what's needed.
  var head = (c.level === "approve" || c.level === "task" ? '' : '<div class="metaRow"><span class="b ' + lv[1] + '">' + esc(lv[0]) + '</span><span>' + esc(c.context) + ' · ' + esc(Portal.time(c.at)) + '</span></div>') +
    '<h3>' + esc(c.title) + '</h3>' + (c.subtitle ? '<p class="muted">' + esc(c.subtitle) + '</p>' : '');
  var h = '<article class="card ' + cls + '">' + (c.amount_cents != null
    ? '<div class="cardhead"><div class="l">' + head + '</div><span class="amount">' + esc(Portal.money(c.amount_cents)) + '</span></div>' : head);
  if (c.body) h += '<p>' + esc(c.body) + '</p>';
  if (c.quote) h += Portal.quote(c.quote);
  if (c.pair) h += '<div class="pair">' + c.pair.map(Portal.quote).join("") + '</div>';
  if (c.next_step) h += '<p><strong>Next step:</strong> ' + esc(c.next_step) + '</p>';
  var actions = c.actions || [], wait = ui.confirming && ui.confirming.card === c.id ? actions[ui.confirming.action] : null;
  h += wait ? Portal.passkey(c.id, wait.confirm) : '<div class="actions">' + actions.map(function (a, i) {
    if (a.href) return '<a class="btn ghost linkbtn" href="' + esc(Portal.href(a.href)) + '">' + esc(a.label) + '</a>';
    return '<button type="button" class="btn' + (a.primary ? ' primary' : '') + '" data-card="' + esc(c.id) + '" data-action="' + i + '">' + esc(a.label) + '</button>';
  }).join("") + '</div>';
  return h + (Portal.pick(feed, c.steps).length ? Portal.stepsBlock(feed, c.steps) : '') + '</article>';
};
Portal.attention = function (feed, ui) {
  return (feed.attention || []).filter(function (c) { return !(ui.dismissed || {})[c.id]; });
};
/* The owner's clicks in this demo: an item with "requires" stays hidden until that card's action
   has run, and an item that "resolves" with a card takes its when_approved or when_declined fields
   once the owner has answered that card. */
Portal.visible = function (feed, ui) {
  var ran = ui.ran || {}, dis = ui.dismissed || {}, out = {};
  var shown = function (x) { return !x.requires || ran[x.requires]; };
  var answered = function (x) {
    if (!x.resolves || !dis[x.resolves]) return x;
    var y = {}, extra = ran[x.resolves] ? x.when_approved : x.when_declined, k;
    for (k in x) y[k] = x[k];
    for (k in extra || {}) y[k] = extra[k];
    return y;
  };
  for (var k in feed) out[k] = feed[k];
  ["steps", "events", "attention", "orders"].forEach(function (key) {
    out[key] = (feed[key] || []).filter(shown).map(answered);
  });
  return out;
};

/* ---------- AI agent activities ---------- */
Portal.FILTERS = [["all", "All"], ["action", "Needs action"], ["orders", "Orders"], ["payments", "Payments"], ["stopped", "Stopped and flags"]];
Portal.keep = function (filter, it) {
  if (filter === "action") return ["approve", "stop", "mismatch", "failed"].indexOf(it.level) >= 0;
  if (filter === "orders") return it.kind === "Order" || it.kind === "Bill";
  if (filter === "payments") return ["Payment", "Bill", "Inbox", "Summary"].indexOf(it.kind) >= 0;
  if (filter === "stopped") return ["stop", "mismatch", "flag", "failed"].indexOf(it.level) >= 0;
  return true;
};
Portal.groups = function (feed, byOrder) {
  var events = feed.events || [];
  if (!byOrder) {
    var days = [], seen = {};
    events.forEach(function (e) {
      var d = e.at.slice(0, 10);
      if (!seen[d]) {
        seen[d] = { head: '<div class="day">' + (d === feed.as_of.slice(0, 10) ? "Today · " : "") + Portal.esc(Portal.day(e.at)) + '</div>', items: [] };
        days.push(seen[d]);
      }
      seen[d].items.push(e);
    });
    return days;
  }
  // By order: each order's bill, payment, flags and summary checks sit under it.
  var esc = Portal.esc, orders = feed.orders || [], known = {};
  var out = orders.map(function (o) {
    known[o.order_number] = true;
    var chain = (o.progress || []).map(function (p) {
      return p.level === "done" ? '<li><span class="ic-ok">✓</span>' + esc(p.label) + '</li>'
        : '<li><span class="b ' + Portal.status(Portal.LEVEL, p.level)[1] + '">' + esc(p.label) + '</span></li>';
    }).join("");
    var bill = o.bill_id ? ' · bill ' + esc(o.bill_id) + ' due ' + esc(Portal.day(o.bill_due)) : '';
    return { items: events.filter(function (e) { return e.order === o.order_number; }),
      head: '<div class="ordhead"><div class="oh-l"><b>Order ' + esc(o.order_number) + ' · ' + esc(o.seller) + '</b><span class="muted small">' +
        esc(o.summary) + ' · ' + esc(Portal.money(o.total_cents)) + bill + '</span></div>' +
        '<ol class="chain" aria-label="Order progress">' + chain + '</ol><a href="' + esc(Portal.href("#order/" + o.order_number)) + '" class="small">Order receipt</a></div>' };
  });
  out.push({ items: events.filter(function (e) { return !known[e.order]; }),
    head: '<div class="ordhead"><div class="oh-l"><b>Not tied to an order</b><span class="muted small">Other actions Claude tried during its runs</span></div></div>' });
  return out;
};
Portal.feedHtml = function (feed, ui) {
  var esc = Portal.esc, byOrd = ui.feedView !== "time"; // By order is the default
  var h = '<section aria-label="AI agent activities"><div class="sh"><div class="filters" role="group" aria-label="Filter">';
  Portal.FILTERS.forEach(function (f) {
    h += '<button type="button" class="chip" data-filter="' + f[0] + '" aria-pressed="' + (ui.filter === f[0]) + '">' + esc(f[1]) + '</button>';
  });
  h += '</div></div><div class="feedbar"><div class="viewtoggle" role="group" aria-label="Group activities">' +
    '<button type="button" class="seg" data-feedview="order" aria-pressed="' + byOrd + '">By order</button>' +
    '<button type="button" class="seg" data-feedview="time" aria-pressed="' + !byOrd + '">By time</button></div>' +
    '</div><div class="feed">';
  var any = false;
  Portal.groups(feed, byOrd).forEach(function (g) {
    var items = g.items.filter(function (it) { return Portal.keep(ui.filter, it); });
    if (!items.length) return;
    any = true;
    h += g.head;
    items.forEach(function (it) {
      var l = Portal.status(Portal.LEVEL, it.level), n = Portal.pick(feed, it.steps).length;
      h += '<details class="item' + (it.level === "resolved" ? " mute" : "") + '"><summary><span class="t">' + (byOrd ? esc(Portal.short(it.at)) + '<br>' : '') + esc(Portal.time(it.at)) + '</span>' +
        '<span class="bcol"><span class="b ' + l[1] + '">' + esc(l[0]) + '</span><span class="cat">' + esc(it.kind) + (byOrd && it.kind === "Bill" && it.bill ? ' · ' + esc(it.bill) : '') + '</span></span>' +
        '<span class="main"><div class="ti">' + esc(it.title) + '</div><div class="de">' + esc(it.detail) + '</div></span><span class="more">' + n + (n === 1 ? ' step' : ' steps') + '</span></summary>' +
        '<div class="body">' + Portal.trail(Portal.pick(feed, it.steps)) + '</div></details>';
    });
  });
  if (!any) h += '<p style="margin:0;padding:24px 20px" class="muted">Nothing here for this filter.</p>';
  return h + '</div></section>';
};

/* ---------- pages ---------- */
Portal.header = function (title, sub) {
  return '<header class="top"><div><h1>' + Portal.esc(title) + '</h1>' + (sub ? '<p>' + Portal.esc(sub) + '</p>' : '') + '</div></header>';
};
Portal.dashboard = function (d, ui) {
  var esc = Portal.esc, f = d.feed, g = f.glance, cards = Portal.attention(f, ui);
  var pct = Math.floor(g.budget.used_cents / g.budget.limit_cents * 100); // round down: 99.7% is not "100% used"
  var waiting = cards.filter(function (c) { return c.level === "approve"; });
  var h = Portal.header("Good afternoon, " + f.owner);
  h += '<section aria-labelledby="glh"><h2 id="glh" style="margin:0;font-size:19px;font-weight:600">At a glance</h2><div class="glance">' +
    '<div class="tile"><span class="k">' + esc(g.budget.label) + '</span><span class="n">' + esc(Portal.dollars(g.budget.used_cents)) + ' <span>of ' + esc(Portal.dollars(g.budget.limit_cents)) + '</span></span>' +
    '<div class="meter" role="img" aria-label="' + pct + ' percent used"><i style="width:' + Math.min(pct, 100) + '%"></i></div>' +
    '<span class="d">' + pct + '% used</span></div>' +
    '<div class="tile"><span class="k">Operating balance</span><span class="n">' + esc(Portal.dollars(g.balance.balance_cents)) + '</span></div>' +
    '<div class="tile"><span class="k">Waiting on you</span><span class="n">' + waiting.length + '</span><span class="d">' +
    (waiting.length ? waiting.map(function (c) { return esc(c.short || c.title); }).join("<br>") : "No approvals waiting") + '</span></div>' +
    '<div class="tile"><span class="k">Claude\'s run today</span><span class="n">' + esc(g.run.steps) + ' <span>steps</span></span>' +
    '<span class="d">' + esc(g.run.blocked) + ' blocked by the guard · <a href="#activities">see all activities</a></span></div></div></section>';
  h += '<section aria-labelledby="attnh"><div class="sh"><h2 id="attnh">Needs your attention</h2><span>' +
    (cards.length ? cards.length + (cards.length === 1 ? " item" : " items") : "Nothing waiting") + '</span></div>';
  h += cards.length ? '<div class="attn">' + cards.map(function (c) { return Portal.card(f, c, ui); }).join("") + '</div>'
    : '<div class="card"><p>All clear. Nothing needs you right now.</p></div>';
  return h + '</section>';
};
Portal.activities = function (d, ui) {
  return Portal.header("AI agent activities") +
    Portal.feedHtml(d.feed, ui);
};
Portal.itemsTable = function (items, total) {
  var esc = Portal.esc;
  return '<section class="card"><h2 style="margin:0;font-size:17px">Items</h2><div class="tablewrap" style="border:0"><table><thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Total</th></tr></thead><tbody>' +
    items.map(function (i) { return '<tr><td>' + esc(i.name) + '</td><td class="num">' + esc(i.quantity) + '</td><td class="num">' + esc(Portal.money(i.total_cents)) + '</td></tr>'; }).join("") +
    '<tr><td><b>Total</b></td><td></td><td class="num"><b>' + esc(Portal.money(total)) + '</b></td></tr></tbody></table></div></section>';
};
Portal.receiptBody = function (r) {
  var esc = Portal.esc, v = Portal.status(Portal.VERDICT, r.verdict), p = r.payment, b = r.bill;
  var h = '<section class="card"><div class="verdict"><span class="b ' + v[1] + '">' + esc(v[0]) + '</span><p style="margin:0;max-width:70ch">' + esc(r.verdict_reason) + '</p></div>';
  // One receipt per order, updated at each step: not_checked means Claude hasn't written its summary yet.
  if (r.summary_check.status === "not_checked") h += '<p class="note">Claude hasn\'t written its summary yet, so it hasn\'t been checked.</p>';
  else if (r.summary_check.status !== "checked") h += '<p class="banner">Claude\'s summary couldn\'t be checked, so this receipt can\'t be called clean.</p>';
  if (r.owner_action && r.owner_action.needed) h += '<p><strong>Next step:</strong> ' + esc(r.owner_action.title) + '</p>';
  h += '<ol class="stages">' + r.events.map(function (s) {
    var st = s.status !== "not_reached" && s.source === "unverified" ? ["Unverified", "ic-mute"] : Portal.status(Portal.LIFE, s.status);
    return '<li><b>' + esc(Portal.status(Portal.STAGE, s.stage)) + '</b><span class="muted">' + esc(s.at ? Portal.short(s.at) : s.status === "not_reached" ? "Not yet" : "Not recorded") + '</span><span class="tag ' + st[1] + '">' + esc(st[0]) + '</span></li>';
  }).join("") + '</ol></section>';
  var pay = Portal.status(Portal.PAYMENT, p.status) + (p.payment_id ? " · " + p.payment_id : "");
  var to = p.requested_to_account && p.requested_to_account !== p.account_on_file
    ? p.requested_to_account + " requested · " + p.account_on_file + " on file" : (p.account_on_file || "") + " (on file)";
  h += '<div class="two">' + Portal.itemsTable(r.order.items, r.order.total_cents) +
    '<section class="card"><h2 style="margin:0;font-size:17px">Bill and payment</h2><dl class="kv">' +
    (b ? '<dt>Bill</dt><dd>' + esc(b.bill_id + " · " + Portal.money(b.amount_cents) + " · due " + Portal.day(b.due_date)) + '</dd>' : '') +
    '<dt>Payment</dt><dd>' + esc(pay) + '</dd><dt>Pay to</dt><dd class="mono">' + esc(to) + '</dd></dl></section></div>';
  h += '<section class="card"><div class="sh"><h2>Checks</h2><span>Plain code decided each one, not Claude</span></div><ul class="checks">' + r.checks.map(function (c) {
    var s = Portal.status(Portal.CHECK, c.status), q = c.caused_by ? c.caused_by.quote : c.quote;
    return '<li class="' + (c.status === "flagged" ? "flag" : "") + '"><span class="' + s[3] + '">' + esc(s[2]) + '</span><span><span class="b ' + s[1] + '">' + esc(s[0]) + '</span>' + esc(c.title) +
      (q ? '<span class="q">"' + esc(q) + '"</span>' : '') + '<span class="ref">' + esc([c.id].concat(c.evidence).join(" · ")) + '</span></span></li>';
  }).join("") + '</ul></section>';
  return h;
};
Portal.order = function (d, num) {
  var esc = Portal.esc, f = d.feed, r = d.receipt && d.receipt.order.order_number === num ? d.receipt : null;
  var o = (f.orders || []).filter(function (x) { return x.order_number === num; })[0];
  if (!o && !r) return Portal.header("Order not found", num) + '<div class="card"><p><a href="#dashboard">Back to the dashboard</a></p></div>';
  var seller = r ? r.order.seller : { name: o.seller, email: o.seller_email }, placed = r ? r.order.order_date : o.placed_at;
  var h = '<a class="back" href="#dashboard">← Back to dashboard</a>' + Portal.header("Order receipt · " + num, seller.name + " · placed " + Portal.day(placed) + ", " + Portal.time(placed) + (seller.email ? " · " + seller.email : ""));
  h += r ? Portal.receiptBody(r) : '<section class="card"><p class="note">' + esc(o.receipt_note || "No receipt yet. The verifier writes one when the order stops: its bill is paid, or the payment is stopped.") + '</p></section>' +
    '<div class="two">' + Portal.itemsTable(o.items, o.total_cents) + '</div>';
  var steps = (f.steps || []).filter(function (s) { return s.order === num; });
  return h + '<section class="card"><div class="sh"><h2>Steps Claude took on this order</h2><span>' + steps.length + ' steps · oldest first</span></div>' +
    Portal.legend + Portal.trail(steps, true) + '</section>';
};
Portal.POLICY_GROUPS = [
  ["guard", "Guards"], ["order", "Order policy"], ["payment", "Payment policy"], ["budget", "Budget policy"]
];
Portal.policies = function (d) {
  var esc = Portal.esc, pol = d.policies || { guards: [], policies: [] };
  var h = Portal.header("Policies", "The rules Claude must follow. Plain code checks them before every action; Claude can't change them.");
  Portal.POLICY_GROUPS.forEach(function (g) {
    var list = g[0] === "guard" ? pol.guards : pol.policies.filter(function (p) { return p.kind === g[0]; });
    h += '<section aria-labelledby="pol-' + g[0] + '"><div class="sh"><h2 id="pol-' + g[0] + '">' + esc(g[1]) + '</h2></div>' +
      '<div class="tablewrap"><table><thead><tr><th style="width:62%">Rule</th><th>Setting</th></tr></thead><tbody>' +
      list.map(function (p) { return '<tr><td>' + esc(p.title) + '</td><td class="mono small">' + esc(p.setting) + '</td></tr>'; }).join("") + '</tbody></table></div></section>';
  });
  return h;
};

/* ---------- onboarding: sign in, connect Claude Code, set your rules ---------- */
Portal.ONBOARD_STEPS = ["Sign in", "Connect Claude Code", "Your rules", "You're set"];
// Install order from the plugin PR (#7): the small-business dependency's marketplace must come first.
Portal.INSTALL = [
  "/plugin marketplace add anthropics/knowledge-work-plugins",
  "/plugin marketplace add ronaldon2023/ledgers-receipts",
  "/plugin install ledgers-receipts@the-ledgers"
];
// Starting values for the rules step, read from the policies file.
Portal.ruleDefaults = function (pol) {
  var by = {};
  ((pol || {}).policies || []).forEach(function (p) { by[p.id] = p; });
  var limit = function (id, c) { return by[id] && by[id].limit_cents != null ? by[id].limit_cents : c; };
  return {
    suppliers: ((by["POL-ORDER-VENDOR"] || {}).setting || "").replace(/^Approved:\s*/, ""),
    threshold_cents: limit("POL-PAY-THRESHOLD", 50000), budget_cents: limit("POL-BUDGET-MONTHLY", 300000),
    floor_cents: limit("POL-BANK-FLOOR", 200000)
  };
};
Portal.onboarding = function (d, ui) {
  var esc = Portal.esc, o = ui.onboard || {}, step = o.step || 0, r = o.rules || Portal.ruleDefaults(d.policies);
  var back = '<button type="button" class="btn ghost" data-onb="back">Back</button>';
  var h = '<header class="top"><div><h1>Set up Ledger</h1><p>' + esc(d.feed.business) + ' · step ' + (step + 1) + ' of 4</p></div></header>' +
    '<ol class="stages" aria-label="Setup steps">' + Portal.ONBOARD_STEPS.map(function (s, i) {
      return '<li' + (i === step ? ' class="on" aria-current="step"' : '') + '><b>' + esc(s) + '</b><span class="tag ' + (i < step ? 'ic-ok">Done' : i === step ? 'ic-ask">Now' : 'ic-mute">Next') + '</span></li>';
    }).join("") + '</ol><section class="card onb">';
  if (step === 0) {
    h += '<h2>Welcome, ' + esc(d.feed.owner) + '</h2><p>Ledger shows you everything Claude does for your business. Claude does the work, plain code checks every step, and nothing over your limits happens without you.</p>' +
      '<div class="passkey"><strong>Sign in with your passkey</strong><span>Use Touch ID, Face ID or your security key. The same passkey approves payments later, so a stolen email or password can\'t move your money.</span>' +
      '<div class="actions"><button type="button" class="btn primary" data-onb="signin">Use passkey</button></div></div>';
  } else if (step === 1) {
    var cmd = function (c, i) {
      return '<div class="cmd"><code>' + esc(c) + '</code><button type="button" class="btn" data-copy="' + i + '">' + (o.copied === i ? 'Copied' : 'Copy') + '</button></div>';
    };
    h += '<h2>Connect Claude Code</h2><p>Claude works for you inside Claude Code. These steps let Ledger log and check everything it does.</p><ol class="howto">' +
      '<li><b>Install Claude Code and sign in.</b> Follow the steps at <a href="https://claude.com/claude-code" target="_blank" rel="noopener">claude.com/claude-code</a>.</li>' +
      '<li><b>Open your business folder and start Claude.</b> In a terminal, go to the folder that holds your business files, then run:' + cmd("claude", 0) + '</li>' +
      '<li><b>Add the Ledger plugin.</b> Paste these into Claude, one at a time and in this order:' + Portal.INSTALL.map(function (c, i) { return cmd(c, i + 1); }).join("") + '</li>' +
      '<li><b>Restart Claude.</b> It offers to set up your rules. Answer its questions; it confirms the same rules you\'ll see next.</li></ol>' +
      '<div class="actions"><button type="button" class="btn primary" data-onb="connected">I\'ve connected Claude</button>' + back + '</div>';
  } else if (step === 2) {
    var num = function (id, label, cents) {
      return '<label class="field"><span><b>' + esc(label) + '</b></span><span class="dollar">$<input id="' + id + '" type="number" min="0" step="1" inputmode="numeric" value="' + esc(Math.round(cents / 100)) + '"></span></label>';
    };
    h += '<h2>Your rules</h2><p>Plain code checks these before every action Claude takes. Claude can\'t change them.</p>' +
      '<h3>Order</h3><label class="field"><span><b>Approved suppliers</b></span><input id="r-suppliers" type="text" value="' + esc(r.suppliers) + '"></label>' +
      '<h3>Payment</h3>' + num("r-threshold", "Ask me before paying more than", r.threshold_cents) +
      '<h3>Budget</h3>' + num("r-budget", "Monthly supplies budget", r.budget_cents) +
      num("r-floor", "Always keep in the bank", r.floor_cents) +
      '<h3>Always on</h3><ul class="checks plain"><li><span class="ic-ok">✓</span><span><b>Email only addresses on file</b></span></li>' +
      '<li><span class="ic-ok">✓</span><span><b>Pay only the account on file</b></span></li></ul>' +
      '<div class="actions"><button type="button" class="btn primary" data-onb="rules">Save rules</button>' + back + '</div>';
  } else {
    h += '<h2>You\'re set</h2><div class="two">' +
      '<div class="quote"><b>Claude does the work</b>Orders supplies, pays bills and answers email, using the order and payment skills.</div>' +
      '<div class="quote"><b>Code checks every step</b>Approved suppliers: ' + esc(r.suppliers || "none yet") + '. Budget ' + esc(Portal.dollars(r.budget_cents)) + ' a month. Keep ' + esc(Portal.dollars(r.floor_cents)) + ' in the bank. Every step goes into a tamper-evident log.</div>' +
      '<div class="quote"><b>You approve</b>Anything over ' + esc(Portal.dollars(r.threshold_cents)) + ', with your passkey, here in Ledger.</div>' +
      '<div class="quote"><b>Alerts</b>We email you when something needs you. Email buttons only open Ledger; approving always needs your passkey here.</div></div>' +
      '<div class="actions"><button type="button" class="btn primary" data-onb="finish">Go to dashboard</button>' + back + '</div>';
  }
  return h + '</section>';
};

Portal.page = function (d, ui) {
  var esc = Portal.esc, view = ui.view || "dashboard";
  d = { feed: Portal.visible(d.feed, ui), receipt: d.receipt, policies: d.policies };
  var brand = '<div class="brand"><b>Ledger</b><span>' + esc(d.feed.business) + '</span></div>';
  if (view === "onboarding") return { side: "", main: Portal.onboarding(d, ui) }; // no sidebar during setup
  var broken = d.feed.chain_ok === false || (d.receipt ? d.receipt.sessions : []).some(function (s) { return !s.ok; });
  var main = view.indexOf("order/") === 0 ? Portal.order(d, view.slice(6)) : view === "policies" ? Portal.policies(d)
    : view === "activities" ? Portal.activities(d, ui) : Portal.dashboard(d, ui);
  if (broken) main = '<p class="banner" role="alert">Untrusted: the activity log failed its tamper check. Don\'t rely on anything here until it\'s fixed.</p>' + main;
  var cur = view === "policies" || view === "activities" ? view : "dashboard";
  var side = brand +
    [["dashboard", "Dashboard"], ["activities", "Activities"], ["policies", "Policies"]].map(function (l) {
      return '<a href="#' + l[0] + '"' + (l[0] === cur ? ' aria-current="page"' : '') + '>' + esc(l[1]) + '</a>';
    }).join("") + '<div class="navbtns"><button type="button" class="btn" data-onb="again">Start onboarding</button>' +
    '<button type="button" class="btn" data-act="reset">Restart demo</button></div>' +
    '<div class="meta"><span>' + esc(Portal.day(d.feed.as_of) + " · " + Portal.time(d.feed.as_of)) + '</span><span>Agent: Claude · connected</span><span>Log chain: <strong' + (broken ? ' class="bad">broken' : '>intact') + '</strong></span>' +
    '<span>Signed in as ' + esc(d.feed.owner) + ' · passkey</span></div>';
  return { side: side, main: main };
};

/* ---------- browser start-up: load the JSON, check it again every second, handle clicks ---------- */
if (typeof document !== "undefined") (function () {
  var KEY = "receipts-portal-v3", STATES = ["pending", "stopped", "paid", "declined"];
  var ui = { state: "pending", filter: "all", feedView: "order", confirming: null, dismissed: {}, ran: {}, onboarded: false, onboard: { step: 0 } };
  var data = null, last = "", side = document.getElementById("side"), app = document.getElementById("app");
  try {
    var saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved && STATES.indexOf(saved.state) >= 0) { ui.state = saved.state; ui.dismissed = saved.dismissed || {}; ui.ran = saved.ran || {}; }
    if (saved) { ui.onboarded = !!saved.onboarded; ui.onboard.rules = saved.rules; }
  } catch (e) { /* storage blocked: start fresh */ }
  var asked = /[?&]state=(\w+)/.exec(location.search); // ?state=stopped opens a demo state directly
  if (asked && STATES.indexOf(asked[1]) >= 0) { ui.state = asked[1]; ui.onboarded = true; }
  if (/[?&]onboarding=1/.test(location.search)) ui.onboarded = false; // ?onboarding=1 runs setup again
  function view() {
    var h = (location.hash || "").slice(1);
    if (!ui.onboarded) return "onboarding";
    return h === "policies" || h === "activities" || h.indexOf("order/") === 0 ? h : "dashboard";
  }
  function render() {
    if (!data) return;
    ui.view = view();
    var out = Portal.page(data, ui);
    side.innerHTML = out.side;
    side.hidden = !out.side;
    app.innerHTML = out.main;
  }
  function set(p) {
    for (var k in p) ui[k] = p[k];
    try {
      localStorage.setItem(KEY, JSON.stringify({ state: ui.state, dismissed: ui.dismissed, ran: ui.ran, onboarded: ui.onboarded, rules: ui.onboard.rules }));
    } catch (e) { /* ignore */ }
    render();
  }
  function get(name) {
    return fetch("data/" + name, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(name + ": " + r.status);
      return r.text();
    });
  }
  function load() {
    return Promise.all([get("feed_" + ui.state + ".json"), get("policies.json")]).then(function (t) {
      var feed = JSON.parse(t[0]);
      return (feed.receipt ? get(feed.receipt) : Promise.resolve("null")).then(function (rt) {
        if (t.join("") + rt === last) return; // unchanged: keep open sections open
        last = t.join("") + rt;
        data = { feed: feed, receipt: JSON.parse(rt), policies: JSON.parse(t[1]) };
        render();
      });
    }).catch(function (e) {
      app.innerHTML = '<div class="card"><p>Could not load the portal data: ' + Portal.esc(e.message) + '</p></div>';
    });
  }
  function go(state) { last = ""; set({ state: state, confirming: null }); load(); }
  function onboardClick(t) {
    var o = ui.onboard, step = o.step || 0, act = t.getAttribute("data-onb");
    if (t.hasAttribute("data-copy")) {
      var i = +t.getAttribute("data-copy"), text = i === 0 ? "claude" : Portal.INSTALL[i - 1];
      if (navigator.clipboard) navigator.clipboard.writeText(text).catch(function () { /* copy blocked */ });
      o.copied = i;
      return set({});
    }
    if (act === "again") { ui.onboard = { step: 0, rules: o.rules }; return set({ onboarded: false }); }
    if (act === "back") o.step = Math.max(0, step - 1);
    else if (act === "rules") {
      var dollars = function (id) { var v = Math.round(+document.getElementById(id).value); return (v > 0 ? v : 0) * 100; };
      o.rules = { suppliers: document.getElementById("r-suppliers").value.trim(), threshold_cents: dollars("r-threshold"),
        budget_cents: dollars("r-budget"), floor_cents: dollars("r-floor") };
      o.step = 3;
    } else if (act === "finish") { location.hash = "#dashboard"; return set({ onboarded: true }); }
    else o.step = step + 1; // signin, connected
    o.copied = null;
    set({});
    window.scrollTo(0, 0);
  }
  document.addEventListener("click", function (e) {
    var ob = e.target.closest("[data-onb],[data-copy]");
    if (ob) return onboardClick(ob);
    var t = e.target.closest("[data-filter],[data-feedview],[data-action],[data-act]");
    if (!t) return;
    if (t.hasAttribute("data-filter")) return set({ filter: t.getAttribute("data-filter") });
    if (t.hasAttribute("data-feedview")) return set({ feedView: t.getAttribute("data-feedview") });
    var card = (data.feed.attention || []).filter(function (c) { return c.id === t.getAttribute("data-card"); })[0];
    var act = t.getAttribute("data-act");
    if (act === "reset") { ui.dismissed = {}; ui.ran = {}; ui.filter = "all"; return go("pending"); }
    if (act === "cancel") return set({ confirming: null });
    if (!card) return;
    var i = act === "passkey" && ui.confirming ? ui.confirming.action : +t.getAttribute("data-action"), a = card.actions[i];
    if (a.confirm && act !== "passkey") return set({ confirming: { card: card.id, action: i } });
    if (a.run) ui.ran[card.id] = true; // e.g. Start check: reveals what that run produced
    if (a.dismiss || a.run) { ui.dismissed[card.id] = true; set({ confirming: null }); }
    else if (a.next) go(a.next);
  });
  window.addEventListener("hashchange", function () { render(); window.scrollTo(0, 0); });
  load();
  setInterval(load, 1000);
})();
