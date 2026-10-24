#!/usr/bin/env python3
"""Daily watch: compare public free-model catalogues with data/lanes.json (stdlib only, no LLM).

    python3 tools/watch.py [--out DIR] [--heartbeat]

Prints a short report only when something changed (new $0 models, or tracked lanes missing from a catalogue);
prints nothing otherwise, unless --heartbeat. Writes DIR/latest.json (default ~/scratch/DimResearchS/freetokens-watch).
A new model whose Artificial Analysis index >= 30 is flagged as a free-pool candidate.
AA comes from Artificial Analysis' own data API (ADR-031 / 16b-3): one authenticated call lists every model
they index plus its sub-scores. The key is AA_API_KEY from the environment or chco .env, read at run time and
never printed; without it the tool falls back to reading AA model pages one by one, as it did before.
"""
import json, os, re, sys, urllib.request, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "freetokens-watch/1 (+https://freetokens.fyi)"}
AA_API = "https://artificialanalysis.ai/api/v2/data/llms/models"  # one call: every model AA indexes, with sub-scores
# chco .env directories, same search order as _pool_policy() below; the key value is never printed.
CHCO_HOME = ["~/WorkflowUser/Code/Project/dimresearchcode", "~/WorkflowUser/Code/Personal/dimresearchcode",
             "~/Workflow/code/project/dimresearchcode"]
# Pool floors are Dim's private policy, kept in chco tools/free-pool/arms.toml [policy] (main_bar, pool_bar).
# Read them from there when present (env FT_POOL_POLICY overrides the path); fall back to the last known values.
def _pool_policy():
    import os
    try:
        import tomllib
    except ImportError:
        return 25, 30, 35
    cands = [os.environ.get("FT_POOL_POLICY", "")] + [os.path.expanduser(p + "/tools/free-pool/arms.toml") for p in
             ("~/WorkflowUser/Code/Project/dimresearchcode", "~/WorkflowUser/Code/Personal/dimresearchcode", "~/Workflow/code/project/dimresearchcode")]
    for c in cands:
        if c and os.path.exists(c):
            pol = tomllib.load(open(c, "rb")).get("policy", {})
            return pol.get("pass_bar", 25), pol.get("pool_bar", 30), pol.get("main_bar", 35)
    return 25, 30, 35


PASS_BAR, BORDER_BAR, MAIN_BAR = _pool_policy()  # 及格层 25-30 (retrieval / docs only), 擦线层 30-35, 主层 >= 35 (Dim, 2026-10-08)
POOL_BAR = PASS_BAR  # lowest floor: anything at or above it is worth flagging
# ids whose return to a free catalogue matters to someone: (channel, model_id) -> who to tell
WATCH_RETURN = {
    ("OpenCode Go", "opencode-go/space-bunny-free"): "m1max-dimmodel can restore the bunny arm (retired 2026-10-06)",
}
# tracked ids whose departure matters to someone beyond the public record: (channel, model_id) -> who to tell
WATCH_GONE = {
    ("OpenCode Zen", "opencode/muse-spark-1.3-contributor-free"): "tell m1max-dimmodel to cancel its 4-hourly Muse probe timer (set 2026-10-06)",
}
# known non-chat models and aliases of lanes we already track: (channel, model_id) -> why it is ignored
IGNORE = {
    ("OpenRouter", "nvidia/nemotron-3.5-content-safety:free"): "safety classifier, not a chat model",
    ("OpenRouter", "google/lyria-3-pro-preview"): "music model",
    ("OpenRouter", "google/lyria-3-clip-preview"): "music model",
    ("Vercel AI Gateway", "inclusionai/ling-3.1-flash"): "same $0 model as the tracked -free id",
    ("Vercel AI Gateway", "reflection/beam"): "no Vercel free lane (standard id billed; -free id untested, needs one call to qualify per ADR-022) — re-report suppressed, ask Dim",
}


def get(url, timeout=60, headers=None):
    h = dict(UA)
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def aa_key():
    """AA_API_KEY from the environment, else parsed out of chco .env at run time. Never printed, never stored."""
    v = os.environ.get("AA_API_KEY")
    if v:
        return v.strip()
    for d in CHCO_HOME:
        f = Path(d).expanduser() / ".env"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if line.startswith("AA_API_KEY=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def aa_table(cache={}):
    """{slug: {name, aa, creator}} from the AA data API, or None when there is no key or the call fails
    (then every AA lookup falls back to scraping the model page). One call covers the whole run."""
    if "t" in cache:
        return cache["t"]
    cache["t"] = None  # one attempt per process, whatever happens
    k = aa_key()
    if not k:
        return None
    try:
        rows = json.loads(get(AA_API, 120, {"x-api-key": k}))["data"]
    except Exception:
        return None
    t = {}
    for r in rows:
        if not r.get("slug"):
            continue
        t[r["slug"]] = {"name": r.get("name") or r["slug"],
                        "aa": (r.get("evaluations") or {}).get("artificial_analysis_intelligence_index"),
                        "creator": (r.get("model_creator") or {}).get("name")}
    cache["t"] = t
    return t


def zero(*vals):
    return all(str(v) in ("0", "0.0", "0.00") for v in vals)


# each catalogue: channel name as in lanes.json -> (ids that are free now, how our model_id is written)
def openrouter():
    d = json.loads(get("https://openrouter.ai/api/v1/models"))["data"]
    return {m["id"]: m.get("name", m["id"]) for m in d
            if zero(m.get("pricing", {}).get("prompt"), m.get("pricing", {}).get("completion"))
            and "text" in (m.get("architecture", {}).get("output_modalities") or ["text"])
            and not m["id"].startswith("openrouter/")}


def opencode(url, prefix):
    d = json.loads(get(url))["data"]
    return {f"{prefix}/{m['id']}": m["id"] for m in d if m["id"].endswith("-free") or m["id"] == "big-pickle"}


def vercel():
    d = json.loads(get("https://ai-gateway.vercel.sh/v1/models"))["data"]
    return {m["id"]: m.get("name", m["id"]) for m in d
            if m.get("type") == "language" and zero(m.get("pricing", {}).get("input"), m.get("pricing", {}).get("output"))}


CATALOGUES = {
    "OpenRouter": openrouter,
    "OpenCode Zen": lambda: opencode("https://opencode.ai/zen/v1/models", "opencode"),
    "OpenCode Go": lambda: opencode("https://opencode.ai/zen/go/v1/models", "opencode-go"),
    "Vercel AI Gateway": vercel,
}


def aa_index(name_or_id, slugs, cache={}):
    """Best-effort AA lookup by slug guess; None when AA has no page. The slug space and the index come from
    the AA data API when it is reachable; otherwise from the AA sitemap plus one page per slug (the old route)."""
    base = re.sub(r"[^a-z0-9]+", "-", name_or_id.split("/")[-1].lower().replace(":free", "").replace("-free", "")).strip("-")
    table = aa_table()
    pool = set(table) if table else set(slugs)
    cands = [s for s in pool if s == base] or sorted(s for s in pool if s.startswith(base))[:1]
    if not cands:
        return None, None
    s = cands[0]
    url = f"https://artificialanalysis.ai/models/{s}"  # the attribution link we keep citing on the site
    if table:
        v = table[s]["aa"]
        return (round(float(v)) if v is not None else None), url
    if s not in cache:
        try:
            h = get(f"https://artificialanalysis.ai/models/{s}").replace('\\"', '"')
            m = re.search(r'"slug":"%s"' % re.escape(s), h)
            ii = re.search(r'"intelligenceIndex":([0-9.]+)', h[m.start():m.start() + 4000]) if m else None
            cache[s] = round(float(ii.group(1))) if ii else None
        except Exception:
            cache[s] = None
    return cache[s], url


def screen():
    """Weekly self-check (the Dots3 lesson): lanes already in our data that agents may use, score >= POOL_BAR
    (official AA or EST centre), still free, but never load-tested. Pool membership is not ours to know; just list them."""
    sys.path.insert(0, str(ROOT))
    import build
    models = {m["id"]: m for m in build.load("models")}
    est, _ = build.estimate(list(models.values()), build.load_optional("benchmarks", {}), build.load_optional("anchors", []))
    chans = {c["name"]: c for c in build.load_optional("channels", [])}
    out = []
    for l in build.load("lanes"):
        a = (l.get("access") or chans.get(l["channel"], {}).get("access") or {})
        if l["status"] not in ("live", "listed", "overdue") or "no_automation" in a.get("rules", []) or a.get("form") not in ("api", "own_cli"):
            continue
        m = models[l["model"]]
        s = m["aa_index"].get("value") or (est.get(m["id"], {}).get("center") if est.get(m["id"], {}).get("status") == "ok" else None)
        judged = l.get("limits_observed") or ((l.get("limits_stated") or {}).get("per_day") or 10**9) < 100  # under 100 a day is too few for agent use
        if s and s >= POOL_BAR and not judged:
            out.append((s, m["name"], l["channel"], l["status"]))
    return sorted(out, reverse=True)


# promo pages with no machine-readable catalogue: alert when the page text changes (e.g. an end date is announced)
PAGES = {
    "Qoder · Qwen3.8-Flash promo": ("https://docs.qoder.com/zh/events/flashoffer", "结束"),
}


def norm_name(s):
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)", "", (s or "").lower())).strip()


def aa_recheck(out, slugs):
    """Weekly (Dim 2026-10-22; on the AA data API since 16b-3): tracked models with no AA index get one more
    lookup. One API call returns every model AA indexes with its intelligence index and name, so a late listing
    is caught either by slug or by AA's own model name (the Beam 1.0 lesson: a slug our guess never produced).
    Runs once per calendar week; state lives next to latest.json. Nothing is written into data/: the line tells
    Dim to fill models.json himself."""
    state_f = out / "aa_recheck.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    week = list(dt.date.today().isocalendar()[:2])
    if state.get("week") == week:
        return state.get("lines", [])
    models = json.loads((ROOT / "data/models.json").read_text())
    table = aa_table()
    by_name = {}
    for s, r in (table or {}).items():
        by_name.setdefault(norm_name(r["name"]), (s, r))
    lines = []
    for m in models:
        if (m.get("aa_index") or {}).get("value"):
            continue
        v, url = aa_index(m["id"], slugs)
        how = ""
        if not v and by_name:
            hit = by_name.get(norm_name(m.get("name")))
            if hit:
                s, r = hit
                v = round(float(r["aa"])) if r["aa"] is not None else None
                url = f"https://artificialanalysis.ai/models/{s}"
                how = " · matched on AA's model name"
        if v:
            lines.append(f"🆕 AA now lists {m['id']}: index {v} ({url}) — fill models.json{how}")
    state = {"week": week, "via": "aa-data-api" if table else "aa-pages", "checked": len(models), "lines": lines}
    state_f.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return lines


def page_changes(out):
    import hashlib, html as H
    state_f = out / "pages.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    lines = []
    for name, (url, key) in PAGES.items():
        try:
            t = re.sub(r"<script.*?</script>|<style.*?</style>", "", get(url), flags=re.S)
            t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", t)))
        except Exception as e:
            lines.append(f"⚠️ could not read {name}: {str(e)[:60]}")
            continue
        h = hashlib.sha1(t.encode()).hexdigest()
        if name in state and state[name] != h:
            snips = [t[max(0, m.start() - 60):m.end() + 80] for m in re.finditer(key, t)][:2]
            lines.append(f"📄 {name} changed: " + " … ".join(snips) + f" ({url})")
        state[name] = h
    state_f.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return lines


def main():
    out = Path(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "~/scratch/DimResearchS/freetokens-watch")).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    lanes = json.loads((ROOT / "data/lanes.json").read_text())
    tracked = {(l["channel"], l["model_id"]) for l in lanes}
    live = {(l["channel"], l["model_id"]): l for l in lanes if l["status"] in ("live", "listed", "overdue")}
    slugs = set()
    if aa_table() is None:  # no AA API this run (no key, or the call failed): fall back to the AA sitemap
        try:
            slugs = set(re.findall(r"artificialanalysis\.ai/models/([a-z0-9.\-]+)</loc>", get("https://artificialanalysis.ai/sitemap.xml", 90)))
        except Exception:
            slugs = set()
    new, gone, errors = [], [], []
    for ch, fetch in CATALOGUES.items():
        try:
            free = fetch()
        except Exception as e:
            errors.append(f"{ch}: {str(e)[:80]}")
            continue
        for mid, name in free.items():
            if (ch, mid) not in tracked and (ch, mid) not in IGNORE:
                aa, url = aa_index(mid, slugs)
                new.append({"channel": ch, "model_id": mid, "name": name, "aa": aa, "aa_url": url, "pool_candidate": bool(aa and aa >= POOL_BAR)})
        for (c, mid), l in live.items():
            if c == ch and mid not in free:
                gone.append({"channel": ch, "model_id": mid, "lane": l["id"], "status": l["status"], "note": WATCH_GONE.get((ch, mid))})
    back = [{"channel": c, "model_id": m, "note": n} for (c, m), n in WATCH_RETURN.items()
            if any(x["channel"] == c and x["model_id"] == m for x in new)]
    new.sort(key=lambda x: -(x["aa"] or -1))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    (out / "latest.json").write_text(json.dumps({"checked": now, "back": back, "new": new, "gone": gone, "errors": errors}, ensure_ascii=False, indent=1))
    lines = aa_recheck(out, slugs) + page_changes(out) + [f"🔁 back in a free catalogue: {x['model_id']} · {x['channel']} → {x['note']}" for x in back]
    if new:
        lines.append(f"🆕 {len(new)} free model(s) not on freetokens yet:")
        for x in new:
            tag = "⭐ pool candidate " if x["pool_candidate"] else ""
            if x["pool_candidate"]: tag = "⭐ main-tier candidate " if x["aa"] >= MAIN_BAR else "◐ borderline candidate " if x["aa"] >= BORDER_BAR else "○ pass-tier candidate (retrieval / docs only) "
            lines.append(f"  {tag}{x['name']} · {x['channel']} · {x['model_id']} · AA {x['aa'] if x['aa'] is not None else '—'}")
    if gone:
        lines.append(f"🕳️ {len(gone)} tracked lane(s) no longer in the catalogue (maybe ended):")
        lines += [f"  {x['model_id']} · {x['channel']} (lane {x['lane']}, {x['status']})" + (f" → {x['note']}" if x["note"] else "") for x in gone]
    if errors:
        lines.append("⚠️ could not read: " + "; ".join(errors))
    if lines:
        print("freetokens watch · " + now[:10] + "\n" + "\n".join(lines) + f"\nDetails: {out / 'latest.json'}")
    elif "--heartbeat" in sys.argv:
        print(f"freetokens watch · {now[:10]} · no catalogue changes this run (weekly heartbeat)")
    if "--heartbeat" in sys.argv:
        todo = screen()
        if todo:
            print(f"🔎 {len(todo)} lane(s) agents could use, score ≥{POOL_BAR}, never tested by us:")
            print("\n".join(f"  {s:g} · {n} · {c} ({st})" for s, n, c, st in todo))


if __name__ == "__main__":
    main()
