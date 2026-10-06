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
POOL_BAR = 30
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
                gone.append({"channel": ch, "model_id": mid, "lane": l["id"], "status": l["status"]})
    new.sort(key=lambda x: -(x["aa"] or -1))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    (out / "latest.json").write_text(json.dumps({"checked": now, "new": new, "gone": gone, "errors": errors}, ensure_ascii=False, indent=1))
    lines = []
    if new:
        lines.append(f"🆕 {len(new)} free model(s) not on freetokens yet:")
        for x in new:
            tag = "⭐ pool candidate " if x["pool_candidate"] else ""
            lines.append(f"  {tag}{x['name']} · {x['channel']} · {x['model_id']} · AA {x['aa'] if x['aa'] is not None else '—'}")
    if gone:
        lines.append(f"🕳️ {len(gone)} tracked lane(s) no longer in the catalogue (maybe ended):")
        lines += [f"  {x['model_id']} · {x['channel']} (lane {x['lane']}, {x['status']})" for x in gone]
    if errors:
        lines.append("⚠️ could not read: " + "; ".join(errors))
    if lines:
        print("freetokens watch · " + now[:10] + "\n" + "\n".join(lines) + f"\nDetails: {out / 'latest.json'}")
    elif "--heartbeat" in sys.argv:
        print(f"freetokens watch · {now[:10]} · no changes in {len(CATALOGUES)} catalogues this run (weekly heartbeat)")


if __name__ == "__main__":
    main()
