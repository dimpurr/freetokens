#!/usr/bin/env python3
"""Daily watch: compare public free-model catalogues with data/lanes.json (stdlib only, no LLM).

    python3 tools/watch.py [--out DIR] [--heartbeat]

Prints a short report only when something changed (new $0 models, or tracked lanes missing from a catalogue);
prints nothing otherwise, unless --heartbeat. Writes DIR/latest.json (default ~/scratch/DimResearchS/freetokens-watch).
A new model whose Artificial Analysis index >= 30 is flagged as a free-pool candidate.
AA comes from Artificial Analysis' own data API (ADR-031 / 16b-3): one authenticated call lists every model
they index plus its sub-scores. The key is AA_API_KEY from the environment or chco .env, read at run time and
never printed; without it the tool falls back to reading AA model pages one by one, as it did before.
Channels: OpenRouter, OpenCode Zen/Go, Vercel AI Gateway, Kilo Code and SiliconFlow report $0 models (full);
OVHcloud AI Endpoints, Groq, Google AI Studio and AIHubMix are gone-only (no per-model $0 price in their
machine-readable list, so they only flag tracked lanes that vanished).
A new channel's first read is a baseline run: it reports no "new" (that would flood on onboarding) and instead
prints the untracked free inventory. Groq and Google AI Studio need an API key (GROQ_API_KEY /
GOOGLE_GEMINI_API_KEY from the environment or chco .env); when the key is absent the channel is skipped cleanly.
Freshly indexed AA models are diffed against DIR/aa_index.json (slug snapshot): new listings are reported, with a
⭐ when the slug exactly matches a model free on a full channel. The first run only seeds the snapshot.
"""
import json, os, re, sys, time, urllib.request, datetime as dt
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
    ("Kilo Code", "nvidia/nemotron-3.5-content-safety:free"): "safety classifier, not a chat model",
    ("OpenRouter", "google/lyria-3-pro-preview"): "music model",
    ("OpenRouter", "google/lyria-3-clip-preview"): "music model",
    ("Vercel AI Gateway", "inclusionai/ling-3.1-flash"): "same $0 model as the tracked -free id",
    ("Vercel AI Gateway", "reflection/beam"): "no Vercel free lane (standard id billed; -free id untested, needs one call to qualify per ADR-022) — re-report suppressed, ask Dim",
}


# catalogue entries that are not chat models even when they cost $0 (SiliconFlow's own subType values)
NOT_CHAT = {"embedding", "reranker", "speech-to-text", "text-to-image", "text-to-speech", "text-to-video", "image-to-video"}


def get(url, timeout=60, headers=None):
    h = dict(UA)
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def env_key(var):
    """API key for `var` from the environment, else parsed out of a chco .env at run time. Never printed, never stored."""
    v = os.environ.get(var)
    if v:
        return v.strip()
    for d in CHCO_HOME:
        f = Path(d).expanduser() / ".env"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if line.startswith(var + "=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


class Skip(Exception):
    """Raised by a keyed fetcher when its required env var has no key: skip the channel, do not alert."""

    def __init__(self, var):
        self.var = var


def aa_key():
    """AA_API_KEY from the environment, else parsed out of chco .env at run time. Never printed, never stored."""
    return env_key("AA_API_KEY")


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


def nzero(*vals):
    """Numeric zero: Kilo writes prices as "0.000000000000", which the string zero() does not match."""
    try:
        return all(float(v) == 0 for v in vals)
    except (TypeError, ValueError):
        return False


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


def kilo():
    # free = the gateway's own isFree flag plus prompt/completion price 0 (checked 2026-10-27); router pseudo-models dropped
    d = json.loads(get("https://api.kilo.ai/api/gateway/models"))["data"]
    return {m["id"]: m.get("name", m["id"]) for m in d
            if m.get("isFree") and nzero(m.get("pricing", {}).get("prompt"), m.get("pricing", {}).get("completion"))
            and "text" in (m.get("architecture", {}).get("output_modalities") or ["text"])
            and not m["id"].startswith(("kilo-auto/", "openrouter/"))}  # router pseudo-models are routing meta, not models


def siliconflow():
    # free = model-level price "0" (¥/M tokens) on the China model plaza; v1/models is 401 without a key and no chco key exists
    txt = get("https://siliconflow.cn/models").replace('\\"', '"')
    if '{"modelId":"' not in txt:
        raise RuntimeError("model plaza page no longer embeds the model list (page shape changed)")
    free = {}
    for c in txt.split('{"modelId":"')[1:]:
        mid, price = re.search(r'"modelName":"([^"]+)"', c), re.search(r'"price":"?(-?[0-9.]+)"?', c)
        sub = re.search(r'"subType":"([^"]*)"', c)
        if sub and sub.group(1) in NOT_CHAT:
            continue  # embedding / reranker / ASR / image endpoints: not a lane candidate even when $0
        if mid and price and nzero(price.group(1)):
            name = re.search(r'"DisplayName":"([^"]+)"', c)  # field order is not stable, so pull each independently
            free[mid.group(1)] = name.group(1) if name else mid.group(1)
    return free


def ovh():
    # free cannot be read: the catalogue page carries no prices (checked 2026-10-27) and each model's keyless
    # /v1/models returns id only, while our lanes ride the anonymous rate-limited lane (2 req/min) — availability list, gone check
    html = get("https://www.ovhcloud.com/en-gb/public-cloud/ai-endpoints/catalog/")
    ids = re.findall(r'aria-label="([^"]+)"\s+href="/en-gb/public-cloud/ai-endpoints/catalog/', html)
    if not ids:
        raise RuntimeError("OVH catalogue page no longer lists models (page shape changed)")
    return {i: i for i in ids}


def groq():
    # keyed /v1/models: no per-model price (free tier is rate-limited), so availability only; every id kept, incl. audio
    k = env_key("GROQ_API_KEY")
    if not k:
        raise Skip("GROQ_API_KEY")
    d = json.loads(get("https://api.groq.com/openai/v1/models", headers={"Authorization": "Bearer " + k}))["data"]
    return {m["id"]: m.get("name", m["id"]) for m in d}


def google():
    # keyed v1beta/models: a free tier is rate-limited per model, not a $0 price, so availability only
    k = env_key("GOOGLE_GEMINI_API_KEY")
    if not k:
        raise Skip("GOOGLE_GEMINI_API_KEY")
    out, token = {}, None
    for _ in range(10):  # paged: a truncated list would read as every unlisted lane having left (false gone)
        q = f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200" + (f"&pageToken={token}" if token else "")
        d = json.loads(get(q, headers={"x-goog-api-key": k}))
        out.update({m["name"].split("models/", 1)[-1]: m.get("displayName") or m["name"] for m in d.get("models", [])})
        token = d.get("nextPageToken")
        if not token:
            break
    return out


def aihubmix():
    # plain OpenAI list, no pricing at all: their free-routed models carry a "-free" id suffix
    d = json.loads(get("https://api.aihubmix.com/v1/models"))["data"]
    return {m["id"]: m["id"] for m in d if m["id"].endswith("-free")}


# each catalogue: name as in lanes.json -> (fetcher, "full" = can report new $0 models | "gone" = availability list for the gone check only)
CATALOGUES = {
    "OpenRouter": (openrouter, "full"),
    "OpenCode Zen": (lambda: opencode("https://opencode.ai/zen/v1/models", "opencode"), "full"),
    "OpenCode Go": (lambda: opencode("https://opencode.ai/zen/go/v1/models", "opencode-go"), "full"),
    "Vercel AI Gateway": (vercel, "full"),
    "Kilo Code": (kilo, "full"),
    "SiliconFlow": (siliconflow, "full"),
    "OVHcloud AI Endpoints": (ovh, "gone"),
    "Groq": (groq, "gone"),
    "Google AI Studio": (google, "gone"),
    "AIHubMix": (aihubmix, "gone"),
}
# a new full channel's first read is a baseline run (reporting its whole onboarding set would flood); the four
# original ones and the gone-only ones need no baseline: they report new every day, or never report new at all
BASELINED = {"Kilo Code", "SiliconFlow"}


def _slug(name_or_id):
    """AA slug our model_id most likely maps to (last path segment, stripped of the free-suffix and punctuation)."""
    return re.sub(r"[^a-z0-9]+", "-", name_or_id.split("/")[-1].lower().replace(":free", "").replace("-free", "")).strip("-")


def aa_index(name_or_id, slugs, cache={}):
    """Best-effort AA lookup by slug guess; None when AA has no page. The slug space and the index come from
    the AA data API when it is reachable; otherwise from the AA sitemap plus one page per slug (the old route)."""
    base = _slug(name_or_id)
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


def aa_diff(out, watched, cap=15):
    """New Artificial Analysis listings since the last run: added = current slugs - snapshot slugs, reusing the
    same single aa_table() call. First ever run only seeds the snapshot; the snapshot is written after a
    successful call only, so a failed run never clobbers it. (lines, entries, baseline_count)."""
    table = aa_table()
    if not table:
        return [], [], None  # no key / call failed: skip silently, keep the old snapshot
    f = out / "aa_index.json"
    try:
        prev = set(json.loads(f.read_text())) if f.exists() else set()
    except Exception:
        prev = set()  # a corrupt snapshot costs one day of diff, not the whole run: it is reseeded below
    cur = set(table)
    if prev and len(cur) < 0.9 * len(prev):
        return [], [], None  # a short AA payload: keep the snapshot, or next run would call the whole library "new"
    f.write_text(json.dumps(sorted(cur), ensure_ascii=False))  # successful call: refresh the snapshot
    if not prev:
        return [], [], len(cur)  # baseline run: nothing to report yet, just note the count
    keys = []  # exact slug only: a prefix match would star a different model (Qwen3-8B vs Qwen3-8B-Instruct)
    for w in watched:
        b = _slug(w[0])
        if b:
            keys.append((b, w))
    entries = []
    for s in sorted(cur - prev):
        r = table[s]
        v = round(float(r["aa"])) if r["aa"] is not None else None
        hit = next((w for b, w in keys if s == b), None)
        entries.append({"slug": s, "name": r["name"], "aa": v, "url": f"https://artificialanalysis.ai/models/{s}",
                        "free": bool(hit), "channel": hit[2] if hit else None, "model_id": hit[0] if hit else None})
    if not entries:
        return [], [], None
    entries.sort(key=lambda e: (not e["free"], -(e["aa"] or -1)))  # a new listing we can offer for free leads
    lines = [f"📰 AA 新收录 {len(entries)} 个"]
    stars = [e for e in entries if e["free"]]
    plain = [e for e in entries if not e["free"]]
    for e in stars + plain[:cap]:
        tier = ""
        if e["free"]:
            a = e["aa"] or 0
            tier = (f" · ≥{MAIN_BAR} main-tier" if a >= MAIN_BAR else f" · ≥{BORDER_BAR} borderline" if a >= BORDER_BAR
                    else f" · ≥{PASS_BAR} pass-tier" if a >= PASS_BAR else f" · below {PASS_BAR}")
        lines.append(f"  {'⭐' if e['free'] else ''}{e['name']} · AA {e['aa'] if e['aa'] is not None else '—'} ({e['url']})"
                     + (f" · free on {e['channel']}: {e['model_id']}" if e["free"] else "") + tier)
    if len(plain) > cap:
        lines.append(f"  … +{len(plain) - cap} more (see latest.json)")
    return lines, entries, None


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
    new, gone, errors, skipped = [], [], [], []
    baseline_lines = []  # (channel, total free, [untracked entries]) printed only on a channel's first baseline run
    watched = []         # (model_id, name, channel) for every catalogue read this run, for the AA new-listing match
    fail_f = out / "source_failures.json"  # P18: single-day failure is logged, alert only after 2 consecutive days
    fails = json.loads(fail_f.read_text()) if fail_f.exists() else {}
    cat_f = out / "catalogue_state.json"  # per-channel baseline id lists, so onboarding a new channel does not flood
    cat = json.loads(cat_f.read_text()) if cat_f.exists() else {}
    today = dt.date.today().isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    for ch, (fetch, mode) in CATALOGUES.items():
        try:
            try:
                free = fetch()
            except Skip:
                raise  # no key: skip cleanly, never retry-and-alert
            except Exception:
                time.sleep(30)
                free = fetch()  # one retry ~30s later (P18)
            fails.pop(ch, None)
        except Skip as e:
            skipped.append(ch)  # goes to latest.json; voiced only on the weekly heartbeat, because empty stdout is how the daily job stays silent
            if "--heartbeat" in sys.argv:
                print(f"ℹ️ {ch} skipped: no {e.var} key")
            continue
        except Exception as e:
            prev = fails.get(ch, {})
            if prev.get("date") == today:
                streak = prev.get("streak", 1)
            elif prev.get("date") == yesterday:
                streak = prev.get("streak", 0) + 1
            else:
                streak = 1
            fails[ch] = {"date": today, "streak": streak, "error": str(e)[:80]}
            if streak >= 2:
                errors.append(f"{ch}: {str(e)[:80]}")
            else:
                print(f"ℹ️ {ch} catalogue unreadable, retry 1× failed; logged, no alert (1st day)")
            continue
        if mode == "full":  # a "gone" channel's dict is an availability list, not a free list: never new, never AA ⭐
            watched += [(mid, name, ch) for mid, name in free.items() if (ch, mid) not in IGNORE]
            first = ch in BASELINED and ch not in cat
            base = set(cat.get(ch, []))  # read before seeding, or the first run would find nothing to inventory
            if first:
                cat[ch] = sorted(free)  # seeded once: the onboarding set is handed to Dim as a baseline, not re-reported daily
            cands = [(mid, name) for mid, name in free.items()
                     if (ch, mid) not in tracked and (ch, mid) not in IGNORE and mid not in base]
            if first:
                ent = sorted(({"channel": ch, "model_id": mid, "name": name, "aa": aa_index(mid, slugs)[0]} for mid, name in cands),
                             key=lambda x: -(x["aa"] or -1))
                if ent:
                    baseline_lines.append((ch, len(free), ent))
            else:
                for mid, name in cands:
                    aa, url = aa_index(mid, slugs)
                    new.append({"channel": ch, "model_id": mid, "name": name, "aa": aa, "aa_url": url, "pool_candidate": bool(aa and aa >= POOL_BAR)})
        for (c, mid), l in live.items():
            if c == ch and mid not in free:
                gone.append({"channel": ch, "model_id": mid, "lane": l["id"], "status": l["status"], "note": WATCH_GONE.get((ch, mid))})
    back = [{"channel": c, "model_id": m, "note": n} for (c, m), n in WATCH_RETURN.items()
            if any(x["channel"] == c and x["model_id"] == m for x in new)]
    new.sort(key=lambda x: -(x["aa"] or -1))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    aa_lines, aa_entries, aa_base = aa_diff(out, watched)  # reuses the one aa_table() call; no-ops without a key
    fail_f.write_text(json.dumps(fails, ensure_ascii=False, indent=1))
    cat_f.write_text(json.dumps(cat, ensure_ascii=False, indent=1))
    latest = {"checked": now, "back": back, "new": new, "gone": gone, "errors": errors,
              "skipped": skipped, "baseline": [e for _, _, ents in baseline_lines for e in ents], "aa_new": aa_entries}
    if aa_base is not None:
        latest["aa_new_baseline"] = aa_base  # first AA run: snapshot seeded, nothing to diff yet
    (out / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1))
    lines = aa_recheck(out, slugs) + page_changes(out) + [f"🔁 back in a free catalogue: {x['model_id']} · {x['channel']} → {x['note']}" for x in back]
    if new:
        lines.append(f"🆕 {len(new)} free model(s) not on freetokens yet:")
        for x in new:
            tag = "⭐ pool candidate " if x["pool_candidate"] else ""
            if x["pool_candidate"]: tag = "⭐ main-tier candidate " if x["aa"] >= MAIN_BAR else "◐ borderline candidate " if x["aa"] >= BORDER_BAR else "○ pass-tier candidate (retrieval / docs only) "
            lines.append(f"  {tag}{x['name']} · {x['channel']} · {x['model_id']} · AA {x['aa'] if x['aa'] is not None else '—'}")
    for ch, n, ent in baseline_lines:
        lines.append(f"🧱 baseline · {ch}: {n} free model(s), {len(ent)} not on freetokens yet:")
        for e in ent[:25]:
            lines.append(f"  {e['name']} · {e['model_id']} · AA {e['aa'] if e['aa'] is not None else '—'}")
        if len(ent) > 25:
            lines.append(f"  … +{len(ent) - 25} more (see latest.json)")
    lines += aa_lines
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
