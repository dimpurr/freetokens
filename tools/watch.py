#!/usr/bin/env python3
"""Daily watch: compare public free-model catalogues with data/lanes.json (stdlib only, no keys, no LLM).

    python3 tools/watch.py [--out DIR] [--heartbeat]

Prints a short report only when something changed (new $0 models, or tracked lanes missing from a catalogue);
prints nothing otherwise, unless --heartbeat. Writes DIR/latest.json (default ~/scratch/DimResearchS/freetokens-watch).
A new model whose Artificial Analysis page shows an index >= 30 is flagged as a free-pool candidate.
"""
import json, re, sys, urllib.request, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "freetokens-watch/1 (+https://freetokens.fyi)"}
POOL_BAR = 30  # free-pool floors (Dim, 2026-10-07): main tier >= 35, borderline 30-35, below 30 out; admission needs Dim's approval
MAIN_BAR = 35
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
}


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


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
    """Best-effort AA lookup by slug guess; None when AA has no page."""
    base = re.sub(r"[^a-z0-9]+", "-", name_or_id.split("/")[-1].lower().replace(":free", "").replace("-free", "")).strip("-")
    cands = [s for s in slugs if s == base] or sorted(s for s in slugs if s.startswith(base))[:1]
    if not cands:
        return None, None
    s = cands[0]
    if s not in cache:
        try:
            h = get(f"https://artificialanalysis.ai/models/{s}").replace('\\"', '"')
            m = re.search(r'"slug":"%s"' % re.escape(s), h)
            ii = re.search(r'"intelligenceIndex":([0-9.]+)', h[m.start():m.start() + 4000]) if m else None
            cache[s] = round(float(ii.group(1))) if ii else None
        except Exception:
            cache[s] = None
    return cache[s], f"https://artificialanalysis.ai/models/{s}"


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
    lines = page_changes(out) + [f"🔁 back in a free catalogue: {x['model_id']} · {x['channel']} → {x['note']}" for x in back]
    if new:
        lines.append(f"🆕 {len(new)} free model(s) not on freetokens yet:")
        for x in new:
            tag = "⭐ pool candidate " if x["pool_candidate"] else ""
            if x["pool_candidate"]: tag = "⭐ main-tier candidate " if x["aa"] >= MAIN_BAR else "◐ borderline candidate "
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
