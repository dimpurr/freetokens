#!/usr/bin/env python3
"""Site observability without client-side tracking (stdlib only). See OBSERVE.md.

    python3 tools/observe.py logs FILE...            # nginx combined logs -> per-day traffic JSON
    python3 tools/observe.py health [--watch PATH]   # site up, deploy age, data freshness -> JSON
    python3 tools/observe.py links                   # channel and source links that look broken -> JSON
    python3 tools/observe.py report --daily|--weekly [--logs FILE...] [--watch PATH]
                                                     # text for Telegram; --daily prints nothing when all is well

Traffic counts exclude bots (by user agent) and the IPs in FT_OBSERVE_IGNORE_IPS (comma-separated: own machines).
"Browsers" = distinct IPs that loaded /assets/data.js, i.e. ran the page's JavaScript: the closest thing to real visitors.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://freetokens.fyi"
STALE_DAYS = 7  # a live lane not re-checked for this long is due for a re-check (shown on the site too)
UA = {"User-Agent": "freetokens-observe/1 (+https://freetokens.fyi)"}

LINE = re.compile(r'(\S+) \S+ \S+ \[(\d+/\w+/\d+):[^\]]+\] "(\S+) (\S+)[^"]*" (\d+) \S+ "([^"]*)" "([^"]*)"')
# paths only freetokens serves: used to pick our lines out of kafu's shared log (before 2026-10-08 the site had no log of its own)
SITE_PATH = re.compile(r"^/(models/|channels/|makers|lanes|timeline|methodology|assets/(data|common)\.js|feed\.xml|og\.png|llms\.txt)")
BOT = re.compile(r"(?i)bot|crawl|spider|slurp|preview|facebookexternal|curl|python|wget|go-http|headless|playwright|httpx|axios|"
                 r"node-fetch|scrapy|ahrefs|semrush|petal|bytespider|gpt|claude|perplexity|anthropic|cohere|google-|feedfetcher|"
                 r"lighthouse|monitor|freetokens-")
LLM_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
            "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "Bytespider", "CCBot", "cohere-ai",
            "meta-externalagent", "Amazonbot", "DuckAssistBot", "MistralAI-User"]
SEARCH_BOTS = ["Googlebot", "bingbot", "YandexBot", "Baiduspider", "DuckDuckBot", "Applebot", "Sogou", "360Spider"]


def get(url, timeout=30, head=False):
    req = urllib.request.Request(url, headers=UA, method="HEAD" if head else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, (b"" if head else r.read())


# ---------- logs ----------

def parse_logs(files):
    ignore = {x.strip() for x in os.environ.get("FT_OBSERVE_IGNORE_IPS", "").split(",") if x.strip()}
    days = defaultdict(lambda: {"views": 0, "visitors": set(), "browsers": set(), "pages": Counter(), "referrers": Counter(),
                                "llm_bots": Counter(), "search_bots": Counter(), "other_bots": 0, "feed": 0, "llms_txt": 0,
                                "ai_user_pages": Counter(), "ai_landings": Counter()})
    USER_FETCH = ("ChatGPT-User", "Perplexity-User", "Claude-User", "MistralAI-User")  # an assistant reading a page for a person, live
    for f in files:
        own_log = "freetokens" in Path(f).name  # site-specific log: every line is ours; shared log: our paths only
        for line in open(f, errors="ignore"):
            m = LINE.match(line)
            if not m:
                continue
            ip, day, _, path, status, ref, ua = m.groups()
            own_ref = "freetokens.fyi" in ref
            if not own_log and not SITE_PATH.match(path) and not own_ref:
                continue
            d = days[dt.datetime.strptime(day, "%d/%b/%Y").date().isoformat()]
            llm = next((b for b in LLM_BOTS if b.lower() in ua.lower()), None)
            srch = next((b for b in SEARCH_BOTS if b.lower() in ua.lower()), None)
            if llm:
                d["llm_bots"][llm] += 1
                if llm in USER_FETCH and SITE_PATH.match(path):  # only our own paths: scanners fake this user agent
                    d["ai_user_pages"][path.split("?")[0]] += 1
                continue
            if srch:
                d["search_bots"][srch] += 1; continue
            if BOT.search(ua):
                d["other_bots"] += 1; continue
            if ip in ignore:
                continue
            p = path.split("?")[0]
            src = re.search(r"utm_source=([a-z.]+)", path)
            if src and src.group(1) in ("chatgpt.com", "perplexity", "perplexity.ai", "claude.ai", "copilot.com", "gemini.google.com"):
                d["ai_landings"][f"{p} ← {src.group(1)}"] += 1
            if p == "/feed.xml": d["feed"] += 1
            if p == "/llms.txt": d["llms_txt"] += 1
            if p.startswith("/assets/data.js"):
                d["browsers"].add(ip); continue
            if status.startswith("2") and not p.startswith("/assets") and p not in ("/favicon.svg", "/robots.txt"):
                d["views"] += 1; d["visitors"].add(ip); d["pages"][p] += 1
                if ref not in ("", "-") and not own_ref:
                    d["referrers"][re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", ref)] += 1
    out = {}
    for k, d in sorted(days.items()):
        out[k] = {"views": d["views"], "visitors": len(d["visitors"]), "browsers": len(d["browsers"]),
                  "top_pages": d["pages"].most_common(8), "referrers": d["referrers"].most_common(8),
                  "llm_bots": dict(d["llm_bots"]), "search_bots": dict(d["search_bots"]), "other_bots": d["other_bots"],
                  "feed": d["feed"], "llms_txt": d["llms_txt"],
                  "ai_user_pages": d["ai_user_pages"].most_common(10), "ai_landings": d["ai_landings"].most_common(10)}
    return out


# ---------- health ----------

def lanes_stale(today=None):
    today = today or dt.date.today()
    out = []
    for l in json.loads((ROOT / "data/lanes.json").read_text()):
        if l["status"] in ("live", "overdue"):
            age = (today - dt.date.fromisoformat(l["checked"]["date"][:10])).days
            if age > STALE_DAYS:
                out.append({"lane": l["id"], "checked": l["checked"]["date"], "days": age})
    return sorted(out, key=lambda x: -x["days"])


def health(watch_path=None):
    h = {"checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "pages": {}, "problems": []}
    for p in ("/", "/lanes", "/timeline", "/makers", "/feed.xml", "/sitemap.xml", "/llms.txt"):
        try:
            h["pages"][p] = get(SITE + p, head=True)[0]
        except Exception as e:
            h["pages"][p] = str(e)[:60]
        if h["pages"][p] != 200:
            h["problems"].append(f"{p} answers {h['pages'][p]}")
    try:
        js = get(SITE + "/assets/data.js")[1].decode("utf-8", "ignore")
        built = re.search(r'"built":\s*"(\d{4}-\d{2}-\d{2})"', js).group(1)
        h["deployed_build"] = built
        local = json.loads((ROOT / "data/lanes.json").read_text())
        h["deploy_matches_repo"] = len(re.findall(r'"model_id"', js)) >= len(local)
    except Exception as e:
        h["problems"].append(f"cannot read the deployed data: {str(e)[:60]}")
    h["stale_lanes"] = lanes_stale()
    today = dt.date.today()
    h["stale_offers"] = [o["id"] for o in json.loads((ROOT / "data/offers.json").read_text())
                         if o["status"] in ("live", "listed") and (today - dt.date.fromisoformat((o["checked"]["date"] if isinstance(o["checked"], dict) else o["checked"])[:10])).days > 14]
    if watch_path:
        try:
            w = json.loads(Path(watch_path).expanduser().read_text())
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(w["checked"])).total_seconds() / 3600
            h["watch_age_hours"] = round(age, 1)
            if age > 30:
                h["problems"].append(f"catalogue watch last ran {age:.0f} h ago")
            if w.get("errors"):
                h["problems"].append("catalogue watch could not read: " + "; ".join(w["errors"]))
        except Exception as e:
            h["problems"].append(f"catalogue watch output unreadable: {str(e)[:60]}")
    return h


# ---------- links ----------

def links():
    urls = set()
    for c in json.loads((ROOT / "data/channels.json").read_text()):
        urls |= {u for u in (c.get("links") or {}).values() if u}
        urls.add(c["source"]["url"])
    for l in json.loads((ROOT / "data/lanes.json").read_text()):
        if l["status"] in ("live", "listed", "overdue") and l["limits_stated"].get("source"):
            urls.add(l["limits_stated"]["source"])
    broken, blocked = [], []
    for u in sorted(urls):
        if not u.startswith("http"):
            continue
        try:
            code = get(u, timeout=25)[0]
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            code = str(e)[:40]
        if code in (401, 403, 429):
            blocked.append([u, code])  # bot protection, not a dead page
        elif code != 200:
            broken.append([u, code])
    return {"checked": len(urls), "broken": broken, "blocked_for_bots": blocked}


# ---------- search engines ----------

def gsc(days=7, site="sc-domain:freetokens.fyi"):
    """Google Search Console via the local gcloud user credentials (scope webmasters.readonly).
    Quota project: FT_GSC_QUOTA_PROJECT (default mellow-app-25eaf, where the Search Console API is enabled)."""
    import subprocess, urllib.parse
    tok = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"], capture_output=True, text=True, timeout=60).stdout.strip()
    if not tok:
        return {"error": "no gcloud token (run gcloud auth application-default login with webmasters.readonly)"}
    end = dt.date.today() - dt.timedelta(days=2)  # Search Console data lags about two days
    start = end - dt.timedelta(days=days - 1)
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(site, safe='')}/searchAnalytics/query"
    hdr = {"Authorization": "Bearer " + tok, "Content-Type": "application/json",
           "x-goog-user-project": os.environ.get("FT_GSC_QUOTA_PROJECT", "mellow-app-25eaf")}
    def q(dims, n=10):
        body = json.dumps({"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dims, "rowLimit": n}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdr), timeout=60) as r:
            return json.load(r).get("rows", [])
    try:
        tot = q([], 1)
        return {"start": start.isoformat(), "end": end.isoformat(),
                "clicks": tot[0]["clicks"] if tot else 0, "impressions": tot[0]["impressions"] if tot else 0,
                "position": round(tot[0]["position"], 1) if tot else None,
                "queries": [(r["keys"][0], r["clicks"], r["impressions"]) for r in q(["query"])],
                "pages": [(r["keys"][0].replace("https://freetokens.fyi", "") or "/", r["clicks"], r["impressions"]) for r in q(["page"])]}
    except Exception as e:
        return {"error": str(e)[:120]}


def bing(site="https://freetokens.fyi/"):
    """Bing Webmaster Tools API (BING_WEBMASTER_API_KEY from the environment or chco .env)."""
    key = os.environ.get("BING_WEBMASTER_API_KEY")
    if not key:
        envf = Path.home() / "WorkflowUser/Code/Project/dimresearchcode/.env"
        if envf.exists():
            key = next((l.split("=", 1)[1].strip().strip('"') for l in envf.read_text().splitlines() if l.startswith("BING_WEBMASTER_API_KEY=")), None)
    if not key:
        return {"error": "no BING_WEBMASTER_API_KEY"}
    def call(m):
        with urllib.request.urlopen(f"https://ssl.bing.com/webmaster/api.svc/json/{m}?siteUrl={site}&apikey={key}", timeout=60) as r:
            return json.load(r).get("d") or []
    try:
        traffic, queries = call("GetRankAndTrafficStats")[-7:], call("GetQueryStats")
        return {"clicks": sum(x.get("Clicks", 0) for x in traffic), "impressions": sum(x.get("Impressions", 0) for x in traffic),
                "queries": sorted(((q.get("Query"), q.get("Clicks", 0), q.get("Impressions", 0)) for q in queries), key=lambda x: -x[2])[:6], "days": len(traffic)}
    except Exception as e:
        return {"error": str(e)[:120]}


# ---------- report ----------

def report(kind, log_files, watch_path):
    h = health(watch_path)
    lines = []
    if h["problems"]:
        lines.append("⚠️ " + " · ".join(h["problems"]))
    st = h["stale_lanes"]
    if kind == "weekly":
        lines.insert(0, f"📈 freetokens weekly · {dt.date.today().isoformat()}")
        if log_files:
            days = parse_logs(log_files)
            last = sorted(days)[-7:]
            tot = lambda k: sum(days[d][k] for d in last)
            pages, refs, llm, srch, aiu, ail = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
            for d in last:
                pages.update(dict(days[d]["top_pages"])); refs.update(dict(days[d]["referrers"]))
                aiu.update(dict(days[d]["ai_user_pages"])); ail.update(dict(days[d]["ai_landings"]))
                llm.update(days[d]["llm_bots"]); srch.update(days[d]["search_bots"])
            lines.append(f"Visitors (7 d): {tot('browsers')} browser loads · {tot('visitors')} IPs · {tot('views')} page views · "
                         f"daily browsers {', '.join(str(days[d]['browsers']) for d in last)}")
            lines.append("Top pages: " + ", ".join(f"{p} {n}" for p, n in pages.most_common(6)))
            lines.append("Referrers: " + (", ".join(f"{r} {n}" for r, n in refs.most_common(6)) or "none recorded"))
            lines.append("AI crawlers: " + (", ".join(f"{b} {n}" for b, n in llm.most_common()) or "none") +
                         " · search bots: " + (", ".join(f"{b} {n}" for b, n in srch.most_common(5)) or "none") +
                         f" · feed {tot('feed')} · llms.txt {tot('llms_txt')}")
            lines.append("Pages AI assistants read for someone: " + (", ".join(f"{p} {n}" for p, n in aiu.most_common(8)) or "none"))
            lines.append("Visitors who came from an AI answer: " + (", ".join(f"{p} {n}" for p, n in ail.most_common(6)) or "none"))
        g = gsc()
        if g.get("error"):
            lines.append("Google Search: unavailable (" + g["error"] + ")")
        else:
            lines.append(f"Google Search {g['start'][5:]}–{g['end'][5:]}: {g['clicks']} clicks · {g['impressions']} impressions · avg position {g['position'] or '—'}"
                         + (" · queries: " + ", ".join(f"{k} {c}/{i}" for k, c, i in g["queries"][:6]) if g["queries"] else " · queries hidden (too few)")
                         + (" · pages: " + ", ".join(f"{k} {i}" for k, c, i in g["pages"][:5]) if g["pages"] else ""))
        b = bing()
        if b.get("error"):
            lines.append("Bing: unavailable (" + b["error"] + ")")
        else:
            lines.append("Bing: no data yet" if not b["days"] and not b["queries"] else
                         f"Bing ({b['days']} days): {b['clicks']} clicks · {b['impressions']} impressions" + (" · queries: " + ", ".join(f"{k} {c}/{i}" for k, c, i in b["queries"]) if b["queries"] else ""))
        lk = links()
        lines.append(f"Links: {len(lk['broken'])} broken of {lk['checked']}" + (": " + "; ".join(f"{u} ({c})" for u, c in lk["broken"][:8]) if lk["broken"] else ""))
        lines.append(f"Data: {len(st)} live lane(s) not re-checked for >{STALE_DAYS} days" + (": " + ", ".join(f"{x['lane']} ({x['days']} d)" for x in st[:12]) if st else ""))
        so = h.get("stale_offers", [])
        lines.append(f"Programs: {len(so)} not re-checked for >14 days" + (": " + ", ".join(so[:10]) if so else ""))
        lines.append(f"Deployed build {h.get('deployed_build', '?')} · site pages {'all 200' if not any(v != 200 for v in h['pages'].values()) else h['pages']}")
    elif st and dt.date.today().weekday() == 3:  # daily: stale data is a Thursday nudge, not a daily one
        lines.append(f"🕰️ {len(st)} live lane(s) due for a re-check (>{STALE_DAYS} days): " + ", ".join(x["lane"] for x in st[:12]))
    if lines and kind == "daily":
        lines.insert(0, f"freetokens health · {dt.date.today().isoformat()}")
    return "\n".join(lines)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd, rest = argv[0], argv[1:]
    opt = lambda k: rest[rest.index(k) + 1] if k in rest else None
    files = rest[rest.index("--logs") + 1:] if "--logs" in rest else ([a for a in rest if not a.startswith("--")] if cmd == "logs" else [])
    files = [f for f in files if not f.startswith("--") and Path(f).exists()]
    if cmd == "logs":
        print(json.dumps(parse_logs(files), ensure_ascii=False, indent=1))
    elif cmd == "health":
        print(json.dumps(health(opt("--watch")), ensure_ascii=False, indent=1))
    elif cmd == "links":
        print(json.dumps(links(), ensure_ascii=False, indent=1))
    elif cmd == "report":
        text = report("weekly" if "--weekly" in rest else "daily", files, opt("--watch"))
        if text:
            print(text)
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
