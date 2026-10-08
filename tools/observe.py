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
                                "llm_bots": Counter(), "search_bots": Counter(), "other_bots": 0, "feed": 0, "llms_txt": 0})
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
                d["llm_bots"][llm] += 1; continue
            if srch:
                d["search_bots"][srch] += 1; continue
            if BOT.search(ua):
                d["other_bots"] += 1; continue
            if ip in ignore:
                continue
            p = path.split("?")[0]
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
                  "feed": d["feed"], "llms_txt": d["llms_txt"]}
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
            pages, refs, llm, srch = Counter(), Counter(), Counter(), Counter()
            for d in last:
                pages.update(dict(days[d]["top_pages"])); refs.update(dict(days[d]["referrers"]))
                llm.update(days[d]["llm_bots"]); srch.update(days[d]["search_bots"])
            lines.append(f"Visitors (7 d): {tot('browsers')} browser loads · {tot('visitors')} IPs · {tot('views')} page views · "
                         f"daily browsers {', '.join(str(days[d]['browsers']) for d in last)}")
            lines.append("Top pages: " + ", ".join(f"{p} {n}" for p, n in pages.most_common(6)))
            lines.append("Referrers: " + (", ".join(f"{r} {n}" for r, n in refs.most_common(6)) or "none recorded"))
            lines.append("AI crawlers: " + (", ".join(f"{b} {n}" for b, n in llm.most_common()) or "none") +
                         " · search bots: " + (", ".join(f"{b} {n}" for b, n in srch.most_common(5)) or "none") +
                         f" · feed {tot('feed')} · llms.txt {tot('llms_txt')}")
        lk = links()
        lines.append(f"Links: {len(lk['broken'])} broken of {lk['checked']}" + (": " + "; ".join(f"{u} ({c})" for u, c in lk["broken"][:8]) if lk["broken"] else ""))
        lines.append(f"Data: {len(st)} live lane(s) not re-checked for >{STALE_DAYS} days" + (": " + ", ".join(f"{x['lane']} ({x['days']} d)" for x in st[:12]) if st else ""))
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
