/* shared by every page; D is inlined by build.py */
const V = D.vocab;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const DAY = 86400000;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/* ---------- dates: one style everywhere (relative on top, exact below) ---------- */
function pd(s) {
  if (!s) return null;
  if (/^\d{4}-\d{2}$/.test(s)) return { t: Date.parse(s + "-01T00:00Z"), p: "month" };
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return { t: Date.parse(s + "T00:00Z"), p: "day" };
  return { t: Date.parse(s.replace("Z", ":00Z")), p: "minute" };
}
const now = Date.now();
const todayT = Date.parse(new Date(now).toISOString().slice(0, 10) + "T00:00Z");
const thisYear = new Date(now).getUTCFullYear();
const daysTo = (t) => Math.round((Math.floor(t / DAY) * DAY - todayT) / DAY); // UTC calendar days
function absDate(s) {
  const d = pd(s); if (!d) return "";
  const x = new Date(d.t), y = x.getUTCFullYear();
  if (d.p === "month") return `${MON[x.getUTCMonth()]} ${y}`;
  const day = `${MON[x.getUTCMonth()]} ${x.getUTCDate()}${y !== thisYear ? ", " + y : ""}`;
  return d.p === "minute" ? `${day}, ${x.toISOString().slice(11, 16)} UTC` : day;
}
function relDays(t) {
  const n = daysTo(t);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  if (Math.abs(n) > 45) return null;
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

/* ---------- icons (inline SVG, stroke = currentColor) ---------- */
const svg = (p, label) => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ${label ? `role="img" aria-label="${label}"` : 'aria-hidden="true"'}>${p}</svg>`;
const I = {
  bolt: (l) => svg('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', l),
  lock: (l) => svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>', l),
  eye: (l) => svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>', l),
  help: (l) => svg('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14"/><path d="M12 17h.01"/>', l),
  copy: (l) => svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>', l),
  ext: (l) => svg('<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>', l),
  image: (l) => svg('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>', l),
  minus: (l) => svg('<path d="M5 12h14"/>', l),
};

/* ---------- vocab + entities ---------- */
const lab = (v, k) => V[v][k].label;
const short = (v, k) => V[v][k].short || V[v][k].label;
const statusHTML = (k, text) => `<span class="st ${k}">${esc(text ?? short("status", k))}</span>`;
const confHTML = (k) => k === "none" ? "" : `<span class="conf ${k}">${esc(lab("end_confidence", k))}</span>`;
const models = Object.fromEntries(D.models.map((m) => [m.id, m]));
const lanes = Object.fromEntries(D.lanes.map((l) => [l.id, l]));
const effEnd = (l) => l.ends.expected || l.ends.announced;
const isFree = (l) => l.status === "live" || l.status === "overdue" || l.status === "listed";
const slug = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const modelHref = (id) => `${D.root}models/${encodeURIComponent(id)}${D.ext}`;
const channelHref = (name) => `${D.root}channels/${slug(name)}${D.ext}`;
const mlink = (id) => `<a href="${modelHref(id)}">${esc(models[id].name)}</a>`;
const clink = (name) => `<a href="${channelHref(name)}">${esc(name)}</a>`;
const channels = [...new Set(D.lanes.map((l) => l.channel))];
const lanesOf = (mid) => D.lanes.filter((l) => l.model === mid);
const lanesOn = (name) => D.lanes.filter((l) => l.channel === name);
const eventsOf = (mid) => D.events.filter((e) => e.lanes.some((i) => lanes[i].model === mid));
const eventsOn = (name) => D.events.filter((e) => e.lanes.some((i) => lanes[i].channel === name));

/* events have stable anchors; dates that came from an event link to it */
const evId = (e) => `ev-${e.date.replace(/[^0-9]/g, "")}-${e.lanes[0]}`;
const findEv = (l, pred) => D.events.find((e) => e.lanes.includes(l.id) && pred(e));
const whenLink = (s, ev) => ev ? `<a class="when" href="#${evId(ev)}">${esc(absDate(s))}</a>` : esc(absDate(s));
const endedEvent = (l) => findEv(l, (e) => e.kind === "ended");
const startEvent = (l) => l.started.date && findEv(l, (e) => e.date === l.started.date);
const announceEvent = (l) => l.ends.announced && findEv(l, (e) => e.end_date === l.ends.announced);

/* the one place that turns a lane's end into words: {main, sub} */
function endInfo(l) {
  const conf = l.ends.confidence;
  if (l.status === "ended") {
    const e = endedEvent(l);
    return { main: e ? `ended ${relDays(pd(e.date).t) || absDate(e.date)}` : "ended", sub: e ? whenLink(e.date, e) : "" };
  }
  if (l.status === "unavailable") return { main: "not answering", sub: `at last check, ${esc(absDate(l.checked.date))}` };
  const end = effEnd(l);
  if (!end) {
    const se = startEvent(l);
    return { main: "no end announced", sub: l.started.date ? `free since ${whenLink(l.started.date, se)}` : "" };
  }
  const t = pd(end).t, n = daysTo(t);
  if (l.status === "overdue" && !l.ends.expected) {
    return { main: `${-n} day${-n === 1 ? "" : "s"} overdue`, sub: `${confHTML(conf)} end was ${whenLink(l.ends.announced, announceEvent(l))}` };
  }
  const main = n === 0 ? "ends today" : n > 0 ? `ends ${relDays(t) || absDate(end)}` : `end passed ${absDate(end)}`;
  let sub = `${confHTML(conf)} ${l.ends.expected ? esc(absDate(end)) : whenLink(end, announceEvent(l))}`;
  if (l.status === "overdue" && l.ends.announced) sub += ` · was ${whenLink(l.ends.announced, announceEvent(l))}`;
  return { main, sub };
}

/* chips: a channel (on model pages) or a model (on channel pages) with its state */
/* the state in words, so a chip never relies on colour alone: "free · ends in 4 days", "listed free · no end announced" */
const stateWords = (l) => {
  const main = endInfo(l).main;
  return l.status === "live" ? `free · ${main}` : l.status === "listed" ? `listed free · ${main}` : main;
};
/* a chip prints only the exception (an end, past end, ended, not answering); the icon carries the state, the tooltip says it in full */
const chipNote = (l) => { const m = endInfo(l).main; return m === "no end announced" ? "" : m; };
const chipTo = (href, text, l) => `<a class="chip" href="${href}" title="${esc(text + ": " + stateWords(l))}" aria-label="${esc(text + ", " + stateWords(l))}">${statusHTML(l.status, text)}${chipNote(l) ? `<small>${esc(chipNote(l))}</small>` : ""}</a>`;
const channelChip = (l) => chipTo(channelHref(l.channel), l.channel, l);
const modelChip = (l) => chipTo(modelHref(l.model), models[l.model].name, l);

/* our own measurements: the site's unique data */
function measuredHTML(l, badge = false) {
  const lo = l.limits_observed;
  if (!lo) return `<span class="muted">not measured</span>`;
  return `<span class="measured${badge ? " badge" : ""}">${I.bolt()}${esc(lo.text)}</span>`;
}
const checkedSub = (l) => {
  const age = -daysTo(pd(l.checked.date).t);
  return `<span class="sub">${esc(lab("check_method", l.checked.method))} · <span class="${age > 30 ? "stale" : ""}">${esc(absDate(l.checked.date))}${age > 30 ? " · stale" : ""}</span></span>`;
};
function policyHTML(k) {
  const icon = k === "zero_retention" ? I.lock() : k === "may_train" ? I.eye() : I.help();
  return `<span class="pol ${k}" title="${esc(lab("data_policy", k))}">${icon}${esc(short("data_policy", k))}</span>`;
}
const idHTML = (l) => l.model_id === "not recorded"
  ? `<span class="muted">not recorded</span>`
  : `<code class="id">${esc(l.model_id)}</code><button type="button" class="copy" data-copy="${esc(l.model_id)}" aria-label="Copy model ID ${esc(l.model_id)}">${I.copy()}</button>`;
const limitHTML = (l) => {
  const ls = l.limits_stated;
  const txt = ["unstated", "not checked"].includes(ls.text) ? `<span class="muted">${esc(ls.text)}</span>` : esc(ls.text);
  return ls.source ? `<a href="${esc(ls.source)}" target="_blank" rel="noopener">${txt}</a>` : txt;
};
/* AA: official label (links to AA) · EST band with evidence (ADR-004/006) · or not ranked */
const aaValue = (m) => m.aa_index.value != null ? m.aa_index.value : (m.est && m.est.status === "ok" ? m.est.center : null);
/* one ranking for every page: official AA = a point, EST = its band. A rank is a range wherever bands overlap
   (never a single #n for an estimate, ADR-006). Order: centre desc, official before EST, then name. */
const isEst = (m) => m.aa_index.value == null && !!(m.est && m.est.status === "ok");
const band = (m) => m.aa_index.value != null ? [m.aa_index.value, m.aa_index.value] : isEst(m) ? [m.est.low, m.est.high] : null;
const scored = D.models.filter(band).sort((a, b) => aaValue(b) - aaValue(a) || isEst(a) - isEst(b) || a.name.localeCompare(b.name));
function rankOf(m) {
  const me = band(m); if (!me) return null;
  const others = scored.filter((o) => o !== m).map(band);
  return { a: 1 + others.filter(([lo]) => lo > me[1]).length, b: 1 + others.filter(([, hi]) => hi > me[0]).length, est: isEst(m) };
}
const rankLabel = (r) => `${r.est ? "≈" : ""}#${r.a}${r.b > r.a ? "–" + r.b : ""}`;
function rankText(m) {
  const r = rankOf(m); if (!r) return "";
  return `${r.est ? "about " : ""}${rankLabel(r).replace("≈", "")} of ${scored.length} scored here${r.est ? " (estimate)" : ""}`;
}
function estPanel(m) {
  const e = m.est;
  const rows = e.evidence.map((c) => `<li>${c.implied != null ? `<b class="mono">≈${c.implied}</b> ` : ""}<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.benchmark === "aicodingdaily" ? "AI Coding Daily" : c.benchmark)}</a>: ${esc(c.score)}${c.variant ? ` <span class="muted">(${esc(c.variant)})</span>` : ""} · ${esc(c.source_type)}${c.implied != null ? ` · fit r=${c.r}, ${c.anchors} reference models` : ` · <span class="muted">not used: ${esc(c.why)}</span>`}</li>`).join("");
  const head = e.status === "ok"
    ? `Estimated from ${e.benchmarks} benchmark${e.benchmarks === 1 ? " (one source only: a rough guide)" : "s"}: centre ${e.center}${e.spread > 10 ? " · sources disagree widely" : ""}.`
    : `Not enough evidence yet: ${e.benchmarks} of the required benchmarks (rule: ${esc(D.est_rule)}).`;
  return `<div class="estpanel"><p>${head}</p><ul>${rows}</ul><p class="muted">An estimate, not an Artificial Analysis score. Method: <a href="https://github.com/dimpurr/freetokens/blob/main/METHOD.md">how EST works</a>.</p></div>`;
}
function aaHTML(m) {
  const a = m.aa_index;
  if (a.value != null) {
    const title = `Artificial Analysis Intelligence Index, ${absDate(a.date)}`;
    const inner = `<small>AA</small>${a.approx ? "≈" : ""}${a.value}`;
    return a.url ? `<a class="aa" href="${esc(a.url)}" target="_blank" rel="noopener" title="${esc(title)}">${inner}${I.ext()}</a>` : `<span class="aa" title="${esc(title)}">${inner}</span>`;
  }
  if (m.est) {
    const label = m.est.status === "ok" ? `${m.est.low}–${m.est.high}` : "—";
    return `<details class="estd"><summary class="aa est" title="Estimated AA index: tap for the evidence"><small>EST</small>${label} ${I.help()}</summary>${estPanel(m)}</details>`;
  }
  return `<span class="muted">${esc(a.note || "not ranked")}</span>`;
}
/* P7: one line under the score chip saying where the number comes from */
const aaSource = (m) => m.aa_index.value != null
  ? `<span class="sub">Artificial Analysis · ${esc(absDate(m.aa_index.date))}</span>`
  : isEst(m) ? `<span class="sub">${m.est.benchmarks} benchmark${m.est.benchmarks === 1 ? "" : "s"} · estimate</span>`
  : "";

/* compact key shown above tables */
const keyHTML = () => [
  ...Object.keys(V.status).map((k) => statusHTML(k)),
  `<span class="measured">${I.bolt()}tested by us</span>`,
  `<span class="pol zero_retention">${I.lock()}no retention</span>`,
  `<span class="pol may_train">${I.eye()}may train</span>`,
  `<span><span class="conf official">official</span> <span class="conf inferred">inferred</span> end date</span>`,
].map((x) => `<span>${x}</span>`).join("");

const legendHTML = () => [["status", "Status"], ["end_confidence", "End-date confidence"], ["check_method", "Checked by"], ["channel_type", "Channel type"], ["data_policy", "Data policy"]].map(([v, name]) =>
  `<div><h3>${name}</h3><dl>${Object.entries(V[v]).map(([k, o]) => `<dt>${v === "status" ? statusHTML(k, o.label) : esc(o.label)}</dt>${o.help ? `<dd>${esc(o.help)}</dd>` : ""}`).join("")}</dl></div>`
).join("");

/* ---------- lane chart: bars = free period, markers = events (tap to jump) ---------- */
function renderChart(el, rows, fit = false) {
  const ends = D.lanes.map((l) => effEnd(l) && pd(effEnd(l)).t).filter(Boolean);
  const starts = rows.map((l) => l.started.date && pd(l.started.date).t).filter(Boolean);
  const t0 = fit ? Math.min(todayT - 35 * DAY, Math.max(todayT - 120 * DAY, ...starts.map((t) => t - 3 * DAY))) : todayT - 35 * DAY;
  const t1 = Math.max(todayT + 14 * DAY, ...ends.map((t) => t + 4 * DAY));
  const x = (t) => ((Math.min(Math.max(t, t0), t1) - t0) / (t1 - t0)) * 100;
  const pct = (t) => x(t).toFixed(3) + "%";
  let ticks = "";
  const dow = new Date(t0).getUTCDay();
  for (let t = t0 + ((8 - dow) % 7) * DAY; t <= t1; t += 7 * DAY) ticks += `<div class="tick" style="left:${pct(t)}"><span>${MON[new Date(t).getUTCMonth()]} ${new Date(t).getUTCDate()}</span></div>`;
  let html = `<div class="lbl axis-l"></div><div class="axis">${ticks}<div class="todayline" style="left:${pct(todayT)}"><span>today</span></div></div>`;
  for (const l of rows) {
    const s = l.started.date ? pd(l.started.date).t : null;
    const ann = l.ends.announced ? pd(l.ends.announced).t : null;
    const end = effEnd(l) ? pd(effEnd(l)).t : null;
    const conf = l.ends.confidence;
    /* unknown start: begin at the model's earliest recorded start, never at the chart's edge */
    const sib = D.lanes.filter((x) => x.model === l.model && x.started.date).map((x) => pd(x.started.date).t);
    const from = s ?? (sib.length ? Math.min(...sib) : t0);
    let segs = "";
    if (l.status === "unavailable" || l.status === "ended") {
      const e = endedEvent(l), stop = e ? pd(e.date).t : todayT;
      segs += `<div class="seg past unavailable" style="left:${pct(from)};width:calc(${pct(stop)} - ${pct(from)})"></div>`;
      if (e) segs += `<div class="note" style="left:calc(${pct(stop)} + 8px)">ended ${esc(absDate(e.date).replace(" UTC", ""))}</div>`;
    } else {
      const pastEnd = l.status === "overdue" && ann ? ann : todayT;
      segs += `<div class="seg past" style="left:${pct(from)};width:calc(${pct(Math.min(pastEnd, todayT))} - ${pct(from)})"></div>`;
      if (l.status === "overdue" && ann) segs += `<div class="seg over" style="left:${pct(ann)};width:calc(${pct(todayT)} - ${pct(ann)})"></div>`;
      if (end && end > todayT) {
        segs += `<div class="seg fut ${conf}" style="left:${pct(todayT)};width:calc(${pct(end)} - ${pct(todayT)})"></div>`;
        segs += `<div class="cap ${conf}" style="left:${pct(end)}"></div>`;
        segs += `<div class="note" style="left:calc(${pct(end)} + 8px)">${esc(absDate(effEnd(l)).replace(/, \d\d:\d\d UTC/, ""))} · ${esc(lab("end_confidence", conf))}</div>`;
      } else if (!end) {
        segs += `<div class="seg fut none" style="left:${pct(todayT)};width:calc(${pct(t1)} - ${pct(todayT)})"></div>`;
        segs += `<div class="note" style="left:calc(${pct(todayT)} + 8px)">no end announced</div>`;
      } else if (l.status === "overdue") {
        segs += `<div class="note" style="left:calc(${pct(todayT)} + 8px)">no new date</div>`;
      }
    }
    if (s && s < t0) segs += `<div class="since">◀ since ${esc(absDate(l.started.date))}</div>`;
    if (!s) segs += `<div class="since" style="left:calc(${pct(from)} + 4px)">start not recorded</div>`;
    for (const e of D.events.filter((e) => e.lanes.includes(l.id))) {
      const t = pd(e.date).t; if (t < t0) continue;
      const tip = `${absDate(e.date)}: ${lab("event_kind", e.kind)}. ${e.text}`;
      segs += `<a class="ev ${e.kind}" href="#${evId(e)}" style="left:${pct(t)}" title="${esc(tip)}" aria-label="${esc(tip)}"></a>`;
    }
    html += `<div class="lbl"><div class="m">${mlink(l.model)}</div><div class="c">${clink(l.channel)} ${statusHTML(l.status)}</div></div><div class="trk">${segs}</div>`;
  }
  el.innerHTML = html;
  /* on narrow screens the chart scrolls: start with today in view, not the oldest week */
  const sc = el.parentElement;
  requestAnimationFrame(() => { if (sc.scrollWidth > sc.clientWidth) sc.scrollLeft = Math.max(0, sc.scrollWidth * (x(todayT) / 100) - sc.clientWidth * 0.55); });
}
const chartKey = [
  `<span><i style="background:var(--live)"></i>free so far</span>`,
  `<span><i style="background:repeating-linear-gradient(135deg,var(--overdue) 0 4px,var(--overdue-soft) 4px 8px)"></i>past announced end</span>`,
  `<span><i style="background:var(--live-soft);border:2px solid var(--live)"></i>official end ahead</span>`,
  `<span><i style="border:2px dashed var(--live)"></i>inferred end ahead</span>`,
  `<span><i style="background:linear-gradient(90deg,var(--live-soft),transparent)"></i>no end announced</span>`,
  `<span><i style="background:var(--off)"></i>ended / not answering</span>`,
  `<span>● event · ◆ end announced · tap one to see it</span>`,
].join("");

/* ---------- timeline grouped by UTC day; times link to the source ---------- */
function timelineHTML(evs) {
  const sorted = [...evs].sort((a, b) => pd(b.date).t - pd(a.date).t);
  let out = "", lastDay = null;
  for (const e of sorted) {
    const d = pd(e.date), x = new Date(d.t);
    const dayKey = d.p === "month" ? e.date : x.toISOString().slice(0, 10);
    if (dayKey !== lastDay) {
      lastDay = dayKey;
      const label = d.p === "month" ? absDate(e.date) : `${WD[x.getUTCDay()]}, ${MON[x.getUTCMonth()]} ${x.getUTCDate()}${x.getUTCFullYear() !== thisYear ? ", " + x.getUTCFullYear() : ""}`;
      const rel = d.p === "month" ? "" : relDays(Date.parse(dayKey + "T00:00Z"));
      out += `<div class="day">${esc(label)}${rel ? `<span>${esc(rel)}</span>` : ""}</div>`;
    }
    const time = d.p === "minute" ? x.toISOString().slice(11, 16) : "";
    const timeHTML = e.source.url ? `<a href="${esc(e.source.url)}" target="_blank" rel="noopener" title="Open the source">${time}</a>` : time;
    const src = e.source.url ? `<a href="${esc(e.source.url)}" target="_blank" rel="noopener">${esc(e.source.label)} ${I.ext()}</a>` : esc(e.source.label);
    out += `<div class="it" id="${evId(e)}"><div class="t">${timeHTML}</div><div class="b">
      <div class="h"><span class="k">${esc(lab("event_kind", e.kind))}</span>${e.lanes.map((i) => `<span class="lane">${mlink(lanes[i].model)} · ${clink(lanes[i].channel)}</span>${statusHTML(lanes[i].status)}`).join(" ")}</div>
      <div class="x">${esc(e.text)}${e.end_date ? ` <span class="muted">→ end date ${esc(absDate(e.end_date))}</span>` : ""}</div>
      <div class="s">Source: ${src}${e.source.note ? ` · ${esc(e.source.note)}` : ""}</div>
    </div></div>`;
  }
  return out || `<p class="muted" style="padding:12px 16px;margin:0">No events recorded.</p>`;
}

/* ---------- copy buttons ---------- */
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-copy]"); if (!b) return;
  const old = b.innerHTML;
  const done = () => { b.textContent = "copied"; setTimeout(() => (b.innerHTML = old), 1500); };
  const fallback = () => { const r = document.createRange(); r.selectNodeContents(b.previousElementSibling); const s = getSelection(); s.removeAllRanges(); s.addRange(r); b.textContent = "selected"; setTimeout(() => (b.innerHTML = old), 2500); };
  try { navigator.clipboard.writeText(b.dataset.copy).then(done, fallback); } catch (e) { fallback(); }
});

const stamp = () => `<span>data as of <b>${esc(absDate(D.built))}</b></span><span>today <b>${esc(absDate(new Date(now).toISOString().slice(0, 10)))}</b> UTC</span>`;
/* P3: catalogue size + freshness in one line (home) */
const metaStrip = () => `<span><b>${D.models.length}</b> models</span><span><b>${D.lanes.length}</b> lanes · <b>${D.lanes.filter(isFree).length}</b> free now</span><span><b>${channels.length}</b> channels</span><span><b>${D.events.length}</b> events</span>` + stamp();
