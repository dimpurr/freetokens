#!/usr/bin/env python3
"""Validate data/*.json against schema/schema.json, then generate README.md tables and index.html.

    python3 build.py                 # validate + write README.md and index.html
    python3 build.py --check         # validate + fail if README.md / index.html are out of date
    python3 build.py --validate      # validate data/ only, write nothing (what contributors run)
    python3 build.py --fragment OUT  # also write the page without <html>/<head> wrappers (for hosts that add their own)
    python3 build.py --today 2026-10-04

Standard library only. Hand-written prose in README.md lives outside the <!-- BEGIN:x --> / <!-- END:x --> markers.
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / "schema/schema.json").read_text())
VOCAB = SCHEMA["vocab"]


def load(name):
    return json.loads((ROOT / f"data/{name}.json").read_text())


# ---------- dates ----------

def parse_date(s):
    """'2026-06' | '2026-09-23' | '2026-09-23T14:31Z' -> (datetime UTC, precision)."""
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return dt.datetime.strptime(s, "%Y-%m").replace(tzinfo=dt.timezone.utc), "month"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc), "day"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", s):
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc), "minute"
    raise ValueError(f"bad date {s!r}")


def fmt_date(s):
    d, p = parse_date(s)
    return {"month": d.strftime("%Y-%m"), "day": d.strftime("%Y-%m-%d"), "minute": d.strftime("%Y-%m-%d %H:%M UTC")}[p]


def day(s):
    return parse_date(s)[0].date()


def effective_end(lane):
    e = lane["ends"]
    return e.get("expected") or e.get("announced")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------- validation ----------

def get(obj, dotted):
    for k in dotted.split("."):
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def validate(lanes, events, models):
    errs = []
    tables = {"lanes": lanes, "events": events, "models": models}
    for tname, rows in tables.items():
        spec = SCHEMA["tables"][tname]
        for i, row in enumerate(rows):
            where = f"{tname}[{row.get('id', i)}]"
            for f in spec["required"]:
                if f not in row:
                    errs.append(f"{where}: missing field {f!r}")
            for f, vname in spec.get("vocab_fields", {}).items():
                v = get(row, f)
                if v not in VOCAB[vname]:
                    errs.append(f"{where}: {f}={v!r} is not in vocab {vname!r} ({', '.join(VOCAB[vname])})")
            for k, v in row.items():
                if v == "":
                    errs.append(f"{where}: {k} is an empty string; write the unknown explicitly")

    for m in models:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", m["id"]):
            errs.append(f"models[{m['id']}]: id must be lowercase letters, digits, '.' or '-' (it becomes a URL)")
    for m in models:
        a = m["aa_index"]
        if a.get("value") is not None and not str(a.get("url", "")).startswith("https://artificialanalysis.ai/"):
            errs.append(f"models[{m['id']}]: an AA index value needs aa_index.url (its artificialanalysis.ai page)")
    model_ids = {m["id"] for m in models}
    lane_ids = {l["id"] for l in lanes}
    for coll, name in ((lanes, "lanes"), (models, "models")):
        ids = [r["id"] for r in coll]
        for dup in {x for x in ids if ids.count(x) > 1}:
            errs.append(f"{name}: duplicate id {dup!r}")

    types, slugs = {}, {}
    for l in lanes:
        types.setdefault(l["channel"], set()).add(l["type"])
        slugs.setdefault(slug(l["channel"]), set()).add(l["channel"])
    for c, ts in types.items():
        if len(ts) > 1:
            errs.append(f"channel {c!r}: its lanes disagree on type ({', '.join(sorted(ts))}); one channel has one type")
    for sl, names in slugs.items():
        if len(names) > 1:
            errs.append(f"channels {sorted(names)} share the page name {sl!r}; rename one")

    by_lane = {}
    for e in events:
        try:
            parse_date(e["date"])
        except ValueError as x:
            errs.append(f"events[{e['date']}]: {x}")
        for lid in e["lanes"]:
            if lid not in lane_ids:
                errs.append(f"events[{e['date']}]: unknown lane {lid!r}")
            by_lane.setdefault(lid, []).append(e)
        if not (e["source"].get("url") or e["source"].get("label")):
            errs.append(f"events[{e['date']}]: source needs a url or a label")

    for l in lanes:
        w = f"lanes[{l['id']}]"
        if l["model"] not in model_ids:
            errs.append(f"{w}: unknown model {l['model']!r}")
        evs = by_lane.get(l["id"], [])
        s = l["started"].get("date")
        if s is None and not l["started"].get("note"):
            errs.append(f"{w}: started.date is null; add started.note (e.g. 'not recorded')")
        if s and not any(e["date"] == s and e["kind"] in ("announced", "listed", "available") for e in evs):
            errs.append(f"{w}: started {s} has no matching announced/listed/available event")
        e_ = l["ends"]
        if e_.get("announced") and not any(e.get("end_date") == e_["announced"] for e in evs):
            errs.append(f"{w}: announced end {e_['announced']} has no event carrying end_date")
        if (effective_end(l) is None) != (e_["confidence"] == "none"):
            errs.append(f"{w}: ends.confidence must be 'none' exactly when no end date is given")
        checked = day(l["checked"]["date"])
        ann = e_.get("announced")
        if l["status"] == "live" and ann and day(ann) < checked:
            errs.append(f"{w}: status 'live' but announced end {ann} is before the check on {checked}; use 'overdue'")
        if l["status"] == "ended" and not any(e["kind"] == "ended" for e in evs):
            errs.append(f"{w}: status 'ended' needs an 'ended' event with the date it stopped")
        if l["status"] == "overdue" and not (ann and day(ann) < checked):
            errs.append(f"{w}: status 'overdue' needs an announced end before the check date")
        for f in ("limits_stated",):
            if l[f] is not None and not l[f].get("text"):
                errs.append(f"{w}: {f}.text is required")
    bench, anchors = load_optional("benchmarks", {}), load_optional("anchors", [])
    for c in bench.get("claims", []):
        if c["model"] not in model_ids:
            errs.append(f"benchmarks.claims: unknown model {c['model']!r}")
        if not str(c.get("url", "")).startswith("http"):
            errs.append(f"benchmarks.claims[{c['model']}/{c['benchmark']}]: needs a source url")
    for a in anchors:
        if not str(a.get("aa_url", "")).startswith("https://artificialanalysis.ai/"):
            errs.append(f"anchors[{a.get('name')}]: needs its artificialanalysis.ai url")
    return errs



def validate_channels(channels, lanes):
    """data/channels.json: one record per channel that has lanes; entry cost with its source (cost badges)."""
    errs = []
    spec = SCHEMA["tables"]["channels"]
    names = [c.get("name") for c in channels]
    for c in channels:
        w = f"channels[{c.get('name')}]"
        for f in spec["required"]:
            if f not in c:
                errs.append(f"{w}: missing field {f!r}")
        k = get(c, "entry.kind")
        if k not in VOCAB["entry_kind"]:
            errs.append(f"{w}: entry.kind={k!r} is not in vocab 'entry_kind' ({', '.join(VOCAB['entry_kind'])})")
        if k in ("subscription", "topup") and not isinstance(get(c, "entry.usd"), (int, float)):
            errs.append(f"{w}: a {k} entry needs entry.usd")
        if not str(get(c, "source.url") or "").startswith("http"):
            errs.append(f"{w}: source.url is required")
        a = c.get("access") or {}
        if a.get("form") not in VOCAB["access_form"]:
            errs.append(f"{w}: access.form={a.get('form')!r} is not in vocab 'access_form'")
        if a.get("form") == "api" and not a.get("protocols"):
            errs.append(f"{w}: an api channel needs access.protocols")
        for x in a.get("protocols", []):
            if x not in VOCAB["protocol"]:
                errs.append(f"{w}: access.protocols has {x!r}, not in vocab 'protocol'")
        for x in a.get("rules", []):
            if x not in VOCAB["access_rule"]:
                errs.append(f"{w}: access.rules has {x!r}, not in vocab 'access_rule'")
        if not str(get(a, "source.url") or "").startswith("http"):
            errs.append(f"{w}: access.source.url is required")
    for dup in {n for n in names if names.count(n) > 1}:
        errs.append(f"channels: duplicate {dup!r}")
    for c in sorted({l["channel"] for l in lanes} - set(names)):
        errs.append(f"channel {c!r} has lanes but no record in data/channels.json")
    for n in sorted(set(names) - {l["channel"] for l in lanes}):
        errs.append(f"channels[{n}]: no lanes use this channel")
    return errs


def entry_text(c):
    """README / page wording for a channel's cost to start: "$0 · account", "$10/month plan first", "$20 top-up first"."""
    e = c["entry"]
    if e["kind"] == "subscription":
        return f"${e['usd']:g}/{e['period']} plan first"
    if e["kind"] == "topup":
        return f"${e['usd']:g} top-up first"
    return VOCAB["entry_kind"][e["kind"]]["short"]


def access_text(c):
    """"API · OpenAI chat" / "API · 3 formats" / "CLI only", plus "human only" when automation is banned."""
    a = c["access"]
    s = VOCAB["access_form"][a["form"]]["label"]
    if a["form"] == "api":
        s += " · " + (VOCAB["protocol"][a["protocols"][0]]["label"] if len(a["protocols"]) == 1 else f"{len(a['protocols'])} formats")
    return s + "".join(" · " + VOCAB["access_rule"][r]["label"] for r in a.get("rules", []))


# ---------- EST: estimated AA index (ADR-004 method v1, ADR-006 ranking) ----------

def load_optional(name, default):
    f = ROOT / f"data/{name}.json"
    return json.loads(f.read_text()) if f.exists() else default


def estimate(models, bench, anchors):
    """Returns {model_id: est} for models without an official AA index. Pure function of data/ + schema est_rules."""
    import statistics as st
    R = SCHEMA["est_rules"]
    fits = {}
    for bid, b in bench.get("benchmarks", {}).items():
        pts = [(a["scores"][bid]["score"], a["aa_index"]) for a in anchors if bid in a.get("scores", {})]
        if len(pts) < R["min_anchors"]:
            fits[bid] = {"ok": False, "why": f"only {len(pts)} reference models (need {R['min_anchors']})", "n": len(pts)}
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mx, my = st.mean(xs), st.mean(ys)
        slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x in xs)
        r = st.correlation(xs, ys)
        fits[bid] = {"ok": r >= R["min_r"], "a": my - slope * mx, "b": slope, "r": round(r, 3), "n": len(pts),
                     "why": None if r >= R["min_r"] else f"correlation {r:.2f} below {R['min_r']}"}
    out = {}
    for m in models:
        if m["aa_index"].get("value") is not None:
            continue
        claims = [c for c in bench.get("claims", []) if c["model"] == m["id"]]
        if not claims:
            continue
        used, listed = [], []
        for c in claims:
            f = fits.get(c["benchmark"])
            if c.get("excluded"):
                listed.append(dict(c, implied=None, why=c["excluded"]))
            elif not f or not f["ok"]:
                listed.append(dict(c, implied=None, why=(f or {}).get("why") or "no reference models for this benchmark"))
            else:
                used.append(dict(c, implied=round(f["a"] + f["b"] * c["score"], 1), r=f["r"], anchors=f["n"],
                                 weight=R["weights"].get(c["source_type"], 0.5)))
        benches = {c["benchmark"] for c in used}
        sources = {c["url"].split("/")[2] for c in used}
        e = {"evidence": used + listed, "benchmarks": len(benches), "sources": len(sources),
             "rule": f"needs {R['min_benchmarks']} benchmarks from {R['min_sources']} independent sources"}
        if len(benches) >= R["min_benchmarks"] and len(sources) >= R["min_sources"]:
            ws = sorted((c["implied"], c["weight"]) for c in used)
            half, acc, center = sum(w for _, w in ws) / 2, 0, ws[-1][0]
            for v, w in ws:
                acc += w
                if acc >= half:
                    center = v
                    break
            low = round(center - R["band_width"] / 2)
            e.update(status="ok", center=round(center, 1), low=low, high=low + R["band_width"],
                     spread=round(max(c["implied"] for c in used) - min(c["implied"] for c in used), 1))
        else:
            e["status"] = "insufficient"
        out[m["id"]] = e
    return out, fits


# ---------- markdown ----------

def md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(md_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def link(text, url):
    return f"[{text}]({url})" if url else text


def label(vname, key, icon=False):
    v = VOCAB[vname][key]
    return (v.get("icon", "") + " " if icon and v.get("icon") else "") + v["label"]


def ends_text(l):
    e = l["ends"]
    parts = []
    if e.get("announced"):
        parts.append(f"announced {fmt_date(e['announced'])}")
    if e.get("expected"):
        parts.append(f"expected {fmt_date(e['expected'])}")
    txt = " · ".join(parts) or "—"
    txt += f" ({label('end_confidence', e['confidence'])})"
    if e.get("note"):
        txt += f"; {e['note']}"
    return txt


def md_legend():
    lines = []
    for vname, title in (("status", "Status"), ("end_confidence", "End-date confidence"),
                         ("check_method", "Checked by"), ("channel_type", "Channel type")):
        items = [f"**{label(vname, k, icon=True)}**" + (f": {v['help']}" if v.get("help") else "")
                 for k, v in VOCAB[vname].items()]
        lines.append(f"- **{title}:** " + " · ".join(items))
    return "\n".join(lines)


def md_soon(lanes, models, today):
    mname = {m["id"]: m["name"] for m in models}
    rows = []
    for l in lanes:
        end = effective_end(l)
        if l["status"] in ("ended", "unavailable") or not end:
            continue
        d = (day(end) - today).days
        if l["status"] == "overdue" and not l["ends"].get("expected"):
            when = f"past announced end ({fmt_date(end)}), can stop any time"
        elif d < 0:
            when = f"{fmt_date(end)} (passed)"
        else:
            when = f"{fmt_date(end)} · " + ("today" if d == 0 else f"in {d} day{'s' if d != 1 else ''}")
        rows.append((day(end), [f"{mname[l['model']]}", l["channel"], when, label("end_confidence", l["ends"]["confidence"])]))
    rows.sort(key=lambda r: r[0])
    return md_table(["Model", "Channel", "Ends", "Confidence"], [r[1] for r in rows])


def md_lanes(lanes, models):
    mname = {m["id"]: m["name"] for m in models}
    rows = []
    for l in lanes:
        ls = l["limits_stated"]
        lo = l["limits_observed"]
        s = l["started"]
        rows.append([
            mname[l["model"]], l["channel"], label("channel_type", l["type"]),
            f"`{l['model_id']}`" if l["model_id"] != "not recorded" else "not recorded",
            l["free_condition"],
            link(ls["text"], ls.get("source")),
            f"{lo['text']} ({lo['date']})" if lo else "not measured",
            fmt_date(s["date"]) if s.get("date") else s.get("note"),
            ends_text(l),
            label("data_policy", l["data_policy"]),
            label("status", l["status"], icon=True),
            f"{l['checked']['date']} · {label('check_method', l['checked']['method'])}",
        ])
    return md_table(["Model", "Channel", "Type", "Model ID", "Free condition", "Limits (stated)", "Limits (observed)",
                     "Started", "Ends", "Data policy", "Status", "Checked"], rows)


def md_events(events, lanes, models):
    mname = {m["id"]: m["name"] for m in models}
    lane = {l["id"]: l for l in lanes}
    rows = []
    for e in sorted(events, key=lambda e: parse_date(e["date"])[0], reverse=True):
        who = ", ".join(f"{mname[lane[i]['model']]} · {lane[i]['channel']}" for i in e["lanes"])
        src = link(e["source"]["label"], e["source"].get("url"))
        if e["source"].get("note"):
            src += f" ({e['source']['note']})"
        text = e["text"] + (f" → ends {fmt_date(e['end_date'])}" if e.get("end_date") else "")
        rows.append([fmt_date(e["date"]), who, label("event_kind", e["kind"]), text, src])
    return md_table(["Date", "Lane", "Event", "Detail", "Source"], rows)


def md_models(models, lanes, events):
    lane_end = {}
    for e in events:
        if e["kind"] == "ended":
            for i in e["lanes"]:
                lane_end[i] = e["date"]

    def free_on(m):
        out = []
        for l in lanes:
            if l["model"] != m["id"]:
                continue
            st = l["status"]
            if st == "ended":
                tail = f"ended {fmt_date(lane_end[l['id']])[:10]}" if l["id"] in lane_end else "ended"
            elif st == "unavailable":
                tail = "not answering"
            elif st == "overdue" and not l["ends"].get("expected"):
                tail = f"past announced end {fmt_date(effective_end(l))[:10]}"
            elif effective_end(l):
                tail = f"ends {fmt_date(effective_end(l))[:10]}"
            else:
                tail = "no end announced"
            out.append(f"{VOCAB['status'][st]['icon']} {l['channel']} ({tail})")
        return " · ".join(out) or "—"

    def live(m):
        return any(l["model"] == m["id"] and l["status"] in ("live", "overdue", "listed") for l in lanes)

    rows = []
    for m in sorted(models, key=lambda m: (not live(m), -(m["aa_index"].get("value") or (m.get("est") or {}).get("center") or -1))):
        a = m["aa_index"]
        if a.get("value") is not None:
            aa = ("≈ " if a.get("approx") else "") + str(a["value"])
        elif m.get("est", {}).get("status") == "ok":
            aa = f"EST {m['est']['low']}–{m['est']['high']} (estimate)"
        elif m.get("est"):
            aa = f"EST — ({m['est']['benchmarks']} benchmark so far)"
        else:
            aa = a.get("note", "not ranked")
        n = sum(1 for e in events if any(next(l for l in lanes if l["id"] == i)["model"] == m["id"] for i in e["lanes"]))
        rows.append([f"[{m['name']}]({SITE}/models/{m['id']})", free_on(m), str(n), f"{aa} ({a['date']})", m["context"], label("image_input", m["image_input"]), m["maker"], m.get("notes") or "—"])
    return md_table(["Model", "Free on", "Events", "AA index", "Context", "Image input", "Maker", "Notes"], rows)


def md_channels(lanes, models, today, chans):
    cinfo = {c["name"]: c for c in chans}
    mname = {m["id"]: m["name"] for m in models}
    rows = []
    for c in sorted({l["channel"] for l in lanes}):
        ls = [l for l in lanes if l["channel"] == c]
        free = [l for l in ls if l["status"] in ("live", "overdue", "listed")]
        up = sorted((l for l in free if effective_end(l) and day(effective_end(l)) >= today), key=lambda l: day(effective_end(l)))
        nxt = f"{mname[up[0]['model']]} · {fmt_date(effective_end(up[0]))[:10]} ({label('end_confidence', up[0]['ends']['confidence'])})" if up else "none announced"
        models_ = " · ".join(f"{VOCAB['status'][l['status']]['icon']} {mname[l['model']]}" for l in ls)
        rows.append((-len(free), c, [f"[{c}]({SITE}/channels/{slug(c)})", label("channel_type", ls[0]["type"]), f"[{entry_text(cinfo[c])}]({cinfo[c]['source']['url']})", f"[{access_text(cinfo[c])}]({cinfo[c]['access']['source']['url']})", f"{len(free)} / {len(ls)}", nxt, models_]))
    rows.sort()
    return md_table(["Channel", "Type", "To start", "Access", "Free now", "Next end", "Models"], [r[2] for r in rows])


def render_readme(text, sections):
    for key, body in sections.items():
        pat = re.compile(rf"(<!-- BEGIN:{key} -->\n)(?:.*?\n)?(<!-- END:{key} -->)", re.S)
        if not pat.search(text):
            sys.exit(f"README.md is missing the <!-- BEGIN:{key} --> / <!-- END:{key} --> markers")
        text = pat.sub(lambda m: m.group(1) + "<!-- generated by build.py from data/ — do not edit by hand -->\n" + body + "\n" + m.group(2), text)
    return text


# ---------- html ----------

SITE = "https://freetokens.fyi"
REPO = "https://github.com/dimpurr/freetokens"
BRAND = ('<a class="brand" href="__HOME__"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>'
         '<span class="word">freetokens</span></a>')
GH = (f'<a class="gh" href="{REPO}" target="_blank" rel="noopener" title="Data and code on GitHub: corrections and new lanes welcome">'
      '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 '
      '0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 '
      '2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 '
      '2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 '
      '1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg><span>Contribute</span></a>')
FONTS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
"""
FAVICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0a7f8a"/>'
               '<path d="M35 8 14 36h15l-3 20 23-30H34z" fill="#fff"/></svg>')


# ---------- SEO: titles, descriptions, structured data (all derived from data/) ----------

def clip(s, n=158):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:·") + "…"


FREE = ("live", "overdue", "listed")


def seo_home(lanes, models, today):
    chans = sorted({l["channel"] for l in lanes})
    free = [l for l in lanes if l["status"] in FREE]
    title = "Free LLMs and APIs: where they are free and until when | freetokens"
    desc = clip(f"{len(free)} free LLM lanes across {len(chans)} channels ({', '.join(chans[:4])}…): end dates, takedowns and "
                f"limits we measured ourselves. Every fact sourced and dated; updated {today:%b %-d, %Y}.")
    return title, desc


def seo_model(m, lanes):
    ml = [l for l in lanes if l["model"] == m["id"]]
    free = [l for l in ml if l["status"] in FREE]
    title = f"{m['name']} free: {len(free)} of {len(ml)} channels, end dates and limits | freetokens"
    nxt = sorted((l for l in free if effective_end(l)), key=lambda l: effective_end(l))
    a = m["aa_index"]
    parts = [f"Where {m['name']} is free right now: {', '.join(l['channel'] for l in free) or 'no channel at the moment'}."]
    if nxt:
        parts.append(f"Next end: {nxt[0]['channel']}, {fmt_date(effective_end(nxt[0]))[:10]}.")
    if a.get("value") is not None:
        parts.append(f"AA index {a['value']}.")
    parts.append(f"{m['context']} context. Sources and dates for every fact.")
    return title, clip(" ".join(parts))


def seo_channel(c, lanes, models):
    cl = [l for l in lanes if l["channel"] == c]
    free = [l for l in cl if l["status"] in FREE]
    names = {m["id"]: m["name"] for m in models}
    title = f"Free models on {c}: {len(free)} now, end dates and limits | freetokens"
    desc = clip(f"{len(free)} of {len(cl)} tracked models free on {c} ({label('channel_type', cl[0]['type'])}): "
                f"{', '.join(names[l['model']] for l in free) or 'none right now'}. End dates, takedowns and limits, with sources.")
    return title, desc


def jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def crumbs(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)]}


def head_html(title, desc, url, today, extra_ld, og_image):
    return (f'<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'<title>{html.escape(title)}</title>\n<meta name="description" content="{html.escape(desc)}">\n'
            f'<link rel="canonical" href="{url}">\n<meta name="robots" content="index, follow, max-image-preview:large">\n'
            f'<meta name="theme-color" content="#0a7f8a">\n<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
            f'<link rel="alternate" type="application/atom+xml" title="freetokens: free LLM events" href="{SITE}/feed.xml">\n'
            f'<meta property="og:type" content="website">\n<meta property="og:site_name" content="freetokens">\n'
            f'<meta property="og:title" content="{html.escape(title)}">\n<meta property="og:description" content="{html.escape(desc)}">\n'
            f'<meta property="og:url" content="{url}">\n<meta property="og:image" content="{og_image}">\n'
            f'<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n<meta name="twitter:title" content="{html.escape(title)}">\n'
            f'<meta name="twitter:description" content="{html.escape(desc)}">\n<meta name="twitter:image" content="{og_image}">\n'
            + "\n".join(jsonld(x) for x in extra_ld) + "\n" + FONTS)


# ---------- pages ----------

SHARED_KEYS = ("lanes", "events", "models", "chans", "vocab", "built", "ext", "est_rule")


def render_body(template, payload, root, home, shared=False):
    """shared=True (deployed site): the dataset and common.js come from /assets/*.js, cached across pages."""
    t = ROOT / "templates"
    common = (t / "common.js").read_text()
    body = (t / template).read_text().replace("__BRAND__", BRAND).replace("__GH__", GH).replace("__HOME__", home).replace("__ROOT__", root)
    if shared:
        page = {k: v for k, v in payload.items() if k not in SHARED_KEYS}
        boot = (f'<script src="/assets/data.js?v={ASSET_V}"></script>\n<script>const D = Object.assign({{}}, window.FT_DATA, '
                f'{json.dumps(page, ensure_ascii=False)});</script>\n<script src="/assets/common.js?v={ASSET_V}"></script>\n<script>')
        return body.replace("<script>\n/*__COMMON__*/", boot, 1)
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return body.replace("/*__COMMON__*/", f"const D = {data};\n" + common)


def full_doc(head, body):
    css = (ROOT / "templates" / "style.css").read_text()
    return f'<!doctype html>\n<html lang="en">\n<head>\n{head}<style>\n{css}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n'


ASSET_V = "0"
INDEXNOW_KEY = "f7c3a9e14b2d4c6e8a0b1d3f5e7c9a2b"


def build_pages(lanes, events, models, today, mode):
    """mode 'preview': relative .html links (repo, file://, artifact). mode 'site': clean absolute URLs for freetokens.fyi."""
    site = mode == "site"
    ext = "" if site else ".html"
    est, _ = estimate(models, load_optional("benchmarks", {}), load_optional("anchors", []))
    models = [dict(m, est=est[m["id"]]) if m["id"] in est else m for m in models]
    R = SCHEMA["est_rules"]
    base = {"lanes": lanes, "events": events, "models": models, "chans": load_optional("channels", []), "vocab": VOCAB, "built": today.isoformat(), "ext": ext,
            "est_rule": f"{R['min_benchmarks']} benchmarks from {R['min_sources']} independent sources, each fitted on ≥{R['min_anchors']} reference models with r ≥ {R['min_r']}"}
    og = f"{SITE}/og.png"
    pages = {}  # relative output path -> (head, body)
    names = {m["id"]: m["name"] for m in models}
    chans = sorted({l["channel"] for l in lanes})

    title, desc = seo_home(lanes, models, today)
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "freetokens", "url": SITE + "/",
           "description": desc},
          {"@context": "https://schema.org", "@type": "Dataset", "name": "freetokens: free LLM lanes, end dates and measured limits",
           "description": desc, "url": SITE + "/", "sameAs": REPO, "isAccessibleForFree": True,
           "license": "https://creativecommons.org/licenses/by/4.0/", "dateModified": today.isoformat(),
           "creator": {"@type": "Person", "name": "dimpurr", "url": "https://github.com/dimpurr"},
           "keywords": ["free LLM", "free AI models", "free LLM API", "stealth models", "OpenRouter free models", "coding agents"],
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                             "contentUrl": f"https://raw.githubusercontent.com/dimpurr/freetokens/main/data/{n}.json"} for n in ("lanes", "events", "models")]},
          {"@context": "https://schema.org", "@type": "ItemList", "name": "Models tracked on freetokens",
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": m["name"], "url": f"{SITE}/models/{m['id']}"}
                               for i, m in enumerate(models)]}]
    home_href = "/" if site else "index.html"
    pages["index.html"] = (head_html(title, desc, SITE + "/", today, ld, og),
                           render_body("home.html", dict(base, root="/" if site else ""), "/" if site else "", home_href, site))
    sub_root, sub_home = ("/", "/") if site else ("../", "../index.html")
    for m in models:
        title, desc = seo_model(m, lanes)
        url = f"{SITE}/models/{m['id']}"
        ld = [crumbs([("freetokens", SITE + "/"), ("Models", SITE + "/#h-models"), (m["name"], url)]),
              {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url, "description": desc,
               "dateModified": today.isoformat(), "about": {"@type": "Thing", "name": m["name"]}}]
        pages[f"models/{m['id']}.html"] = (head_html(title, desc, url, today, ld, og),
                                            render_body("model.html", dict(base, root=sub_root, model=m["id"]), sub_root, sub_home, site))
    for c in chans:
        title, desc = seo_channel(c, lanes, models)
        url = f"{SITE}/channels/{slug(c)}"
        ld = [crumbs([("freetokens", SITE + "/"), ("Channels", SITE + "/#h-channels"), (c, url)]),
              {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url, "description": desc,
               "dateModified": today.isoformat()}]
        pages[f"channels/{slug(c)}.html"] = (head_html(title, desc, url, today, ld, og),
                                              render_body("channel.html", dict(base, root=sub_root, channel=c), sub_root, sub_home, site))
    if site:
        pages["__base__"] = base
        title = "How freetokens works: lanes, checks, and the EST estimate | freetokens"
        desc = "What a lane, status and end-date confidence mean, how 'Tested by us' limits are measured, and how the EST estimate of the AA index is computed."
        pages["methodology.html"] = (head_html(title, desc, SITE + "/methodology", today, [crumbs([("freetokens", SITE + "/"), ("Methodology", SITE + "/methodology")])], og),
                                     '<div class="topbar"><div class="in">' + BRAND.replace("__HOME__", "/") + '<nav aria-label="Sections"><a href="/#h-models">Models</a><a href="/#h-channels">Channels</a><a href="/#h-tl">Timeline</a></nav>' + GH + '</div></div>'
                                     + '<div class="wrap prose">' + md_to_html((ROOT / "METHOD.md").read_text()) + '</div>')
    return pages


def md_to_html(md):
    """Small Markdown subset for METHOD.md: #/## headings, paragraphs, - and 1. lists, **bold**, `code`, [links](url)."""
    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
        return re.sub(r"\[(.+?)\]\((.+?)\)", lambda m: f'<a href="{m.group(2) if m.group(2).startswith("http") else REPO + "/blob/main/" + m.group(2)}">{m.group(1)}</a>', t)
    out, lst = [], None
    for line in md.splitlines() + [""]:
        m = re.match(r"^(\s*)(-|\d+\.)\s+(.*)", line)
        if m:
            tag = "ul" if m.group(2) == "-" else "ol"
            if lst != tag:
                if lst: out.append(f"</{lst}>")
                out.append(f"<{tag}>"); lst = tag
            out.append(f"<li>{inline(m.group(3))}</li>"); continue
        if lst and line.strip() == "":
            out.append(f"</{lst}>"); lst = None
        if line.startswith("# "): out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "): out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.strip(): out.append(f"<p>{inline(line)}</p>")
    return "\n".join(out)


def site_extras(pages, lanes, events, models, today):
    """robots.txt, sitemap.xml, favicon, 404 page: only for the deployed site."""
    def lastmod(path):
        if path.startswith("models/"):
            mid = path[7:-5]
            ds = [l["checked"]["date"] for l in lanes if l["model"] == mid] + [e["date"][:10] for e in events if any(lanes_by_id[i]["model"] == mid for i in e["lanes"])]
        elif path.startswith("channels/"):
            cs = path[9:-5]
            ds = [l["checked"]["date"] for l in lanes if slug(l["channel"]) == cs] + [e["date"][:10] for e in events if any(slug(lanes_by_id[i]["channel"]) == cs for i in e["lanes"])]
        else:
            ds = [today.isoformat()]
        return max(d for d in ds if len(d) == 10) if ds else today.isoformat()
    lanes_by_id = {l["id"]: l for l in lanes}
    urls = []
    for p in sorted(pages):
        loc = SITE + "/" if p == "index.html" else f"{SITE}/{p[:-5]}"
        urls.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod(p)}</lastmod></url>")
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>\n"
    robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
    notfound = full_doc(
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Not found | freetokens</title>\n'
        '<meta name="robots" content="noindex">\n<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n' + FONTS,
        '<div class="wrap"><header class="intro"><h1>Page not found</h1><p>This page doesn\'t exist (models and channels can be renamed). '
        'Start from the <a href="/">home page</a>, or browse <a href="/#h-models">models</a> and <a href="/#h-channels">channels</a>.</p></header></div>')
    names = {m["id"]: m["name"] for m in models}
    free = [l for l in lanes if l["status"] in FREE]
    llms = (f"# freetokens\n\n> Which LLMs you can use for free right now, through which channel, and until when. "
            f"{len(free)} free lanes across {len({l['channel'] for l in lanes})} channels; every fact dated and sourced. Data under CC BY 4.0.\n\n"
            f"## Data (machine-readable)\n\n- [lanes.json](https://raw.githubusercontent.com/dimpurr/freetokens/main/data/lanes.json): one model × channel × free condition, with status, dates and limits\n"
            f"- [events.json](https://raw.githubusercontent.com/dimpurr/freetokens/main/data/events.json): dated events with sources\n"
            f"- [models.json](https://raw.githubusercontent.com/dimpurr/freetokens/main/data/models.json): models, AA index, context, image input\n"
            f"- [Atom feed of events]({SITE}/feed.xml)\n\n## Docs\n\n- [Methodology]({SITE}/methodology): statuses, checks, the EST estimate\n"
            f"- [Contributing]({REPO}/blob/main/CONTRIBUTING.md)\n\n## Models\n\n"
            + "\n".join(f"- [{m['name']}]({SITE}/models/{m['id']})" for m in models)
            + "\n\n## Channels\n\n" + "\n".join(f"- [{c}]({SITE}/channels/{slug(c)})" for c in sorted({l['channel'] for l in lanes})) + "\n")
    def x(t):
        return html.escape(str(t), quote=True)
    entries = []
    for e in sorted(events, key=lambda e: parse_date(e["date"])[0], reverse=True)[:50]:
        l0 = lanes_by_id[e["lanes"][0]]
        when = parse_date(e["date"])[0].strftime("%Y-%m-%dT%H:%M:%SZ")
        link = f"{SITE}/models/{l0['model']}#ev-{re.sub(r'[^0-9]', '', e['date'])}-{e['lanes'][0]}"
        title = f"{label('event_kind', e['kind'])}: {names[l0['model']]} on {l0['channel']}"
        body = e["text"] + (f" (end date {fmt_date(e['end_date'])})" if e.get("end_date") else "") + f". Source: {e['source']['label']}" + (f" {e['source']['url']}" if e['source'].get('url') else "")
        entries.append(f"  <entry><title>{x(title)}</title><link href=\"{x(link)}\"/><id>{x(link)}</id><updated>{when}</updated><summary>{x(body)}</summary></entry>")
    feed = ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
            f'  <title>freetokens: free LLM events</title>\n  <link href="{SITE}/"/>\n  <link rel="self" href="{SITE}/feed.xml"/>\n'
            f'  <id>{SITE}/feed.xml</id>\n  <updated>{today.isoformat()}T00:00:00Z</updated>\n  <author><name>freetokens</name></author>\n'
            + "\n".join(entries) + "\n</feed>\n")
    return {"sitemap.xml": sitemap, "robots.txt": robots, "favicon.svg": FAVICON_SVG + "\n", "404.html": notfound,
            "llms.txt": llms, "feed.xml": feed, f"{INDEXNOW_KEY}.txt": INDEXNOW_KEY + "\n",
            # Bing Webmaster Tools ownership file (site verification, 2026-10-06)
            "BingSiteAuth.xml": '<?xml version="1.0"?>\n<users>\n\t<user>440E125693FE785938B213DB73F48541</user>\n</users>\n'}


def prerender(dist):
    """Run each page once in headless Chrome and keep the rendered DOM, so crawlers get full HTML without running JS."""
    import shutil, subprocess
    chrome = next((c for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome") or "",
                               shutil.which("chromium") or "") if c and Path(c).exists()), None)
    if not chrome:
        print("! Chrome not found: skipped prerendering (pages still work, but content is rendered client-side)", file=sys.stderr)
        return 0
    import functools, http.server, threading
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(dist))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    n = 0
    pages_ = [p for p in sorted(dist.rglob("*.html")) if p.name not in ("404.html", "methodology.html")]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright = None
    if sync_playwright:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            for p in pages_:
                page = ctx.new_page()
                page.goto(f"http://127.0.0.1:{port}/{p.relative_to(dist).as_posix()}", wait_until="load", timeout=30000)
                page.wait_for_timeout(300)
                out = page.content()
                page.close()
                if 'class="wrap"' not in out:
                    sys.exit(f"✗ prerender failed for {p}")
                p.write_text(out if out.lstrip().lower().startswith("<!doctype") else "<!doctype html>\n" + out)
                n += 1
            browser.close()
    else:
        for p in pages_:
            url = f"http://127.0.0.1:{port}/{p.relative_to(dist).as_posix()}"
            out = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000", "--dump-dom", url],
                                 capture_output=True, text=True, timeout=90).stdout
            if 'class="wrap"' not in out:
                sys.exit(f"✗ prerender failed for {p}")
            p.write_text("<!doctype html>\n" + out.strip() + "\n")
            n += 1
    srv.shutdown()
    return n


def og_image(dist, lanes, models, today):
    """1200x630 social card rendered with headless Chrome (skipped without Chrome)."""
    import shutil, subprocess
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).exists():
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        return False
    free = len([l for l in lanes if l["status"] in FREE])
    card = dist / "_og.html"
    card.write_text(f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>
body{{margin:0;width:1200px;height:630px;background:#10141b;color:#e5e9f0;font-family:"IBM Plex Sans",sans-serif;display:flex;flex-direction:column;justify-content:space-between;padding:64px 72px;box-sizing:border-box}}
.b{{display:flex;gap:16px;align-items:center;font:700 40px "Bricolage Grotesque",sans-serif}} .b svg{{width:56px;height:56px}}
h1{{font:700 72px/1.05 "Bricolage Grotesque",sans-serif;margin:0;letter-spacing:-1px}} h1 span{{color:#4fc6d0}}
.s{{display:flex;gap:40px;font:500 28px "IBM Plex Mono",monospace;color:#9aa3b2}} .s b{{color:#e5e9f0;font-weight:500}}</style></head><body>
<div class="b">{FAVICON_SVG}freetokens.fyi</div>
<h1>Free LLMs, by channel,<br><span>with end dates.</span></h1>
<div class="s"><span><b>{free}</b> free lanes</span><span><b>{len(models)}</b> models</span><span><b>{len({l['channel'] for l in lanes})}</b> channels</span><span>updated {today:%b %-d}</span></div>
</body></html>""")
    try:  # Playwright first: the CLI's --virtual-time-budget can hang (same as --dump-dom)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            pg = b.new_page(viewport={"width": 1200, "height": 630})
            pg.goto(card.resolve().as_uri(), timeout=30000)
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(dist / "og.png"))
            b.close()
    except Exception:
        try:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,630",
                            f"--screenshot={(dist / 'og.png').resolve()}", card.resolve().as_uri()], capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            pass
    card.unlink()
    return (dist / "og.png").exists()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--validate", action="store_true", help="only check data/ against the schema; write nothing (for contributors)")
    ap.add_argument("--fragment")
    ap.add_argument("--dist", help="also build the deployable site into this folder (clean URLs, sitemap, prerendered HTML)")
    ap.add_argument("--today")
    a = ap.parse_args()
    if a.today:
        today = dt.date.fromisoformat(a.today)
    elif a.check and (m := re.search(r"As of (\d{4}-\d{2}-\d{2})\.", (ROOT / "README.md").read_text())):
        today = dt.date.fromisoformat(m.group(1))  # --check compares against the last build's date
    else:
        today = dt.date.today()

    lanes, events, models = load("lanes"), load("events"), load("models")
    chans = load_optional("channels", [])
    errs = validate(lanes, events, models) + validate_channels(chans, lanes)
    if errs:
        print("✗ data does not validate:", *errs, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    if a.validate:
        print(f"✓ data valid: {len(lanes)} lanes · {len(events)} events · {len(models)} models")
        return

    est, _ = estimate(models, load_optional("benchmarks", {}), load_optional("anchors", []))
    models_md = [dict(m, est=est[m["id"]]) if m["id"] in est else m for m in models]
    readme_path = ROOT / "README.md"
    readme = render_readme(readme_path.read_text(), {
        "legend": md_legend(),
        "soon": f"As of {today.isoformat()}.\n\n" + md_soon(lanes, models, today),
        "lanes": md_lanes(lanes, models),
        "timeline": md_events(events, lanes, models),
        "models": md_models(models_md, lanes, events),
        "channels": md_channels(lanes, models, today, chans),
    })
    preview = build_pages(lanes, events, models, today, "preview")
    outputs = {readme_path: readme}
    outputs.update({ROOT / p: full_doc(h, b) for p, (h, b) in preview.items()})
    stray = [p for d in ("models", "channels") if (ROOT / d).exists() for p in (ROOT / d).glob("*.html") if p not in outputs]

    if a.check:
        stale = [str(p.relative_to(ROOT)) for p, c in outputs.items() if not p.exists() or p.read_text() != c]
        stale += [f"{p.relative_to(ROOT)} (no such page)" for p in stray]
        if stale:
            print("✗ out of date (run python3 build.py): " + ", ".join(stale), file=sys.stderr)
            sys.exit(1)
        print("✓ data valid, generated files up to date")
        return
    (ROOT / "models").mkdir(exist_ok=True)
    (ROOT / "channels").mkdir(exist_ok=True)
    for p in stray:
        p.unlink()
    for p, c in outputs.items():
        p.write_text(c)
    msg = f"✓ {len(lanes)} lanes · {len(events)} events · {len(models)} models → README.md, index.html, models/*.html, channels/*.html"

    if a.fragment:
        # a host that adds its own <html>/<head>: home page as a fragment (head tags inline), other pages as full documents beside it
        out = Path(a.fragment)
        out.parent.mkdir(parents=True, exist_ok=True)
        h, b = preview["index.html"]
        css = (ROOT / "templates" / "style.css").read_text()
        out.write_text(h.replace('<meta charset="utf-8">\n', "") + f"<style>\n{css}</style>\n" + b)
        for p, (h2, b2) in preview.items():
            if p != "index.html":
                (out.parent / p).parent.mkdir(parents=True, exist_ok=True)
                (out.parent / p).write_text(full_doc(h2, b2))

    if a.dist:
        import shutil
        dist = Path(a.dist)
        shutil.rmtree(dist, ignore_errors=True)
        global ASSET_V
        import hashlib
        probe = build_pages(lanes, events, models, today, "site")
        shared = {k: v for k, v in probe.pop("__base__").items() if k in SHARED_KEYS}
        data_js = "window.FT_DATA = " + json.dumps(shared, ensure_ascii=False).replace("</", "<\\/") + ";\n"
        common_js = (ROOT / "templates" / "common.js").read_text()
        ASSET_V = hashlib.sha1((data_js + common_js).encode()).hexdigest()[:10]
        site = build_pages(lanes, events, models, today, "site")
        site.pop("__base__")
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "assets" / "data.js").write_text(data_js)
        (dist / "assets" / "common.js").write_text(common_js)
        for p, (h, b) in site.items():
            (dist / p).parent.mkdir(parents=True, exist_ok=True)
            (dist / p).write_text(full_doc(h, b))
        for p, c in site_extras(site, lanes, events, models, today).items():
            (dist / p).write_text(c)
        n = prerender(dist)
        ok = og_image(dist, lanes, models, today)
        msg += f"\n✓ site → {dist}/ ({len(site)} pages, {n} prerendered, sitemap, robots, favicon, 404{', og.png' if ok else ''})"
    print(msg)


if __name__ == "__main__":
    main()
