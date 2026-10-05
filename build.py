#!/usr/bin/env python3
"""Validate data/*.json against schema/schema.json, then generate README.md tables and index.html.

    python3 build.py                 # validate + write README.md and index.html
    python3 build.py --check         # validate + fail if README.md / index.html are out of date
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
    return errs


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
        return any(l["model"] == m["id"] and l["status"] in ("live", "overdue") for l in lanes)

    rows = []
    for m in sorted(models, key=lambda m: (not live(m), -(m["aa_index"].get("value") or -1))):
        a = m["aa_index"]
        aa = (("≈ " if a.get("approx") else "") + str(a["value"])) if a.get("value") is not None else a.get("note", "not ranked")
        n = sum(1 for e in events if any(next(l for l in lanes if l["id"] == i)["model"] == m["id"] for i in e["lanes"]))
        rows.append([f"[{m['name']}]({SITE}/models/{m['id']}.html)", free_on(m), str(n), f"{aa} ({a['date']})", m["context"], label("image_input", m["image_input"]), m["maker"], m.get("notes") or "—"])
    return md_table(["Model", "Free on", "Events", "AA index", "Context", "Image input", "Maker", "Notes"], rows)


def md_channels(lanes, models, today):
    mname = {m["id"]: m["name"] for m in models}
    rows = []
    for c in sorted({l["channel"] for l in lanes}):
        ls = [l for l in lanes if l["channel"] == c]
        free = [l for l in ls if l["status"] in ("live", "overdue")]
        up = sorted((l for l in free if effective_end(l) and day(effective_end(l)) >= today), key=lambda l: day(effective_end(l)))
        nxt = f"{mname[up[0]['model']]} · {fmt_date(effective_end(up[0]))[:10]} ({label('end_confidence', up[0]['ends']['confidence'])})" if up else "none announced"
        models_ = " · ".join(f"{VOCAB['status'][l['status']]['icon']} {mname[l['model']]}" for l in ls)
        rows.append((-len(free), c, [f"[{c}]({SITE}/channels/{slug(c)}.html)", label("channel_type", ls[0]["type"]), f"{len(free)} / {len(ls)}", nxt, models_]))
    rows.sort()
    return md_table(["Channel", "Type", "Free now", "Next end", "Models"], [r[2] for r in rows])


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
BRAND = ('<a class="brand" href="__ROOT__index.html"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>'
         '<span class="word">freetokens</span></a>')
GH = (f'<a class="gh" href="{REPO}" target="_blank" rel="noopener" title="Data and code on GitHub: corrections and new lanes welcome">'
      '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 '
      '0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 '
      '2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 '
      '2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 '
      '1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg><span>Contribute</span></a>')
HEAD = """<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
"""


def render_page(template, title, payload, root):
    t = ROOT / "templates"
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    common = (t / "common.js").read_text()
    body = (t / template).read_text().replace("__BRAND__", BRAND).replace("__GH__", GH).replace("__ROOT__", root).replace("/*__COMMON__*/", f"const D = {data};\n" + common)
    return HEAD.format(title=html.escape(title)) + "<style>\n" + (t / "style.css").read_text() + "</style>\n\n" + body


def wrap_full(fragment):
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + fragment + '\n</body>\n</html>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fragment")
    ap.add_argument("--today")
    a = ap.parse_args()
    if a.today:
        today = dt.date.fromisoformat(a.today)
    elif a.check and (m := re.search(r"As of (\d{4}-\d{2}-\d{2})\.", (ROOT / "README.md").read_text())):
        today = dt.date.fromisoformat(m.group(1))  # --check compares against the last build's date
    else:
        today = dt.date.today()

    lanes, events, models = load("lanes"), load("events"), load("models")
    errs = validate(lanes, events, models)
    if errs:
        print("✗ data does not validate:", *errs, sep="\n  ", file=sys.stderr)
        sys.exit(1)

    readme_path = ROOT / "README.md"
    readme = render_readme(readme_path.read_text(), {
        "legend": md_legend(),
        "soon": f"As of {today.isoformat()}.\n\n" + md_soon(lanes, models, today),
        "lanes": md_lanes(lanes, models),
        "timeline": md_events(events, lanes, models),
        "models": md_models(models, lanes, events),
        "channels": md_channels(lanes, models, today),
    })
    base = {"lanes": lanes, "events": events, "models": models, "vocab": VOCAB, "built": today.isoformat()}
    fragment = render_page("home.html", "freetokens", dict(base, root=""), "")
    outputs = {readme_path: readme, ROOT / "index.html": wrap_full(fragment)}
    model_pages = {}
    for m in models:
        frag = render_page("model.html", f"{m['name']} · freetokens", dict(base, root="../", model=m["id"]), "../")
        model_pages[m["id"]] = frag
        outputs[ROOT / "models" / f"{m['id']}.html"] = wrap_full(frag)
    channel_pages = {}
    for c in sorted({l["channel"] for l in lanes}):
        frag = render_page("channel.html", f"{c} · freetokens", dict(base, root="../", channel=c), "../")
        channel_pages[slug(c)] = frag
        outputs[ROOT / "channels" / f"{slug(c)}.html"] = wrap_full(frag)
    stray = [p for d in ("models", "channels") if (ROOT / d).exists() for p in (ROOT / d).glob("*.html") if p not in outputs]

    if a.check:
        stale = [str(p.relative_to(ROOT)) for p, c in outputs.items() if not p.exists() or p.read_text() != c]
        stale += [f"{p.relative_to(ROOT)} (no such model)" for p in stray]
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
    if a.fragment:
        # for hosts that add their own <html>/<head>: the home page as a fragment, model pages as full documents beside it
        out = Path(a.fragment)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(fragment)
        (out.parent / "models").mkdir(exist_ok=True)
        for mid in model_pages:
            (out.parent / "models" / f"{mid}.html").write_text(outputs[ROOT / "models" / f"{mid}.html"])
        (out.parent / "channels").mkdir(exist_ok=True)
        for cs in channel_pages:
            (out.parent / "channels" / f"{cs}.html").write_text(outputs[ROOT / "channels" / f"{cs}.html"])
    print(f"✓ {len(lanes)} lanes · {len(events)} events · {len(models)} models → README.md, index.html, models/*.html, channels/*.html")


if __name__ == "__main__":
    main()
