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
  unknown_recipient: ["Unknown recipient", "b-stop", "✕", "ic-stop"], _unknown: ["Unknown", "b-mute", "?", "ic-mute"]
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
  untrusted: ["Untrusted", "b-stop"], info: ["Info", "b-mute"], _unknown: ["Unknown", "b-mute"]
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
  var head = '<div class="metaRow"><span class="b ' + lv[1] + '">' + esc(lv[0]) + '</span><span>' + esc(c.context) + ' · ' + esc(Portal.time(c.at)) + '</span></div>' +
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
  return h + Portal.stepsBlock(feed, c.steps) + '</article>';
};
Portal.attention = function (feed, ui) {
  return (feed.attention || []).filter(function (c) { return !(ui.dismissed || {})[c.id]; });
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
  var esc = Portal.esc, byOrd = ui.feedView === "order";
  var h = '<section aria-labelledby="feedh"><div class="sh"><h2 id="feedh">AI agent activities</h2><div class="filters" role="group" aria-label="Filter">';
  Portal.FILTERS.forEach(function (f) {
    h += '<button type="button" class="chip" data-filter="' + f[0] + '" aria-pressed="' + (ui.filter === f[0]) + '">' + esc(f[1]) + '</button>';
  });
  h += '</div></div><div class="feedbar"><div class="viewtoggle" role="group" aria-label="Group activities">' +
    '<button type="button" class="seg" data-feedview="time" aria-pressed="' + !byOrd + '">By time</button>' +
    '<button type="button" class="seg" data-feedview="order" aria-pressed="' + byOrd + '">By order</button></div>' +
    '<span class="muted small">' + (byOrd ? 'Each order with its bill and payment, newest first' : 'Everything, newest first') + '</span></div><div class="feed">';
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
