/* shared by every page; D is inlined by build.py */
const V = D.vocab;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const DAY = 86400000;

function pd(s) {
  if (!s) return null;
  if (/^\d{4}-\d{2}$/.test(s)) return { t: Date.parse(s + "-01T00:00Z"), p: "month" };
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return { t: Date.parse(s + "T00:00Z"), p: "day" };
  return { t: Date.parse(s.replace("Z", ":00Z")), p: "minute" };
}
function fd(s) {
  const d = pd(s); if (!d) return "";
  const iso = new Date(d.t).toISOString();
  return d.p === "month" ? iso.slice(0, 7) : d.p === "day" ? iso.slice(0, 10) : iso.slice(0, 10) + " " + iso.slice(11, 16) + " UTC";
}
const lab = (v, k) => V[v][k].label;
const icon = (v, k) => V[v][k].icon ? V[v][k].icon + " " : "";
const statusChip = (k) => `<span class="chip ${k}">${icon("status", k)}${esc(lab("status", k))}</span>`;
const confChip = (k) => `<span class="chip conf ${k}">${k === "none" ? "no end announced" : esc(lab("end_confidence", k))}</span>`;
const models = Object.fromEntries(D.models.map((m) => [m.id, m]));
const lanes = Object.fromEntries(D.lanes.map((l) => [l.id, l]));
const effEnd = (l) => l.ends.expected || l.ends.announced;
const modelHref = (id) => `${D.root}models/${encodeURIComponent(id)}.html`;
const mlink = (id) => `<a class="mlink" href="${modelHref(id)}">${esc(models[id].name)}</a>`;
const lanesOf = (mid) => D.lanes.filter((l) => l.model === mid);
const eventsOf = (mid) => D.events.filter((e) => e.lanes.some((i) => lanes[i].model === mid));
const endedEvent = (l) => D.events.find((e) => e.kind === "ended" && e.lanes.includes(l.id));

const now = Date.now();
const todayT = Date.parse(new Date(now).toISOString().slice(0, 10) + "T00:00Z");
const daysTo = (t) => Math.round((t - todayT) / DAY);

/* one-line state of a lane, used on chips and cards */
function laneState(l) {
  const end = effEnd(l);
  if (l.status === "ended") { const e = endedEvent(l); return e ? `ended ${fd(e.date).slice(5, 16)}` : "ended"; }
  if (l.status === "unavailable") return "not answering";
  if (!end) return "no end announced";
  const d = daysTo(pd(end).t);
  if (l.status === "overdue" && !l.ends.expected) return `past announced end ${fd(end).slice(5, 10)}`;
  return d < 0 ? `past end ${fd(end).slice(5, 10)}` : d === 0 ? `ends today` : `ends ${fd(end).slice(5, 10)} · ${d} day${d === 1 ? "" : "s"}`;
}
const laneChip = (l) => `<a class="chip ${l.status}" href="${modelHref(l.model)}" title="${esc(lab("status", l.status))}">${icon("status", l.status)}${esc(l.channel)} <small>${esc(laneState(l))}</small></a>`;

/* lane chart: bars = free period, markers = events */
function renderChart(el, rows, fit = false) {
  const ends = D.lanes.map((l) => effEnd(l) && pd(effEnd(l)).t).filter(Boolean);
  const starts = rows.map((l) => l.started.date && pd(l.started.date).t).filter(Boolean);
  const t0 = fit ? Math.min(todayT - 35 * DAY, Math.max(todayT - 120 * DAY, ...starts.map((t) => t - 3 * DAY))) : todayT - 35 * DAY;
  const t1 = Math.max(todayT + 14 * DAY, ...ends.map((t) => t + 4 * DAY));
  const x = (t) => ((Math.min(Math.max(t, t0), t1) - t0) / (t1 - t0)) * 100;
  const pct = (t) => x(t).toFixed(3) + "%";
  let ticks = "";
  const dow = new Date(t0).getUTCDay();
  for (let t = t0 + ((8 - dow) % 7) * DAY; t <= t1; t += 7 * DAY) ticks += `<div class="tick" style="left:${pct(t)}"><span>${new Date(t).toISOString().slice(5, 10)}</span></div>`;
  let html = `<div class="lbl axis-l"></div><div class="axis">${ticks}<div class="todayline" style="left:${pct(todayT)}"><span>today</span></div></div>`;
  for (const l of rows) {
    const s = l.started.date ? pd(l.started.date).t : null;
    const ann = l.ends.announced ? pd(l.ends.announced).t : null;
    const end = effEnd(l) ? pd(effEnd(l)).t : null;
    const conf = l.ends.confidence;
    const from = s ?? t0;
    let segs = "";
    if (l.status === "unavailable" || l.status === "ended") {
      const e = endedEvent(l), stop = e ? pd(e.date).t : todayT;
      segs += `<div class="seg past unavailable" style="left:${pct(from)};width:calc(${pct(stop)} - ${pct(from)})"></div>`;
      if (e) segs += `<div class="note" style="left:calc(${pct(stop)} + 6px)">ended ${esc(fd(e.date).slice(5, 16))}</div>`;
    } else {
      const pastEnd = l.status === "overdue" && ann ? ann : todayT;
      segs += `<div class="seg past" style="left:${pct(from)};width:calc(${pct(Math.min(pastEnd, todayT))} - ${pct(from)})"></div>`;
      if (l.status === "overdue" && ann) segs += `<div class="seg over" style="left:${pct(ann)};width:calc(${pct(todayT)} - ${pct(ann)})" title="Past announced end ${esc(fd(l.ends.announced))}"></div>`;
      if (end && end > todayT) {
        segs += `<div class="seg fut ${conf} ${l.status}" style="left:${pct(todayT)};width:calc(${pct(end)} - ${pct(todayT)})"></div>`;
        segs += `<div class="cap ${conf}" style="left:${pct(end)}" title="${esc(lab("end_confidence", conf))} end ${esc(fd(effEnd(l)))}"></div>`;
        segs += `<div class="note" style="left:calc(${pct(end)} + 6px)">${esc(fd(effEnd(l)).slice(5, 10))} ${esc(lab("end_confidence", conf))}</div>`;
      } else if (!end) {
        segs += `<div class="seg fut none" style="left:${pct(todayT)};width:calc(${pct(t1)} - ${pct(todayT)})"></div>`;
        segs += `<div class="note" style="left:calc(${pct(todayT)} + 6px)">no end announced</div>`;
      } else if (l.status === "overdue") {
        segs += `<div class="note" style="left:calc(${pct(todayT)} + 6px)">no new date</div>`;
      }
    }
    if (s && s < t0) segs += `<div class="since">◀ since ${esc(fd(l.started.date))}</div>`;
    if (!s) segs += `<div class="since">start not recorded</div>`;
    for (const e of D.events.filter((e) => e.lanes.includes(l.id))) {
      const t = pd(e.date).t; if (t < t0) continue;
      segs += `<div class="ev ${e.kind}" style="left:${pct(t)}" title="${esc(fd(e.date))}: ${esc(lab("event_kind", e.kind))}. ${esc(e.text)}"></div>`;
    }
    html += `<div class="lbl"><div class="m">${mlink(l.model)}</div><div class="c">${esc(l.channel)} ${statusChip(l.status)}</div></div><div class="trk">${segs}</div>`;
  }
  el.innerHTML = html;
}

const chartKey = [
  `<span><i style="background:var(--live)"></i>free so far</span>`,
  `<span><i style="background:repeating-linear-gradient(135deg,var(--overdue) 0 4px,var(--overdue-soft) 4px 8px)"></i>past announced end, still live</span>`,
  `<span><i style="background:var(--live-soft);border:2px solid var(--live)"></i>official end ahead</span>`,
  `<span><i style="border:2px dashed var(--live)"></i>inferred end ahead</span>`,
  `<span><i style="background:linear-gradient(90deg,var(--live-soft),transparent)"></i>no end announced</span>`,
  `<span><i style="background:var(--off)"></i>ended / not answering</span>`,
  `<span>● event · ◆ end announced</span>`,
].join("");

/* vertical event list, newest first */
function timelineHTML(evs) {
  return [...evs].sort((a, b) => pd(b.date).t - pd(a.date).t).map((e) => {
    const src = e.source.url ? `<a href="${esc(e.source.url)}" target="_blank" rel="noopener">${esc(e.source.label)}</a>` : esc(e.source.label);
    return `<div class="it"><div class="d">${esc(fd(e.date))}</div><div class="b">
      <div class="h"><span class="k">${esc(lab("event_kind", e.kind))}</span><span class="lanes-chips">${e.lanes.map((i) => `${mlink(lanes[i].model)} ${laneChip(lanes[i])}`).join(" ")}</span></div>
      <div class="t">${esc(e.text)}${e.end_date ? ` <span class="mono">→ ends ${esc(fd(e.end_date))}</span>` : ""}</div>
      <div class="s">Source: ${src}${e.source.note ? ` (${esc(e.source.note)})` : ""}</div>
    </div></div>`;
  }).join("") || `<p class="muted" style="padding:12px 16px;margin:0">No events recorded.</p>`;
}

function aaHTML(m) {
  const a = m.aa_index;
  return a.value != null ? `<b class="mono">${a.approx ? "≈ " : ""}${a.value}</b>` : `<span class="muted">${esc(a.note || "not ranked")}</span>`;
}

const stamp = () => `<span>Data as of <b>${esc(D.built)}</b></span><span>Today <b>${new Date(now).toISOString().slice(0, 10)}</b> (UTC)</span>`;
