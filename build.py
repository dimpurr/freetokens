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
import os
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / "schema/schema.json").read_text())
VOCAB = SCHEMA["vocab"]

# ---------- i18n (ADR-010): English is the only hand-written language.
# LANG = "en" | "zh". T = UI strings (i18n/zh.json); ZHCACHE = free-text translations (i18n/zh-cache.json).
LANG = "en"
T = {}
ZHCACHE = {}
ZHMISSING = set()  # English source strings with no translation (reported by --check)


def load_zh():
    """Load i18n/zh.json (UI strings) and i18n/zh-cache.json (free-text cache). Missing files = no Chinese (dev)."""
    global T, ZHCACHE
    for name, dest in (("zh", "t"), ("zh-cache", None)):
        p = ROOT / "i18n" / f"{name}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        if dest:
            T = d.get("t", {})
        else:
            ZHCACHE = d


def zh_methodology():
    """Chinese METHOD.md translated by worker (scope-update): file header records sha1 of the English source.
    Hash mismatch = English moved on without a Chinese update -> fail loudly via --check (build falls back to English only for local experiments, never deploy)."""
    import hashlib
    src = (ROOT / "METHOD.md").read_text()
    want = hashlib.sha1(src.encode()).hexdigest()[:12]
    p = ROOT / "i18n" / "METHOD.zh-CN.md"
    if not p.exists():
        raise SystemExit("✗ i18n/METHOD.zh-CN.md missing: translate METHOD.md first (see DESIGN.md §6)")
    head, _, body = p.read_text().split("---", 2)
    m = re.search(r"source_sha1:\s*([0-9a-f]+)", head + "---" + _)
    if not m or m.group(1) != want:
        raise SystemExit(f"✗ i18n/METHOD.zh-CN.md is stale (EN METHOD.md sha1 {want}, file says {m.group(1) if m else 'none'}): re-translate before building zh")
    return body


def tr(en):
    """UI string lookup: Chinese when building zh, else the English source untouched."""
    if LANG == "zh":
        return T.get(en, en)
    return en


def zh_text(en):
    """Free-text lookup with fallback: missing translations fall back to English (never an error, never empty)."""
    if LANG == "zh" and isinstance(en, str) and en:
        if en in ZHCACHE:
            return ZHCACHE[en]
        ZHMISSING.add(en)
    return en


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
    if LANG == "zh":
        if p == "month":
            return f"{d.year}年{d.month}月"
        base = f"{d.year}年{d.month}月{d.day}日"
        return base if p == "day" else base + f" {d.hour:02d}:{d.minute:02d} UTC"
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
        if not e.get("lanes") and not e.get("offers"):
            errs.append(f"events[{e['date']}]: needs lanes or offers")
        for oid in e.get("offers", []):
            if oid not in {o["id"] for o in load_optional("offers", [])}:
                errs.append(f"events[{e['date']}]: unknown offer {oid!r}")
        for lid in e.get("lanes", []):
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
        lo = l.get("limits_observed")
        if lo:
            allowed = {"date", "reach", "parallel", "scope", "load", "cost", "quirks", "note", "checks", "networks"}
            if set(lo) - allowed:
                errs.append(f"{w}: limits_observed has unknown fields {sorted(set(lo) - allowed)} (old free text goes in note, max 60 chars)")
            for f, vname in (("reach", "reach"), ("scope", "limit_scope"), ("load", "under_load"), ("cost", "cost_seen")):
                if f in lo and lo[f] not in VOCAB[vname]:
                    errs.append(f"{w}: limits_observed.{f} {lo[f]!r} is not in vocab {vname}")
            if any(q not in VOCAB["quirk"] for q in lo.get("quirks", [])):
                errs.append(f"{w}: limits_observed.quirks has a value not in vocab quirk")
            if len(lo.get("note") or "") > 60:
                errs.append(f"{w}: limits_observed.note is over 60 characters; say it with fields")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(lo.get("date", ""))):
                errs.append(f"{w}: limits_observed.date must be YYYY-MM-DD")
        if "volume" in l and not (get(l, "volume.tier") in VOCAB["volume_tier"] and str(get(l, "volume.basis") or "").strip()):
            errs.append(f"{w}: volume needs tier (taste / daily / bulk) and basis (where the number comes from)")
        if "region" in l and not (isinstance(l["region"], str) and re.fullmatch(r"[A-Z]{2}(, ?[A-Z]{2})*", l["region"])):
            errs.append(f"{w}: region must be ISO country codes like 'US' or 'US, CA' (or leave it out for worldwide)")
        ls = l["limits_stated"]
        if set(ls) - {"basis", "per_day", "per_minute", "hours_day", "tokens_day", "note", "source"}:
            errs.append(f"{w}: limits_stated has unknown fields {sorted(set(ls) - {'basis', 'per_day', 'per_minute', 'hours_day', 'tokens_day', 'note', 'source'})}")
        if ls.get("basis") not in VOCAB["limit_basis"]:
            errs.append(f"{w}: limits_stated.basis must be one of {list(VOCAB['limit_basis'])}")
        if ls.get("basis") in ("official", "community") and not ls.get("source"):
            errs.append(f"{w}: a published or community limit needs limits_stated.source")
        if len(ls.get("note") or "") > 60:
            errs.append(f"{w}: limits_stated.note is over 60 characters; use the number fields")
    mk_ids = {x["id"] for x in load_optional("makers", [])}
    if mk_ids:
        for m in models:
            if m["maker"] not in mk_ids:
                errs.append(f"models[{m['id']}]: maker {m['maker']!r} is not an id in data/makers.json")
            sm = m.get("suspected_maker")
            if sm and (sm.get("maker") not in mk_ids or not str(sm.get("url", "")).startswith("http") or sm.get("confidence") != "unconfirmed"):
                errs.append(f"models[{m['id']}]: suspected_maker needs a known maker id, a source url and confidence 'unconfirmed'")
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



def validate_offers(offers, channels, models):
    """data/offers.json (ADR-005 / 019 / 025): generic allowances and grants, kept apart from $0 model lanes."""
    errs, ids = [], set()
    chans = {c["name"] for c in channels}
    spec = SCHEMA["tables"]["offers"]
    for o in offers:
        w = f"offers[{o.get('id')}]"
        for f in spec["required"]:
            if f not in o:
                errs.append(f"{w}: missing field {f!r}")
        if o.get("id") in ids:
            errs.append(f"{w}: duplicate id")
        ids.add(o.get("id"))
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", str(o.get("id", ""))):
            errs.append(f"{w}: id must be lower-case kebab-case")
        for f, vname in spec["vocab_fields"].items():
            if o.get(f) not in VOCAB[vname]:
                errs.append(f"{w}: {f}={o.get(f)!r} is not in vocab {vname}")
        if o.get("channel") and o["channel"] not in chans:
            errs.append(f"{w}: channel {o['channel']!r} is not in channels.json")
        g = o.get("gets") or {}
        if g.get("per") not in VOCAB["per"] or not str(g.get("text", "")).strip() or len(g.get("text", "")) > 90:
            errs.append(f"{w}: gets needs per (once/day/week/month/year) and text (<= 90 chars)")
        if any(r not in VOCAB["requirement"] for r in o.get("requires", [])):
            errs.append(f"{w}: requires has a value not in vocab requirement")
        if o.get("type") == "entitlement" and not (o.get("paid_plan") or {}).get("name"):
            errs.append(f"{w}: an entitlement names the paid plan it comes with")
        if not str((o.get("source") or {}).get("url", "")).startswith("http"):
            errs.append(f"{w}: source.url is required")
        for f in ("started", "ends"):  # the offer page reads these as plain dates (2026-10-12: an object broke /offers/huawei-…)
            if o.get(f) is not None and not (isinstance(o[f], str) and re.fullmatch(r"\d{4}-\d{2}(-\d{2}(T\d{2}:\d{2}Z)?)?", o[f])):
                errs.append(f"{w}: {f} must be a date string like 2026-10-12 (put context in note)")
        for mid in (o.get("models") or {}).get("tracked", []):
            if mid not in {m["id"] for m in models}:
                errs.append(f"{w}: models.tracked {mid!r} is not in models.json")
        if len(o.get("note") or "") > 140:
            errs.append(f"{w}: note over 140 characters")
    return errs


def validate_channels(channels, lanes):
    """data/channels.json: one record per channel that has lanes; entry cost with its source (cost badges)."""
    errs = []
    spec = SCHEMA["tables"]["channels"]
    names = [c.get("name") for c in channels]
    for c in channels:
        w = f"channels[{c.get('name')}]"
        if not str(c.get("free_condition") or "").strip():
            errs.append(f"{w}: free_condition is required (how its lanes are free, said once for the channel)")
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
        for k in ("site", "models"):
            if not str(get(c, f"links.{k}") or "").startswith("http"):
                errs.append(f"{w}: links.{k} is required (official site, and its model / price list page)")
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
    offer_chans = {o.get("channel") for o in load_optional("offers", [])}
    for n in sorted(set(names) - {l["channel"] for l in lanes} - offer_chans):
        errs.append(f"channels[{n}]: no lanes or offers use this channel")
    return errs


def entry_text(c):
    """README / page wording for a channel's cost to start: "$0 · account", "$10/month plan first", "$20 top-up first"."""
    e = c["entry"]
    if e["kind"] == "subscription":
        return f"${e['usd']:g}/{e['period']} " + tr("plan first")
    if e["kind"] == "topup":
        return f"${e['usd']:g} " + tr("top-up first")
    return label("entry_kind", e["kind"]) if LANG == "zh" else VOCAB["entry_kind"][e["kind"]]["short"]


def access_text(c):
    """"API · OpenAI chat" / "API · 3 formats" / "CLI only", plus "human only" when automation is banned."""
    a = c["access"]
    s = label("access_form", a["form"])
    if a["form"] == "api":
        s += " · " + (label("protocol", a["protocols"][0]) if len(a["protocols"]) == 1 else f"{len(a['protocols'])} " + tr("formats"))
    return s + "".join(" · " + label("access_rule", r) for r in a.get("rules", []))


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
            fits[bid] = {"ok": False, "why": f"only {len(pts)} reference models (need {R['min_anchors']})" if LANG == "en" else f"只有 {len(pts)} 个参考模型（需要 {R['min_anchors']} 个）", "n": len(pts)}
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mx, my = st.mean(xs), st.mean(ys)
        slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x in xs)
        r = st.correlation(xs, ys)
        fits[bid] = {"ok": r >= R["min_r"], "a": my - slope * mx, "b": slope, "r": round(r, 3), "n": len(pts),
                     "why": None if r >= R["min_r"] else (f"correlation {r:.2f} below {R['min_r']}" if LANG == "en" else f"相关系数 {r:.2f} 低于 {R['min_r']}")}
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
                listed.append(dict(c, implied=None, why=(f or {}).get("why") or ("no reference models for this benchmark" if LANG == "en" else "该基准尚无带 AA 指数的参考模型")))
            else:
                gap_max, scale = R.get("peer_max_gap", 10), R.get("peer_scale", 5)
                near = [p for p in c.get("peers", []) if p.get("aa") is not None and abs(c["score"] - p["score"]) <= gap_max]
                if near:  # ADR-023: compare inside the same table, so the vendor's harness and model-class bias cancel
                    ws = [(p["aa"] + f["b"] * (c["score"] - p["score"]), 1 / (1 + abs(c["score"] - p["score"]) / scale)) for p in near]
                    implied = sum(v * w for v, w in ws) / sum(w for _, w in ws)
                    used.append(dict(c, implied=round(implied, 1), r=f["r"], anchors=f["n"], method="peer",
                                     peers_used=[p["name"] for p in near], weight=R["weights"].get(c["source_type"], 0.5)))
                else:
                    used.append(dict(c, implied=round(f["a"] + f["b"] * c["score"], 1), r=f["r"], anchors=f["n"], method="fit",
                                     weight=R["weights"].get(c["source_type"], 0.5)))
        benches = {c["benchmark"] for c in used}
        sources = {c["url"].split("/")[2] for c in used}
        e = {"evidence": used + listed, "benchmarks": len(benches), "sources": len(sources),
             "rule": f"needs {R['min_benchmarks']} benchmarks from {R['min_sources']} independent sources"}
        if len(benches) >= R["min_benchmarks"] and len(sources) >= R["min_sources"]:
            ws = [(c["implied"], c["weight"]) for c in used]
            center = sum(v * w for v, w in ws) / sum(w for _, w in ws)  # weighted mean (ADR-023; a median of two picks the lower one)
            vendor_only = all(c["source_type"] == "official" and c["method"] == "fit" for c in used)
            width = R.get("vendor_only_band", 10) if vendor_only else R["band_width"]
            low = round(center - width / 2)
            e.update(status="ok", center=round(center, 1), low=low, high=low + width,
                     method="peer" if any(c["method"] == "peer" for c in used) else "fit", vendor_only=vendor_only,
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
    if LANG == "zh" and isinstance(v.get("zh"), dict) and v["zh"].get("label"):
        lab = v["zh"]["label"]
    else:
        lab = v["label"]
    return (v.get("icon", "") + " " if icon and v.get("icon") else "") + lab


def ends_text(l):
    e = l["ends"]
    parts = []
    if e.get("announced"):
        parts.append(f"{tr('announced')} {fmt_date(e['announced'])}")
    if e.get("expected"):
        parts.append(f"{tr('expected')} {fmt_date(e['expected'])}")
    txt = " · ".join(parts) or "—"
    txt += f" ({label('end_confidence', e['confidence'])})"
    if e.get("note"):
        txt += f"; {e['note']}"
    return txt


def md_legend():
    lines = []
    for vname, title in (("status", tr("Status")), ("end_confidence", tr("End-date confidence")),
                         ("check_method", tr("Checked by")), ("channel_type", tr("Channel type"))):
        items = []
        for k, v in VOCAB[vname].items():
            help_ = ((v.get("zh") or {}).get("help") if LANG == "zh" else None) or v.get("help")
            items.append(f"**{label(vname, k, icon=True)}**" + (f": {help_}" if help_ else ""))
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
            when = f"{tr('past announced end')} ({fmt_date(end)}), can stop any time" if LANG == "en" else f"{tr('past announced end')}（{fmt_date(end)}），随时可能停止"
        elif d < 0:
            when = f"{fmt_date(end)} ({tr('passed')})"
        else:
            when = f"{fmt_date(end)} · " + (tr("today") if d == 0 else (f"in {d} day{'s' if d != 1 else ''}" if LANG == "en" else f"{d} 天后"))
        rows.append((day(end), [f"{mname[l['model']]}", l["channel"], when, label("end_confidence", l["ends"]["confidence"])]))
    rows.sort(key=lambda r: r[0])
    return md_table([tr("Model"), tr("Channel"), tr("Ends"), tr("Confidence")], [r[1] for r in rows])


def stated_text(ls):
    """'50/day · 5/min' or the basis label (README)."""
    parts = [f"{ls['per_day']}/day" if ls.get("per_day") else "", f"{ls['per_minute']}/min" if ls.get("per_minute") else "",
             f"{ls['hours_day']} h/day" if ls.get("hours_day") else "", f"{ls['tokens_day'] / 1e6:g}M tokens/day" if ls.get("tokens_day") else ""]
    nums = " · ".join(p for p in parts if p)
    head = ("≈" + nums if ls["basis"] == "community" else nums) if nums else label("limit_basis", ls["basis"])
    return head + (f" ({ls['note']})" if ls.get("note") else "")


def obs_text(lo):
    """Plain words for a structured 'Tested by us' record (README)."""
    parts = [label("reach", lo["reach"])] if lo.get("reach") else []
    if lo.get("parallel"): parts.append(f"{lo['parallel']} " + tr("parallel"))
    parts += [label(v, lo[f]) for f, v in (("scope", "limit_scope"), ("load", "under_load"), ("cost", "cost_seen")) if lo.get(f)]
    parts += [label("quirk", q) for q in lo.get("quirks", [])]
    if lo.get("note"): parts.append(lo["note"])
    return " · ".join(parts)


def md_lanes(lanes, models):
    mname = {m["id"]: m["name"] for m in models}
    chan_cond = {c["name"]: c.get("free_condition") for c in load_optional("channels", [])}
    rows = []
    for l in lanes:
        ls = l["limits_stated"]
        lo = l["limits_observed"]
        s = l["started"]
        rows.append([
            mname[l["model"]], l["channel"], label("channel_type", l["type"]),
            f"`{l['model_id']}`" if l["model_id"] != "not recorded" else tr("not recorded"),
            "; ".join(x for x in (chan_cond.get(l["channel"]), l["free_condition"]) if x),
            link(stated_text(ls), ls.get("source")),
            f"{obs_text(lo)} ({lo['date']})" if lo else tr("not measured"),
            fmt_date(s["date"]) if s.get("date") else s.get("note"),
            ends_text(l),
            label("data_policy", l["data_policy"]),
            label("status", l["status"], icon=True),
            f"{l['checked']['date']} · {label('check_method', l['checked']['method'])}",
        ])
    return md_table([tr("Model"), tr("Channel"), tr("Type"), tr("Model ID"), tr("Free condition"), tr("Limits (stated)"), tr("Limits (observed)"),
                     tr("Started"), tr("Ends"), tr("Data policy"), tr("Status"), tr("Checked")], rows)


def md_events(events, lanes, models):
    mname = {m["id"]: m["name"] for m in models}
    lane = {l["id"]: l for l in lanes}
    rows = []
    for e in sorted(events, key=lambda e: parse_date(e["date"])[0], reverse=True):
        who = ", ".join(f"{mname[lane[i]['model']]} · {lane[i]['channel']}" for i in e.get("lanes", []))
        src = link(e["source"]["label"], e["source"].get("url"))
        if e["source"].get("note"):
            src += f" ({e['source']['note']})"
        text = e["text"] + (f" → ends {fmt_date(e['end_date'])}" if e.get("end_date") else "")
        rows.append([fmt_date(e["date"]), who, label("event_kind", e["kind"]), text, src])
    return md_table([tr("Date"), tr("Lane"), tr("Event"), tr("Detail"), tr("Source")], rows)


def md_models(models, lanes, events):
    lane_end = {}
    for e in events:
        if e["kind"] == "ended":
            for i in e.get("lanes", []):
                lane_end[i] = e["date"]

    def free_on(m):
        out = []
        for l in lanes:
            if l["model"] != m["id"]:
                continue
            st = l["status"]
            if st == "ended":
                tail = f"{tr('ended')} {fmt_date(lane_end[l['id']])[:10]}" if l["id"] in lane_end else tr("ended")
            elif st == "unavailable":
                tail = tr("not answering")
            elif st == "overdue" and not l["ends"].get("expected"):
                tail = f"{tr('past announced end')} {fmt_date(effective_end(l))[:10]}"
            elif effective_end(l):
                tail = f"{tr('ends')} {fmt_date(effective_end(l))[:10]}" if LANG == "zh" else f"ends {fmt_date(effective_end(l))[:10]}"
            else:
                tail = tr("no end announced")
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
            aa = f"EST {m['est']['low']}–{m['est']['high']} {tr('(estimate)')}"
        elif m.get("est"):
            aa = f"EST — ({m['est']['benchmarks']} {tr('benchmark so far')})"
        else:
            aa = a.get("note", tr("not ranked"))
        n = sum(1 for e in events if any(next(l for l in lanes if l["id"] == i)["model"] == m["id"] for i in e.get("lanes", [])))
        rows.append([f"[{m['name']}]({SITE}/models/{m['id']})", free_on(m), str(n), f"{aa} ({a['date']})", m["context"], label("image_input", m["image_input"]), {x["id"]: x["name"] for x in load_optional("makers", [])}.get(m["maker"], m["maker"]), m.get("notes") or "—"])
    return md_table([tr("Model"), tr("Free on"), tr("Events"), tr("AA index"), tr("Context"), tr("Image input"), tr("Maker"), tr("Notes")], rows)


def md_channels(lanes, models, today, chans):
    cinfo = {c["name"]: c for c in chans}
    mname = {m["id"]: m["name"] for m in models}
    rows = []
    for c in sorted({l["channel"] for l in lanes}):
        ls = [l for l in lanes if l["channel"] == c]
        free = [l for l in ls if l["status"] in ("live", "overdue", "listed")]
        up = sorted((l for l in free if effective_end(l) and day(effective_end(l)) >= today), key=lambda l: day(effective_end(l)))
        nxt = f"{mname[up[0]['model']]} · {fmt_date(effective_end(up[0]))[:10]} ({label('end_confidence', up[0]['ends']['confidence'])})" if up else tr("none announced")
        models_ = " · ".join(f"{VOCAB['status'][l['status']]['icon']} {mname[l['model']]}" for l in ls)
        rows.append((-len(free), c, [f"[{c}]({SITE}/channels/{slug(c)})", label("channel_type", ls[0]["type"]), f"[{entry_text(cinfo[c])}]({cinfo[c]['source']['url']})", f"[{access_text(cinfo[c])}]({cinfo[c]['access']['source']['url']})", f"{len(free)} / {len(ls)}", nxt, models_]))
    rows.sort()
    return md_table([tr("Channel"), tr("Type"), tr("To start"), tr("Access"), tr("Free now"), tr("Next end"), tr("Models")], [r[2] for r in rows])


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
    if len(s) <= n:
        return s
    if LANG == "zh":
        cut = max(s.rfind("。", 0, n), s.rfind("！", 0, n), s.rfind("？", 0, n), s.rfind("；", 0, n))
        return s[: n - 1] if cut < 0 else s[: cut + 1]
    return s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:·") + "…"


FREE = ("live", "overdue", "listed")


def seo_home(lanes, models, today):
    chans = sorted({l["channel"] for l in lanes})
    free = [l for l in lanes if l["status"] in FREE]
    if LANG == "zh":
        title = "免费 LLM 与 API：哪里免费、免费到何时 | freetokens"
        desc = clip(f"{len(free)} 条免费 LLM 线路，覆盖 {len(chans)} 个渠道（{', '.join(chans[:4])}…）：截止日期、下架记录与我们实测的限额。每条事实都有出处和日期，{today.year}年{today.month}月{today.day}日更新。")
        return title, desc
    title = "Free LLMs and APIs: where they are free and until when | freetokens"
    desc = clip(f"{len(free)} free LLM lanes across {len(chans)} channels ({', '.join(chans[:4])}…): end dates, takedowns and "
                f"limits we measured ourselves. Every fact sourced and dated; updated {today:%b %-d, %Y}.")
    return title, desc


def seo_model(m, lanes):
    ml = [l for l in lanes if l["model"] == m["id"]]
    free = [l for l in ml if l["status"] in FREE]
    if LANG == "zh":
        title = f"{m['name']} 免费：{len(ml)} 个渠道中有 {len(free)} 个，截止日期与限额 | freetokens"
        nxt = sorted((l for l in free if effective_end(l)), key=lambda l: effective_end(l))
        a = m["aa_index"]
        parts = [f"{m['name']} 现在哪些渠道免费：{', '.join(l['channel'] for l in free) or '暂无渠道'}。"]
        if nxt:
            parts.append(f"最近到期：{nxt[0]['channel']}，{fmt_date(effective_end(nxt[0]))}。")
        if a.get("value") is not None:
            parts.append(f"AA 指数 {a['value']}。")
        parts.append(f"{zh_text(m['context'])}。每条事实都有出处和日期。")
        return title, clip(" ".join(parts))
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
    if not cl:  # a channel that now holds only free programs (ADR-025)
        os_ = [o for o in load_optional("offers", []) if o.get("channel") == c]
        if LANG == "zh":
            return (f"{c}：免费额度与点数 | freetokens",
                    clip(f"{c} 给的是覆盖多个模型的免费额度，而不是某个模型的单价免费：" + "; ".join(f"{o['name']}：{zh_text(o['gets']['text'])}" for o in os_) + "。条件、出处与日期。"))
        return (f"{c}: free allowance and credits | freetokens",
                clip(f"{c} gives a free allowance that covers many models rather than free models of its own: "
                     + "; ".join(f"{o['name']}: {o['gets']['text']}" for o in os_) + ". Conditions, sources and dates."))
    free = [l for l in cl if l["status"] in FREE]
    names = {m["id"]: m["name"] for m in models}
    if LANG == "zh":
        title = f"{c} 上免费的模型：当前 {len(free)} 个，截止日期与限额 | freetokens"
        desc = clip(f"{c} 上跟踪的 {len(cl)} 个模型中有 {len(free)} 个免费（{label('channel_type', cl[0]['type'])}）："
                    f"{', '.join(names[l['model']] for l in free) or '当前没有'}。截止日期、下架与限额，都有出处。")
        return title, desc
    title = f"Free models on {c}: {len(free)} now, end dates and limits | freetokens"
    desc = clip(f"{len(free)} of {len(cl)} tracked models free on {c} ({label('channel_type', cl[0]['type'])}): "
                f"{', '.join(names[l['model']] for l in free) or 'none right now'}. End dates, takedowns and limits, with sources.")
    return title, desc


def seo_maker(mk, lanes, models):
    ms = [m for m in models if m["maker"] == mk["id"]]
    free = [m for m in ms if any(l["model"] == m["id"] and l["status"] in FREE for l in lanes)]
    who = "stealth models with no maker named" if mk["id"] == "undisclosed" else f"{mk['name']} models"
    if LANG == "zh":
        if mk["id"] == "undisclosed":
            title = f"未公开的免费模型：当前 {len(free)} 个，在哪用、用到何时 | freetokens"
            desc = clip(f"跟踪的 {len(ms)} 个未公开厂商的模型中有 {len(free)} 个当前免费。渠道、截止日期、分数与出处。")
        else:
            title = f"{mk['name']}免费模型：当前 {len(free)} 个，在哪用、用到何时 | freetokens"
            desc = clip(f"跟踪的 {len(ms)} 个{mk['name']}模型中有 {len(free)} 个当前免费：{', '.join(m['name'] for m in free) or '无'}。渠道、截止日期、分数与出处。")
        return title, desc
    title = f"Free {who}: {len(free)} now, where and until when | freetokens" if mk["id"] != "undisclosed" else f"Stealth LLMs free now ({len(free)}): suspected makers and where to use them | freetokens"
    desc = clip(f"{len(free)} of {len(ms)} tracked {who} are free right now: {', '.join(m['name'] for m in free) or 'none'}. Channels, end dates, scores and sources.")
    return title, desc


def jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def crumbs(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)]}


POSTHOG_KEY = "phc_tqfXBiHBRqpyfgAGUtaeMZjhugGAZAPddJueVuSoqSq3"  # public project key of the PostHog EU project "freetokens" (ADR-024); empty = no analytics
POSTHOG_SNIPPET = """<script>
/* cookieless analytics (OBSERVE.md): memory persistence, no session recording, no autocapture, Do Not Track respected; skipped for automation (prerender, crawlers) */
if (!navigator.webdriver && navigator.doNotTrack !== "1") {
!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset identify alias set_config".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
posthog.init("__KEY__", {api_host: "https://eu.i.posthog.com", persistence: "memory", autocapture: false, capture_pageview: true, capture_pageleave: true,
  disable_session_recording: true, respect_dnt: true, person_profiles: "identified_only", ip: false});
}
</script>
"""


BEACON_SNIPPET = """<script>
/* count request (OBSERVE.md §3 "Humans"): one empty first-party request once the page is visible; no cookie, no id, nothing sent */
if (!navigator.webdriver) { (function () { var sent = false, go = function () { if (sent || document.visibilityState !== "visible") return; sent = true;
  setTimeout(function () { fetch("/assets/hi.txt?" + Math.random().toString(36).slice(2), {cache: "no-store", keepalive: true}).catch(function () {}); }, 1000); };
  go(); document.addEventListener("visibilitychange", go); })(); }
</script>
"""
SHARED_ASSETS = True  # deployed pages load the dataset from /assets/data.js (cached across pages); readers without JavaScript get the prerendered HTML (prerender())


def head_html(title, desc, url, today, extra_ld, og_image, lang="en", alternates=()):
    """alternates: [(hreflang, href)] for this page (ADR-010: en <-> zh-CN + x-default)."""
    ld = []
    for x in extra_ld:
        x = dict(x)
        if x.get("@type") in ("WebPage", "Dataset"):
            x["inLanguage"] = "zh-CN" if lang == "zh" else "en"
        ld.append(x)
    hreflang = "".join(f'\n<link rel="alternate" hreflang="{hl}" href="{href}">' for hl, href in alternates)
    locale = "zh_CN" if lang == "zh" else "en_US"
    return ((POSTHOG_SNIPPET.replace("__KEY__", POSTHOG_KEY) if POSTHOG_KEY and url.startswith(SITE) else "") + BEACON_SNIPPET + f'<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'<title>{html.escape(title)}</title>\n<meta name="description" content="{html.escape(desc)}">\n'
            f'<link rel="canonical" href="{url}">\n' + hreflang.lstrip("\n") + ("\n" if hreflang else "")
            + f'<meta name="robots" content="index, follow, max-image-preview:large">\n'
            f'<meta name="theme-color" content="#0a7f8a">\n<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
            f'<link rel="alternate" type="application/atom+xml" title="freetokens: free LLM events" href="{SITE}{"/zh" if lang == "zh" else ""}/feed.xml">\n'
            f'<meta property="og:type" content="website">\n<meta property="og:locale" content="{locale}">\n<meta property="og:site_name" content="freetokens">\n'
            f'<meta property="og:title" content="{html.escape(title)}">\n<meta property="og:description" content="{html.escape(desc)}">\n'
            f'<meta property="og:url" content="{url}">\n<meta property="og:image" content="{og_image}">\n'
            f'<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n<meta name="twitter:title" content="{html.escape(title)}">\n'
            f'<meta name="twitter:description" content="{html.escape(desc)}">\n<meta name="twitter:image" content="{og_image}">\n'
            + "\n".join(jsonld(x) for x in extra_ld) + "\n" + FONTS)


# ---------- pages ----------

SHARED_KEYS = ("lanes", "events", "models", "chans", "makers", "offers", "vocab", "built", "ext", "est_rule")


def _zh_swap(text):
    for en in sorted(T, key=len, reverse=True):
        if len(en) < 4:
            continue
        if en in text:
            text = text.replace(en, T[en])
    return text


def apply_zh_template(body):
    """Chinese build: swap template English phrases for i18n/zh.json entries (longest first; templates stay English).
    Only in text nodes and title/aria-label/alt/placeholder attributes: never inside <script>, and never in
    ids, classes, links, or any other attribute (JS hooks and CSS selectors must survive byte-identical).
    Also rewrites absolute footer links (methodology, feed) to their /zh/ counterparts."""
    segs = re.split(r"(<script.*?</script>)", body, flags=re.S)
    for i in range(0, len(segs), 2):
        parts = re.split(r"(<[^>]+>)", segs[i])
        for j, part in enumerate(parts):
            if part.startswith("<"):
                parts[j] = re.sub(r'\b(title|aria-label|alt|placeholder)="([^"]*)"',
                                  lambda m: f'{m.group(1)}="{_zh_swap(m.group(2))}"', part)
            else:
                parts[j] = _zh_swap(part)
        segs[i] = "".join(parts)
    body = "".join(segs)
    body = body.replace("https://freetokens.fyi/methodology", "https://freetokens.fyi/zh/methodology")
    body = body.replace("https://freetokens.fyi/feed.xml", "https://freetokens.fyi/zh/feed.xml")
    return body


def render_body(template, payload, root, home, shared=False, lang="en"):
    """shared=True (deployed site): the dataset and common.js come from /assets/*.js, cached across pages."""
    t = ROOT / "templates"
    common = (t / "common.js").read_text()
    body = (t / template).read_text().replace("__BRAND__", BRAND).replace("__GH__", GH).replace("__HOME__", home).replace("__ROOT__", root)
    if lang == "zh":
        body = apply_zh_template(body)
        payload = dict(payload, lang="zh", i18n=T)
    else:
        payload = dict(payload, lang="en")
    if shared:
        page = {k: v for k, v in payload.items() if k not in SHARED_KEYS}
        data_asset = "data.zh.js" if lang == "zh" else "data.js"
        boot = (f'<script src="/assets/{data_asset}?v={ASSET_VERSIONS[data_asset]}"></script>\n<script>const D = Object.assign({{}}, window.FT_DATA, '
                f'{json.dumps(page, ensure_ascii=False)});</script>\n<script src="/assets/common.js?v={ASSET_VERSIONS["common.js"]}"></script>\n<script>')
        return body.replace("<script>\n/*__COMMON__*/", boot, 1)
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return body.replace("/*__COMMON__*/", f"const D = {data};\n" + common)


def full_doc(head, body, lang="en"):
    css = (ROOT / "templates" / "style.css").read_text()
    l = "zh-CN" if lang == "zh" else "en"
    return f'<!doctype html>\n<html lang="{l}">\n<head>\n{head}<style>\n{css}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n'


ASSET_V = "0"
ASSET_VERSIONS = {"data.js": "0", "data.zh.js": "0", "common.js": "0"}
INDEXNOW_KEY = "f7c3a9e14b2d4c6e8a0b1d3f5e7c9a2b"


def translate_dataset(base):
    """Deep-copy the shared dataset with free text replaced from i18n/zh-cache.json (missing -> English).
    Also promotes schema vocab zh labels/help/short over the English ones. Used for data.zh.js and zh page payloads."""
    import copy
    z = copy.deepcopy({k: base[k] for k in SHARED_KEYS if k in base})
    if "est_rule" in z:
        R = SCHEMA["est_rules"]
        z["est_rule"] = (f"{R['min_benchmarks']} 个基准，来自 {R['min_sources']} 个独立来源，"
                         f"每个拟合自 ≥{R['min_anchors']} 个参考模型且 r ≥ {R['min_r']}")
    for l in z.get("lanes", []):
        l["free_condition"] = zh_text(l.get("free_condition") or "")
        lo = l.get("limits_observed") or {}
        lo["text"] = zh_text(lo.get("text") or "")
        lo["note"] = zh_text(lo.get("note") or "")
        ls = l.get("limits_stated") or {}
        ls["note"] = zh_text(ls.get("note") or "")
        l["ends"]["note"] = zh_text((l.get("ends") or {}).get("note") or "")
        l["started"]["note"] = zh_text((l.get("started") or {}).get("note") or "")
    for e in z.get("events", []):
        e["text"] = zh_text(e.get("text") or "")
        e["source"]["label"] = zh_text((e.get("source") or {}).get("label") or "")
        e["source"]["note"] = zh_text((e.get("source") or {}).get("note") or "")
    for m in z.get("models", []):
        m["context"] = zh_text(m.get("context") or "")
        if m.get("notes"):
            m["notes"] = zh_text(m["notes"])
        for c in ((m.get("est") or {}).get("evidence") or []):
            if c.get("why"):
                c["why"] = zh_text(c["why"])
    for mk in z.get("makers", []):
        if mk.get("note"):
            mk["note"] = zh_text(mk["note"])
    for c in z.get("chans", []):
        c["free_condition"] = zh_text(c.get("free_condition") or "")
        c["entry"]["note"] = zh_text((c.get("entry") or {}).get("note") or "")
        c["source"]["label"] = zh_text((c.get("source") or {}).get("label") or "")
        a = c.get("access") or {}
        if (a.get("source") or {}).get("label"):
            a["source"]["label"] = zh_text(a["source"]["label"])
    for o in z.get("offers", []):
        o["gets"]["text"] = zh_text((o.get("gets") or {}).get("text") or "")
        if ((o.get("models") or {}).get("note")):
            o["models"]["note"] = zh_text(o["models"]["note"])
        for f in ("note", "quote"):
            if o.get(f):
                o[f] = zh_text(o[f])
        o["source"]["label"] = zh_text((o.get("source") or {}).get("label") or "")
        o["source"]["note"] = zh_text((o.get("source") or {}).get("note") or "")
    for vname, entries in (z.get("vocab") or {}).items():
        for key, entry in entries.items():
            zh = entry.get("zh") or {}
            for f in ("label", "help", "short"):
                if zh.get(f):
                    entry[f] = zh[f]
    return z


def build_pages(lanes, events, models, today, mode, lang="en"):
    """mode 'preview': relative .html links (repo, file://, artifact). mode 'site': clean absolute URLs for freetokens.fyi.
    lang 'en': current behavior. lang 'zh': pages under /zh/ with translated chrome and data (ADR-010; site mode only)."""
    global LANG
    LANG = lang
    zh = lang == "zh"
    if zh:
        load_zh()
    site = mode == "site"
    ext = "" if site else ".html"
    est, _ = estimate(models, load_optional("benchmarks", {}), load_optional("anchors", []))
    models = [dict(m, est=est[m["id"]]) if m["id"] in est else m for m in models]
    R = SCHEMA["est_rules"]
    base = {"lanes": lanes, "events": events, "models": models, "chans": load_optional("channels", []), "makers": load_optional("makers", []), "offers": load_optional("offers", []), "vocab": VOCAB, "built": today.isoformat(), "ext": ext,
            "est_rule": f"{R['min_benchmarks']} benchmarks from {R['min_sources']} independent sources, each fitted on ≥{R['min_anchors']} reference models with r ≥ {R['min_r']}"}
    if zh:
        base = dict(base, **translate_dataset(base))
    P = "zh/" if zh else ""          # output path prefix
    U = SITE + "/zh" if zh else SITE  # canonical URL base
    RT = "/zh/" if zh else "/"        # site root for links
    og = f"{SITE}/og.png"

    def alt(path):
        """hreflang set for a page path (no leading slash, no extension): en + zh-CN + x-default (ADR-010)."""
        if not site:
            return ()
        return (("en", f"{SITE}/{path}"), ("zh-CN", f"{SITE}/zh/{path}"), ("x-default", f"{SITE}/{path}"))

    pages = {}  # relative output path -> (head, body)
    names = {m["id"]: m["name"] for m in models}
    chans = sorted({l["channel"] for l in lanes} | {o["channel"] for o in load_optional("offers", []) if o.get("channel")})  # a channel may hold only offers (ADR-025)

    title, desc = seo_home(lanes, models, today)
    ds_name = "freetokens: 免费 LLM 线路、截止日期与实测限额" if zh else "freetokens: free LLM lanes, end dates and measured limits"
    il_name = "freetokens 跟踪的模型" if zh else "Models tracked on freetokens"
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "freetokens", "url": U + "/",
           "description": desc},
          {"@context": "https://schema.org", "@type": "Dataset", "name": ds_name,
           "description": desc, "url": U + "/", "sameAs": REPO, "isAccessibleForFree": True,
           "license": "https://creativecommons.org/licenses/by/4.0/", "dateModified": today.isoformat(),
           "creator": {"@type": "Person", "name": "dimpurr", "url": "https://github.com/dimpurr"},
           "keywords": ["free LLM", "free AI models", "free LLM API", "stealth models", "OpenRouter free models", "coding agents"],
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                             "contentUrl": f"https://raw.githubusercontent.com/dimpurr/freetokens/main/data/{n}.json"} for n in ("lanes", "events", "models")]},
          {"@context": "https://schema.org", "@type": "ItemList", "name": il_name,
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": m["name"], "url": f"{U}/models/{m['id']}"}
                               for i, m in enumerate(models)]}]
    home_href = "/zh/" if (site and zh) else ("/" if site else "index.html")
    pages[P + "index.html"] = (head_html(title, desc, U + "/", today, ld, og, lang, alt("")),
                               render_body("home.html", dict(base, root=RT if site else ""), RT if site else "", home_href, site and SHARED_ASSETS, lang))
    sub_root, sub_home = ((RT, RT) if zh else ("/", "/")) if site else ("../", "../index.html")
    for m in models:
        title, desc = seo_model(m, lanes)
        url = f"{U}/models/{m['id']}"
        ld = [crumbs([("freetokens", U + "/"), (tr("Models"), U + "/#h-models"), (m["name"], url)]),
              {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url, "description": desc,
               "dateModified": today.isoformat(), "about": {"@type": "Thing", "name": m["name"]}}]
        pages[P + f"models/{m['id']}.html"] = (head_html(title, desc, url, today, ld, og, lang, alt(f"models/{m['id']}")),
                                            render_body("model.html", dict(base, root=sub_root, model=m["id"]), sub_root, sub_home, site and SHARED_ASSETS, lang))
    for c in chans:
        title, desc = seo_channel(c, lanes, models)
        url = f"{U}/channels/{slug(c)}"
        ld = [crumbs([("freetokens", U + "/"), (tr("Channels"), U + "/#h-channels"), (c, url)]),
              {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url, "description": desc,
               "dateModified": today.isoformat()}]
        pages[P + f"channels/{slug(c)}.html"] = (head_html(title, desc, url, today, ld, og, lang, alt(f"channels/{slug(c)}")),
                                              render_body("channel.html", dict(base, root=sub_root, channel=c), sub_root, sub_home, site and SHARED_ASSETS, lang))
    if zh:
        hub = (("lanes", "全部免费线路：状态、截止日期与实测限额 | freetokens",
                f"我们跟踪的全部 {len(lanes)} 条免费模型 × 渠道线路：状态、截止日期、我们实测的限额与准确模型 ID。"),
               ("timeline", "免费 LLM 动态时间线：开始、结束与变化 | freetokens",
                f"免费 LLM 动态的全部记录（{len(events)} 个事件）：免费期开始与结束、公布的截止日期、实测的限额。"))
    else:
        hub = (("lanes", "All free LLM lanes: status, end dates and measured limits | freetokens",
                f"All {len(lanes)} free model × channel routes we track, with status, end dates, our own measured limits and exact model IDs."),
               ("timeline", "Timeline of free LLM offers: starts, ends and changes | freetokens",
                f"Every recorded change to free LLM offers ({len(events)} events): free periods starting and ending, end dates announced, limits measured."))
    for pg, title, desc in hub:
        url = f"{U}/{pg}"
        pages[P + f"{pg}.html"] = (head_html(title, desc, url, today, [crumbs([("freetokens", U + "/"), (tr(pg.title()), url)])], og, lang, alt(pg)),
                               render_body(f"{pg}.html", dict(base, root=RT if site else ""), RT if site else "", home_href, site and SHARED_ASSETS, lang))
    offers = load_optional("offers", [])
    for o in offers:
        url = f"{U}/offers/{o['id']}"
        # search results show ~60 characters: name plus the first clause of what you get, brand only if it still fits
        clause = re.split(r"[;；]|,\s|\s\(", zh_text(o["gets"]["text"]) if zh else o["gets"]["text"])[0].strip()
        core = f"{o['name']}: {clause}" if len(o["name"]) + 2 + len(clause) <= 60 else clip(o["name"], 70)
        title = f"{core} | freetokens" if len(core) <= 57 else core
        if zh:
            desc = clip(f"{o['name']}（{label('offer_type', o['type'])}，{o['provider']}）：{zh_text(o['gets']['text'])} {label('per', o['gets']['per'])}。"
                        f"需要：{', '.join(label('requirement', r) for r in o.get('requires', [])) or tr('nothing')}。状态与出处已核查 {o['checked']['date'] if isinstance(o['checked'], dict) else o['checked']}。")
        else:
            desc = clip(f"{o['name']} ({label('offer_type', o['type'])}, {o['provider']}): {o['gets']['text']} {label('per', o['gets']['per'])}. "
                        f"Needs: {', '.join(label('requirement', r) for r in o.get('requires', [])) or 'nothing'}. Status and source checked {o['checked']['date'] if isinstance(o['checked'], dict) else o['checked']}.")
        ld = [crumbs([("freetokens", U + "/"), (tr("Free programs"), U + "/offers"), (o["name"], url)]),
              {"@context": "https://schema.org", "@type": "Offer", "name": o["name"], "url": url, "price": 0, "priceCurrency": "USD",
               "offeredBy": {"@type": "Organization", "name": o["provider"]}}]
        pages[P + f"offers/{o['id']}.html"] = (head_html(title, desc, url, today, ld, og, lang, alt(f"offers/{o['id']}")),
                                           render_body("offer.html", dict(base, root=sub_root, offer=o["id"]), sub_root, sub_home, site and SHARED_ASSETS, lang))
    if zh:
        title = "免费 LLM 计划：学生优惠、点数与每日额度 | freetokens"
        desc = clip(f"{len(offers)} 个为模型付费的免费计划：学生优惠、注册点数、每日与每月额度、订阅附带权益。"
                    "金额用各家自己的单位，写明各自需要什么。")
    else:
        title = "Free LLM programs: student plans, credits and daily allowances | freetokens"
        desc = clip(f"{len(offers)} free programs that pay for model use: student plans, sign-up credits, daily and monthly allowances, perks bundled with plans. "
                    "Amounts in each provider's own unit, with what each one needs.")
    pages[P + "offers.html"] = (head_html(title, desc, U + "/offers", today, [crumbs([("freetokens", U + "/"), (tr("Free programs"), U + "/offers")])], og, lang, alt("offers")),
                            render_body("offers.html", dict(base, root=RT if site else ""), RT if site else "", home_href, site and SHARED_ASSETS, lang))
    makers = load_optional("makers", [])
    for mk in makers:
        title, desc = seo_maker(mk, lanes, models)
        url = f"{U}/makers/{mk['id']}"
        ld = [crumbs([("freetokens", U + "/"), (tr("Makers"), U + "/makers"), (mk["name"], url)]),
              {"@context": "https://schema.org", "@type": "Organization", "name": mk["name"], "url": (mk.get("links") or {}).get("site") or url}]
        pages[P + f"makers/{mk['id']}.html"] = (head_html(title, desc, url, today, ld, og, lang, alt(f"makers/{mk['id']}")),
                                            render_body("maker.html", dict(base, root=sub_root, maker=mk["id"]), sub_root, sub_home, site and SHARED_ASSETS, lang))
    if zh:
        title, desc = "有免费模型的 LLM 厂商：谁现在有什么 | freetokens", f"{len(makers)} 家模型厂商，按当前免费模型数排名，每家附最强的免费模型。"
    else:
        title, desc = "LLM makers with free models: who offers what, right now | freetokens", f"{len(makers)} model makers, ranked by how many of their models are free right now, with the best free model of each."
    pages[P + "makers.html"] = (head_html(title, desc, U + "/makers", today, [crumbs([("freetokens", U + "/"), (tr("Makers"), U + "/makers")])], og, lang, alt("makers")),
                            render_body("makers.html", dict(base, root=RT if site else ""), RT if site else "", home_href, site and SHARED_ASSETS, lang))
    if site:
        pages["__base__"] = base
        if zh:
            mtitle, mdesc = "freetokens 怎么运作：线路、核查与 EST 估算 | freetokens", "什么是一条线路、状态与截止可信度、“我们实测”限额怎么测、AA 指数的 EST 估算怎么算。"
        else:
            mtitle, mdesc = "How freetokens works: lanes, checks, and the EST estimate | freetokens", "What a lane, status and end-date confidence mean, how 'Tested by us' limits are measured, and how the EST estimate of the AA index is computed."
        method_body = zh_methodology() if zh else (ROOT / "METHOD.md").read_text()
        topbar = ('<div class="topbar"><div class="in">' + BRAND.replace("__HOME__", RT) + '<nav aria-label="Site">'
                  + "".join(f'<a href="{RT}{a}">{tr(t)}</a>' for a, t in
                             (("#h-models", "Models"), ("#h-channels", "Channels"), ("offers", "Offers"), ("lanes", "Lanes"), ("timeline", "Timeline")))
                  + '</nav>' + GH + '</div></div>')
        pages[P + "methodology.html"] = (head_html(mtitle, mdesc, U + "/methodology", today, [crumbs([("freetokens", U + "/"), (tr("Methodology"), U + "/methodology")])], og, lang, alt("methodology")),
                                     topbar + '<div class="wrap prose">' + md_to_html(method_body) + '</div>')
    if site:
        # language switch (topbar, next to the GitHub button): each page links to its counterpart
        for path in list(pages):
            if path == "__base__":
                continue
            h, b = pages[path]
            if '<a class="gh"' not in b:
                continue
            loc = path[:-5]
            if loc == "index":
                loc = ""
            other = SITE + "/" + loc[3:] if zh else SITE + "/zh/" + loc
            pages[path] = (h, b.replace('<a class="gh"', f'<a class="langsw" href="{other}">{"EN" if zh else "中文"}</a><a class="gh"', 1))
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


def llms_txt(lanes, models, today):
    """llms.txt for AI assistants: the answer first (free now, best first, with scores and channels), then pages and data."""
    est, _ = estimate(models, load_optional("benchmarks", {}), load_optional("anchors", []))
    chans = {c["name"]: c for c in load_optional("channels", [])}
    makers = {m["id"]: m["name"] for m in load_optional("makers", [])}
    raw = "https://raw.githubusercontent.com/dimpurr/freetokens/main/data"
    free = [l for l in lanes if l["status"] in FREE]

    def score(m):
        if m["aa_index"].get("value") is not None:
            return m["aa_index"]["value"], f"AA {m['aa_index']['value']}"
        e = est.get(m["id"], {})
        return (e["center"], f"EST {e['low']}-{e['high']}") if e.get("status") == "ok" else (-1, "unscored")

    def agent_ok(l):
        a = l.get("access") or chans.get(l["channel"], {}).get("access") or {}
        return a.get("form") in ("api", "own_cli") and "no_automation" not in a.get("rules", [])

    rows, gone = [], []
    for m in models:
        ls = [l for l in free if l["model"] == m["id"]]
        if not ls:
            if any(l["model"] == m["id"] for l in lanes):
                gone.append(m)
            continue
        s, label_ = score(m)
        where = ", ".join(sorted({l["channel"] + ("" if l["status"] == "live" else " (listed)") for l in ls}))
        agents = "yes" if any(agent_ok(l) for l in ls) else "no"
        rows.append((s, f"- [{m['name']}]({SITE}/models/{m['id']}) · {label_} · {makers.get(m['maker'], m['maker'])} · free on: {where} · usable by agents: {agents}"))
    rows.sort(key=lambda r: -r[0])
    return (f"# freetokens\n\n> Which LLMs you can use for free right now, through which channel, and until when. "
            f"{len(free)} free lanes, {len(rows)} models, {len({l['channel'] for l in lanes})} channels; every fact dated and sourced. "
            f"Generated {today.isoformat()}. Data under CC BY 4.0.\n\n"
            "Scores: AA = Artificial Analysis Intelligence Index (v4.3.2); EST = our estimate from benchmarks when AA has none (method in /methodology). "
            "\"(listed)\" = in the channel's free catalogue but not confirmed working by us. \"Usable by agents\" = an API key or a CLI whose terms allow automation.\n\n"
            "## Free now, best first\n\n" + "\n".join(r for _, r in rows) + "\n\n"
            "## Pages\n\n"
            f"- [Overview]({SITE}/): models, channels, ending soon, latest changes\n"
            f"- [Agents view]({SITE}/?use=agents): routes scripts and agents may use, with a fallback ladder (smartest first, step down when it runs out)\n"
            f"- [All lanes]({SITE}/lanes): every model x channel route with status, limits, what we measured, model IDs\n"
            f"- [Timeline]({SITE}/timeline) and [Atom feed]({SITE}/feed.xml): every recorded change, with sources\n"
            f"- [Makers]({SITE}/makers): who makes the free models; stealth models with unconfirmed attributions\n"
            f"- [Methodology]({SITE}/methodology): statuses, checks, the EST estimate, privacy\n\n"
            "## Data (machine-readable, CC BY 4.0)\n\n"
            f"- [lanes.json]({raw}/lanes.json): one model x channel x free condition: status, dates, published limits, what we measured\n"
            f"- [models.json]({raw}/models.json): models, maker, AA index, context, image input\n"
            f"- [channels.json]({raw}/channels.json): cost to start, how free models can be used (API / CLI / app), free condition\n"
            f"- [events.json]({raw}/events.json): dated events with sources\n"
            f"- [makers.json]({raw}/makers.json) · [benchmarks.json]({raw}/benchmarks.json) · [schema.json]({REPO.replace('github.com', 'raw.githubusercontent.com')}/main/schema/schema.json): field definitions\n\n"
            "## Free programs (allowances and credits, not tied to one model)\n\n"
            + "\n".join(f"- [{o['name']}]({SITE}/offers/{o['id']}) · {o['gets']['text']} ({label('per', o['gets']['per'])}) · needs: {', '.join(label('requirement', r) for r in o.get('requires', [])) or 'nothing'}"
                        for o in sorted(load_optional("offers", []), key=lambda o: (len(o.get("requires", [])), o["name"])) if o["status"] != "ended")
            + f"\n\nAll programs with filters: {SITE}/offers · data: {raw}/offers.json\n\n"
            "## No longer free\n\n" + "\n".join(f"- [{m['name']}]({SITE}/models/{m['id']})" for m in gone) + "\n\n"
            "## Channels\n\n" + "\n".join(f"- [{c}]({SITE}/channels/{slug(c)})" for c in sorted({l['channel'] for l in lanes})) + "\n")


def site_extras(pages, lanes, events, models, today, pages_zh=None):
    """robots.txt, sitemap.xml, favicon, 404 page: only for the deployed site.
    pages_zh: zh build_pages output (paths under zh/); sitemap lists both with xhtml:link alternates (ADR-010)."""
    def lastmod(path):
        if path.startswith("models/"):
            mid = path[7:-5]
            ds = [l["checked"]["date"] for l in lanes if l["model"] == mid] + [e["date"][:10] for e in events if any(lanes_by_id[i]["model"] == mid for i in e.get("lanes", []))]
        elif path.startswith("channels/"):
            cs = path[9:-5]
            ds = [l["checked"]["date"] for l in lanes if slug(l["channel"]) == cs] + [e["date"][:10] for e in events if any(slug(lanes_by_id[i]["channel"]) == cs for i in e.get("lanes", []))]
        else:
            ds = [today.isoformat()]
        return max(d for d in ds if len(d) == 10) if ds else today.isoformat()
    lanes_by_id = {l["id"]: l for l in lanes}
    zh_paths = {("" if p[3:-5] == "index" else p[3:-5]) for p in (pages_zh or {}) if p.startswith("zh/") and p != "__base__"}
    urls = []
    for p in sorted(pages):
        if p == "__base__":
            continue
        loc = SITE + "/" if p == "index.html" else f"{SITE}/{p[:-5]}"
        rel = "" if p == "index.html" else p[:-5]
        if rel in zh_paths:
            alt = (f'<xhtml:link rel="alternate" hreflang="en" href="{loc}"/>'
                   f'<xhtml:link rel="alternate" hreflang="zh-CN" href="{SITE}/zh/{rel}"/>'
                   f'<xhtml:link rel="alternate" hreflang="x-default" href="{loc}"/>')
            urls.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod(p)}</lastmod>{alt}</url>")
            urls.append(f"  <url><loc>{SITE}/zh/{rel}</loc><lastmod>{lastmod(p)}</lastmod>{alt}</url>")
        else:
            urls.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod(p)}</lastmod></url>")
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
               'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n")
    robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
    notfound = full_doc(
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Not found | freetokens</title>\n'
        '<meta name="robots" content="noindex">\n<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n' + FONTS,
        '<div class="wrap"><header class="intro"><h1>Page not found</h1><p>This page doesn\'t exist (models and channels can be renamed). '
        'Start from the <a href="/">home page</a>, or browse <a href="/#h-models">models</a> and <a href="/#h-channels">channels</a>.</p></header></div>')
    names = {m["id"]: m["name"] for m in models}
    free = [l for l in lanes if l["status"] in FREE]
    llms = llms_txt(lanes, models, today)

    def feed_xml(lang):
        """Atom feed per language (scope-update): zh entries link /zh/ pages, titles/summaries via cache."""
        FU = SITE + "/zh" if lang == "zh" else SITE
        elang = "zh" if lang == "zh" else "en"
        entries = []
        for e in sorted(events, key=lambda e: parse_date(e["date"])[0], reverse=True)[:50]:
            when = parse_date(e["date"])[0].strftime("%Y-%m-%dT%H:%M:%SZ")
            if e.get("lanes"):
                l0 = lanes_by_id[e["lanes"][0]]
                link = f"{FU}/models/{l0['model']}#ev-{re.sub(r'[^0-9]', '', e['date'])}-{e['lanes'][0]}"
                what = f"{names[l0['model']]}（{l0['channel']}）" if elang == "zh" else f"{names[l0['model']]} on {l0['channel']}"
                title = f"{label('event_kind', e['kind'])}：{what}" if elang == "zh" else f"{label('event_kind', e['kind'])}: {what}"
            else:  # an event about a free program (offers.json)
                oid = e["offers"][0]
                link = f"{FU}/offers/{oid}#ev-{re.sub(r'[^0-9]', '', e['date'])}"
                oname = next((o["name"] for o in load_optional("offers", []) if o["id"] == oid), oid)
                title = f"{label('event_kind', e['kind'])}：{oname}" if elang == "zh" else f"{label('event_kind', e['kind'])}: {oname}"
            body = e["text"] + (f" (end date {fmt_date(e['end_date'])})" if e.get("end_date") else "") + f". Source: {e['source']['label']}" + (f" {e['source'].get('url')}" if e['source'].get('url') else "")
            if elang == "zh":
                body = zh_text(e["text"]) + (f"（截止日期 {fmt_date(e['end_date'])}）" if e.get("end_date") else "") + f"。出处：{zh_text(e['source']['label'])}" + (f" {e['source'].get('url')}" if e['source'].get('url') else "")
            entries.append(f"  <entry><title>{x(title)}</title><link href=\"{x(link)}\"/><id>{x(link)}</id><updated>{when}</updated><summary>{x(body)}</summary></entry>")
        flang = ' xml:lang="zh-CN"' if lang == "zh" else ""
        return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"' + flang + '>\n'
                f'  <title>freetokens: free LLM events</title>\n  <link href="{FU}/"/>\n  <link rel="self" href="{FU}/feed.xml"/>\n'
                f'  <id>{FU}/feed.xml</id>\n  <updated>{today.isoformat()}T00:00:00Z</updated>\n  <author><name>freetokens</name></author>\n'
                + "\n".join(entries) + "\n</feed>\n")

    def x(t):
        return html.escape(str(t), quote=True)
    global LANG
    _saved = LANG
    LANG = "en"
    feed_en = feed_xml("en")
    LANG = "zh"
    load_zh()
    feed_zh = feed_xml("zh")
    LANG = _saved
    return {"sitemap.xml": sitemap, "robots.txt": robots, "favicon.svg": FAVICON_SVG + "\n", "404.html": notfound,
            "llms.txt": llms, "feed.xml": feed_en, "zh/feed.xml": feed_zh, f"{INDEXNOW_KEY}.txt": INDEXNOW_KEY + "\n",
            # Bing Webmaster Tools ownership file (site verification, 2026-10-06)
            "BingSiteAuth.xml": '<?xml version="1.0"?>\n<users>\n\t<user>440E125693FE785938B213DB73F48541</user>\n</users>\n'}


def prerender(dist):
    """Run each page's own JavaScript once and keep the rendered HTML, so crawlers and AI readers get full pages without JS.
    happy-dom in Node, no browser (ADR-026; headless Chrome kept failing to start). Returns the number of pages rendered."""
    import shutil, subprocess
    node = shutil.which("node")
    if not node or not (ROOT / "node_modules" / "happy-dom").exists():
        if os.environ.get("FT_ALLOW_NO_PRERENDER") == "1":  # local experiments only: never deploy such a build
            print("! node or happy-dom missing: skipped prerendering (FT_ALLOW_NO_PRERENDER=1)", file=sys.stderr)
            return 0
        sys.exit("✗ prerendering needs node and happy-dom: run `npm install` in the repo "
                 "(or set FT_ALLOW_NO_PRERENDER=1 for a local test build that must not be deployed)")
    r = subprocess.run([node, str(ROOT / "tools" / "prerender.mjs"), str(dist)], capture_output=True, text=True, timeout=600)
    if r.returncode:
        sys.exit(r.stderr.strip() or "✗ prerender failed")
    m = re.search(r"prerendered (\d+) pages", r.stdout)
    return int(m.group(1)) if m else 0


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


def collect_free_keys(lanes, events, models):
    """English source strings the zh build needs from i18n/zh-cache.json (mirrors translate_dataset)."""
    keys = set()
    def add(s):
        if isinstance(s, str) and s:
            keys.add(s)
    chans = {c["name"]: c for c in load_optional("channels", [])}
    for l in lanes:
        add(l.get("free_condition"))
        lo = l.get("limits_observed") or {}
        add(lo.get("text"))
        add(lo.get("note"))
        add((l.get("limits_stated") or {}).get("note"))
        add((l.get("ends") or {}).get("note"))
        add((l.get("started") or {}).get("note"))
    for e in events:
        add(e.get("text"))
        add((e.get("source") or {}).get("label"))
        add((e.get("source") or {}).get("note"))
    for m in models:
        add(m.get("context"))
        add(m.get("notes"))
    for mk in load_optional("makers", []):
        add(mk.get("note"))
    for c in (load_optional("benchmarks", {}).get("claims", [])):
        add(c.get("excluded"))
    for c in chans.values():
        add(c.get("free_condition"))
        add((c.get("entry") or {}).get("note"))
        add((c.get("source") or {}).get("label"))
        add(((c.get("access") or {}).get("source") or {}).get("label"))
    for o in load_optional("offers", []):
        add((o.get("gets") or {}).get("text"))
        if ((o.get("models") or {}).get("note")):
            add(o["models"]["note"])
        add(o.get("note"))
        add(o.get("quote"))
        add((o.get("source") or {}).get("label"))
        add((o.get("source") or {}).get("note"))
    _ = chans
    return keys


def check_i18n(lanes, events, models):
    """ADR-010: missing translations fail the build. Returns error list (empty = green)."""
    errs = []
    load_zh()
    for vname, entries in VOCAB.items():
        for key, entry in entries.items():
            if not (entry.get("zh") or {}).get("label"):
                errs.append(f"vocab {vname}.{key}: missing zh label")
    missing = sorted(collect_free_keys(lanes, events, models) - set(ZHCACHE))
    if missing:
        errs.append(f"zh-cache: {len(missing)} missing (first 5: " + "; ".join(m[:60] for m in missing[:5]) + ")")
    import hashlib
    src = (ROOT / "METHOD.md").read_text()
    mp = ROOT / "i18n" / "METHOD.zh-CN.md"
    if not mp.exists():
        errs.append("i18n/METHOD.zh-CN.md missing")
    else:
        parts = mp.read_text().split("---", 2)
        head = (parts[0] + "---" + parts[1]) if len(parts) > 1 else ""
        m = re.search(r"source_sha1:\s*([0-9a-f]+)", head)
        want = hashlib.sha1(src.encode()).hexdigest()[:12]
        if not m or m.group(1) != want:
            errs.append(f"i18n/METHOD.zh-CN.md stale (EN sha1 {want})")
    rp = ROOT / "i18n" / "zh-readme.json"
    if not rp.exists():
        errs.append("i18n/zh-readme.json missing")
    else:
        pmap = json.loads(rp.read_text()).get("prose", {})
        readme = (ROOT / "README.md").read_text()
        gone = [k[:60] for k in pmap if k not in readme]
        if gone:
            errs.append(f"i18n/zh-readme.json stale: {len(gone)} EN blocks no longer in README.md (first: {gone[0]!r})")
    return errs


def extract_readme_prose(text):
    """Hand-written README blocks outside <!-- BEGIN/END --> markers (translated once by worker)."""
    parts, buf, in_gen = [], [], False
    for line in text.split("\n"):
        if "<!-- BEGIN:" in line:
            in_gen = True
            if "".join(buf).strip():
                parts.append("".join(buf))
            buf = []
        elif "<!-- END:" in line:
            in_gen = False
        elif not in_gen:
            buf.append(line + "\n")
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts


def render_readme_zh(readme_en_text, sections_en, sections_zh):
    """README.zh-CN.md: translated prose (zh-readme.json) + regenerated zh tables. Global cache pass last (proper nouns are never cache keys)."""
    meta = json.loads((ROOT / "i18n" / "zh-readme.json").read_text())
    pmap = meta.get("prose", {})
    out = readme_en_text
    for en, zh in sorted(pmap.items(), key=lambda kv: -len(kv[0])):
        if en in out:
            out = out.replace(en, zh)
    for key in sections_en:
        if sections_en[key] in out:
            out = out.replace(sections_en[key], sections_zh[key])
    for en in sorted(ZHCACHE, key=len, reverse=True):
        if en in out:
            out = out.replace(en, ZHCACHE[en])
    return out


def main():
    global LANG, ASSET_V, ASSET_VERSIONS
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
    errs = validate(lanes, events, models) + validate_channels(chans, lanes) + validate_offers(load_optional("offers", []), chans, models)
    if errs:
        print("✗ data does not validate:", *errs, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    if a.validate:
        print(f"✓ data valid: {len(lanes)} lanes · {len(events)} events · {len(models)} models")
        return

    est, _ = estimate(models, load_optional("benchmarks", {}), load_optional("anchors", []))
    models_md = [dict(m, est=est[m["id"]]) if m["id"] in est else m for m in models]
    readme_path = ROOT / "README.md"
    sections_en = {
        "legend": md_legend(),
        "soon": f"As of {today.isoformat()}.\n\n" + md_soon(lanes, models, today),
        "lanes": md_lanes(lanes, models),
        "timeline": md_events(events, lanes, models),
        "models": md_models(models_md, lanes, events),
        "channels": md_channels(lanes, models, today, chans),
    }
    readme = render_readme(readme_path.read_text(), sections_en)
    preview = build_pages(lanes, events, models, today, "preview")
    outputs = {readme_path: readme}
    outputs.update({ROOT / p: full_doc(h, b) for p, (h, b) in preview.items()})
    stray = [p for d in ("models", "channels", "offers", "makers") if (ROOT / d).exists() for p in (ROOT / d).glob("*.html") if p not in outputs]
    # README.zh-CN.md (scope-update: full version; prose + tables regenerated, validated by --check)
    readme_zh = None
    if (ROOT / "i18n" / "zh-readme.json").exists():
        LANG = "zh"
        load_zh()
        sections_zh = {
            "legend": md_legend(),
            "soon": f"截至 {today.isoformat()}。\n\n" + md_soon(lanes, models, today),
            "lanes": md_lanes(lanes, models),
            "timeline": md_events(events, lanes, models),
            "models": md_models(models_md, lanes, events),
            "channels": md_channels(lanes, models, today, chans),
        }
        LANG = "en"
        readme_zh = render_readme_zh(readme_path.read_text(), sections_en, sections_zh)
        outputs[ROOT / "README.zh-CN.md"] = readme_zh

    if a.check:
        stale = [str(p.relative_to(ROOT)) for p, c in outputs.items() if not p.exists() or p.read_text() != c]
        stale += [f"{p.relative_to(ROOT)} (no such page)" for p in stray]
        if stale:
            print("✗ out of date (run python3 build.py): " + ", ".join(stale), file=sys.stderr)
            sys.exit(1)
        ierr = check_i18n(lanes, events, models)
        if ierr:
            print("✗ i18n incomplete:", *ierr, sep="\n  ", file=sys.stderr)
            sys.exit(1)
        print("✓ data valid, generated files up to date, i18n complete")
        return
    (ROOT / "models").mkdir(exist_ok=True)
    (ROOT / "channels").mkdir(exist_ok=True)
    for p in stray:
        p.unlink()
    for p, c in outputs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
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
        import hashlib
        probe = build_pages(lanes, events, models, today, "site")
        shared = {k: v for k, v in probe.pop("__base__").items() if k in SHARED_KEYS}
        data_js = "window.FT_DATA = " + json.dumps(shared, ensure_ascii=False).replace("</", "<\\/") + ";\n"
        common_js = (ROOT / "templates" / "common.js").read_text()
        load_zh()
        LANG = "zh"  # translate_dataset replaces only when LANG == "zh"
        shared_zh = translate_dataset(shared)
        LANG = "en"
        data_zh_js = "window.FT_DATA = " + json.dumps(shared_zh, ensure_ascii=False).replace("</", "<\\/") + ";\n"
        ASSET_VERSIONS = {name: hashlib.sha1(content.encode()).hexdigest()[:10]
                          for name, content in (("data.js", data_js), ("data.zh.js", data_zh_js), ("common.js", common_js))}
        ASSET_V = ASSET_VERSIONS["data.js"]
        LANG = "en"
        site = build_pages(lanes, events, models, today, "site")
        site.pop("__base__")
        LANG = "zh"
        site_zh = build_pages(lanes, events, models, today, "site", "zh")
        site_zh.pop("__base__", None)
        LANG = "en"
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "assets" / "data.js").write_text(data_js)
        (dist / "assets" / "data.zh.js").write_text(data_zh_js)
        (dist / "assets" / "common.js").write_text(common_js)
        (dist / "assets" / "hi.txt").write_text("")  # target of the count request (BEACON_SNIPPET)
        for p, (h, b) in list(site.items()) + list(site_zh.items()):
            (dist / p).parent.mkdir(parents=True, exist_ok=True)
            lang = "zh" if p.startswith("zh/") else "en"
            (dist / p).write_text(full_doc(h, b, lang))
        for p, c in site_extras(site, lanes, events, models, today, site_zh).items():
            (dist / p).parent.mkdir(parents=True, exist_ok=True)
            (dist / p).write_text(c)
        n = prerender(dist)
        expected = len([p for p in dist.rglob("*.html") if p.name not in ("404.html", "methodology.html")])
        if n < expected and os.environ.get("FT_ALLOW_NO_PRERENDER") != "1":
            sys.exit(f"✗ only {n} of {expected} pages prerendered: not deploying")
        ok = og_image(dist, lanes, models, today)
        msg += f"\n✓ site → {dist}/ ({len(site)} pages, {n} prerendered, sitemap, robots, favicon, 404{', og.png' if ok else ''})"
    print(msg)


if __name__ == "__main__":
    main()
