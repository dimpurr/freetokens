#!/usr/bin/env python3
"""Daily watch: compare public free-model catalogues with data/lanes.json (stdlib only, no LLM).

    python3 tools/watch.py [--out DIR] [--heartbeat]

Prints a short report only when something changed (new $0 models, or tracked lanes missing from a catalogue);
prints nothing otherwise, unless --heartbeat. Writes DIR/latest.json (default ~/scratch/DimResearchS/freetokens-watch).
A free model whose ID ends in a date and resembles a tracked ID is marked for manual confirmation (a snapshot of that model, or a separate one; ADR-037).
A model that is not on freetokens yet has no FT Intelligence score, so a new free model is listed without one (ADR-036:
no Artificial Analysis calls and no page scraping here). The weekly self-check (--heartbeat) lists tracked lanes whose FTI
(its centre, for a band) is at or above the pass floor.
Channels: OpenRouter, OpenCode Zen/Go, Vercel AI Gateway, Kilo Code and SiliconFlow report $0 models (full);
OVHcloud AI Endpoints, Groq, Google AI Studio and AIHubMix are gone-only (no per-model $0 price in their
machine-readable list, so they only flag tracked lanes that vanished).
A new channel's first read is a baseline run: it reports no "new" (that would flood on onboarding) and instead
prints the untracked free inventory. Groq and Google AI Studio need an API key (GROQ_API_KEY /
GOOGLE_GEMINI_API_KEY from the environment or chco .env); when the key is absent the channel is skipped cleanly.
"""
import json, os, re, sys, time, urllib.request, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "freetokens-watch/1 (+https://freetokens.fyi)"}
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
        return 20, 24, 28
    cands = [os.environ.get("FT_POOL_POLICY", "")] + [os.path.expanduser(p + "/tools/free-pool/arms.toml") for p in
             ("~/WorkflowUser/Code/Project/dimresearchcode", "~/WorkflowUser/Code/Personal/dimresearchcode", "~/Workflow/code/project/dimresearchcode")]
    for c in cands:
        if c and os.path.exists(c):
            pol = tomllib.load(open(c, "rb")).get("policy", {})
            return pol.get("pass_bar", 20), pol.get("pool_bar", 24), pol.get("main_bar", 28)
    return 20, 24, 28


PASS_BAR, BORDER_BAR, MAIN_BAR = _pool_policy()  # FTI scale (the FTAA numbers, kept by ADR-036; main-session ruling 2026-11-01): 及格层 20-24 (retrieval / docs only), 擦线层 24-28, 主层 >= 28 (was 25/30/35 on the old AA scale; Dim, 2026-10-08)
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
# SiliconFlow cross-check state (populated by siliconflow()): model ids whose pricing-table entry contradicts the directory,
# and model ids that are directory-only (not found in the rendered pricing table).
SF_CONFLICTS = []
SF_WEAK = set()


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


DATED_ID = re.compile(r"[-_](?:\d{4}|\d{6}|\d{8})(?::free|-free)?$")


def snapshot_hint(mid, tracked_ids):
    """ADR-037: an ID ending in a date (-0731, -1017, -20260731) is often an in-place snapshot of a model we already track.
    Returns the tracked model_id with the same stem, or None. Only a hint: a person decides (snapshot or separate model)."""
    m = DATED_ID.search(mid)
    if not m:
        return None
    stem = mid[:m.start()].split("/")[-1].replace(":free", "")
    for t in sorted(tracked_ids):
        base = t.split("/")[-1].replace(":free", "")
        if base != stem and (base.startswith(stem) or stem.startswith(base)) and not DATED_ID.search(t):
            return t
        if base == stem:
            return t
    return None


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
    global SF_CONFLICTS, SF_WEAK
    SF_CONFLICTS = []
    SF_WEAK = set()
    txt = get("https://siliconflow.cn/models").replace('\\\"', '"')
    if '{"modelId":"' not in txt:
        raise RuntimeError("model plaza page no longer embeds the model list (page shape changed)")
    # Cross-check against the rendered pricing table: that table is authoritative for SiliconFlow
    # (the model plaza's price field is only a lead). A model present there with a non-free price is NOT free;
    # a model absent from it keeps the directory judgement but is marked as weak evidence.
    price_table = {}  # model_id (org/model) -> True if free, False if paid, None if unknown
    pricing_html = ""
    try:
        pricing_html = get("https://siliconflow.cn/pricing")
        for m in re.finditer(r'md:hidden">([^<]+)</div>', pricing_html):
            mid = m.group(1).strip()
            seg = pricing_html[m.start():m.start() + 1500]
            if '免费' in seg:
                price_table[mid] = True
            elif '¥' in seg:
                price_table[mid] = False
            else:
                price_table[mid] = None
    except Exception as e:
        print(f"ℹ️ SiliconFlow pricing table unreadable ({str(e)[:60]}); falling back to directory-only (weak evidence)")
        price_table = {}
    free = {}
    for c in txt.split('{"modelId":"')[1:]:
        mid, price = re.search(r'"modelName":"([^"]+)"', c), re.search(r'"price":"?(-?[0-9.]+)"?', c)
        sub = re.search(r'"subType":"([^"]*)"', c)
        if sub and sub.group(1) in NOT_CHAT:
            continue  # embedding / reranker / ASR / image endpoints: not a lane candidate even when $0
        if not (mid and price and nzero(price.group(1))):
            continue
        mid_val = mid.group(1)
        name = re.search(r'"DisplayName":"([^"]+)"', c)  # field order is not stable, so pull each independently
        display = name.group(1) if name else mid_val
        if mid_val in price_table:
            if price_table[mid_val] is False:
                seg = pricing_html[pricing_html.find(mid_val):pricing_html.find(mid_val) + 1500] if mid_val in pricing_html else ''
                prices = re.findall(r'¥\s*([0-9.]+)', seg)
                price_str = '/'.join(prices[:3]) if prices else 'paid (non-free)'
                SF_CONFLICTS.append((mid_val, price_str))
                print(f"⚠️ conflict · SiliconFlow · {mid_val}: directory price 0, pricing table {price_str}")
                continue  # not free
            free[mid_val] = display  # free or unknown-but-present: keep
        else:
            SF_WEAK.add(mid_val)
            free[mid_val] = display  # maintain directory judgement, weak evidence
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


def screen():
    """Weekly self-check (the Dots3 lesson): lanes already in our data that agents may use, score >= POOL_BAR
    (FT Intelligence centre), still free, but never load-tested. Pool membership is not ours to know; just list them."""
    sys.path.insert(0, str(ROOT))
    import build
    models = {m["id"]: m for m in build.load("models")}
    chans = {c["name"]: c for c in build.load_optional("channels", [])}
    out = []
    for l in build.load("lanes"):
        a = (l.get("access") or chans.get(l["channel"], {}).get("access") or {})
        if l["status"] not in ("live", "listed", "overdue") or "no_automation" in a.get("rules", []) or a.get("form") not in ("api", "own_cli"):
            continue
        m = models[l["model"]]
        s = m["ft"]["center"] if m["ft"].get("status") == "ok" else None
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
    tracked_ids = {l["model_id"] for l in lanes}
    live = {(l["channel"], l["model_id"]): l for l in lanes if l["status"] in ("live", "listed", "overdue")}
    new, gone, errors, skipped = [], [], [], []
    baseline_lines = []  # (channel, total free, [untracked entries]) printed only on a channel's first baseline run
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
        if mode == "full":  # a "gone" channel's dict is an availability list, not a free list: never new
            first = ch in BASELINED and ch not in cat
            base = set(cat.get(ch, []))  # read before seeding, or the first run would find nothing to inventory
            if first:
                cat[ch] = sorted(free)  # seeded once: the onboarding set is handed to Dim as a baseline, not re-reported daily
            cands = [(mid, name) for mid, name in free.items()
                     if (ch, mid) not in tracked and (ch, mid) not in IGNORE and mid not in base]
            if first:
                ent = sorted(({"channel": ch, "model_id": mid, "name": name} for mid, name in cands), key=lambda x: x["name"])
                if ent:
                    baseline_lines.append((ch, len(free), ent))
            else:
                for mid, name in cands:
                    new.append({"channel": ch, "model_id": mid, "name": name, "snapshot_hint": snapshot_hint(mid, tracked_ids)})
        for (c, mid), l in live.items():
            if c == ch and mid not in free:
                gone.append({"channel": ch, "model_id": mid, "lane": l["id"], "status": l["status"], "note": WATCH_GONE.get((ch, mid))})
    back = [{"channel": c, "model_id": m, "note": n} for (c, m), n in WATCH_RETURN.items()
            if any(x["channel"] == c and x["model_id"] == m for x in new)]
    new.sort(key=lambda x: x["name"])
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    fail_f.write_text(json.dumps(fails, ensure_ascii=False, indent=1))
    cat_f.write_text(json.dumps(cat, ensure_ascii=False, indent=1))
    latest = {"checked": now, "back": back, "new": new, "gone": gone, "errors": errors,
              "skipped": skipped, "baseline": [e for _, _, ents in baseline_lines for e in ents]}
    (out / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1))
    lines = page_changes(out) + [f"🔁 back in a free catalogue: {x['model_id']} · {x['channel']} → {x['note']}" for x in back]
    if new:
        lines.append(f"🆕 {len(new)} free model(s) not on freetokens yet:")
        for x in new:
            weak = " · weak evidence (not in pricing table)" if (x["channel"] == "SiliconFlow" and x["model_id"] in SF_WEAK) else ""
            hint = f" · 🗓 dated ID, maybe a snapshot of {x['snapshot_hint']}: confirm by hand (snapshot or separate model, ADR-037)" if x.get("snapshot_hint") else ""
            lines.append(f"  {x['name']} · {x['channel']} · {x['model_id']}{weak}{hint}")
    for ch, n, ent in baseline_lines:
        lines.append(f"🧱 baseline · {ch}: {n} free model(s), {len(ent)} not on freetokens yet:")
        for e in ent[:25]:
            weak = " · weak evidence (not in pricing table)" if (ch == "SiliconFlow" and e['model_id'] in SF_WEAK) else ""
            lines.append(f"  {e['name']} · {e['model_id']}{weak}")
        if len(ent) > 25:
            lines.append(f"  … +{len(ent) - 25} more (see latest.json)")
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
