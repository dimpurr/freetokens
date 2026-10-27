#!/usr/bin/env python3
"""Bracket a model's free window from Internet Archive captures (stdlib only, no LLM, ADR-034 ①-b).

    python3 tools/wayback_dates.py URL MODEL_ID [options]

    # one URL holds the whole OpenRouter catalogue, with prices: dates land within hours
    python3 tools/wayback_dates.py https://openrouter.ai/api/v1/models nvidia/nemotron-3-super-120b-a12b:free
    # a model page still free today, and a channel pricing page whose price is only text
    python3 tools/wayback_dates.py https://openrouter.ai/api/v1/models liquid/lfm-2.5-2.6b:free --live
    python3 tools/wayback_dates.py https://channel.dev/models some/model --predicate present
    python3 tools/wayback_dates.py https://channel.dev/models some/model --price loose

Three answers, each with the snapshot link that shows it: the earliest capture where the model is free, the
latest one, and the first capture where it is gone. Every date is an interval between two adjacent captures —
the last one where it was not free and the first where it was — because ADR-034 ④ wants the bracket and the
link, so anyone can re-open the archive and check. Free at the newest capture is reported as "still free at
<date>", never as an end date; --live spends one request on the live page to say whether it holds now.
Nothing is inferred between captures: a short-lived window can be missed by the coarse probe (says so),
and an unreadable capture widens the interval instead of being counted as absence.

Options:
  --from/--to YYYY-MM-DD   window on the capture list (default: everything the archive holds)
  --predicate free|present which signal to bracket (default free; falls back to present, loudly, when the
                           page carries no readable price next to the id)
  --shape auto|json|html   how to read a capture (default auto: parse as JSON, else as text)
  --price auto|loose|off   auto = machine-readable price fields only; loose = also accept "$0"/"Free"/"0/1M"
                           within ~120 chars of the id (flagged loose — always re-open that snapshot);
                           off = presence only
  --price-regex REGEX      your own price rule, searched near the id (wins over auto/loose; a named group
                           holding 0 reads as free, one holding a positive number reads as paid)
  --grid N                 coarse probes that locate the window (default 12; --scan reads every capture)
  --max-fetch N            downloads allowed per run, cache hits are free (default 40)
  --live                   also read the live URL once (one request to the channel, not to the archive)
  --list                   print the capture list only, fetch nothing
  --refresh                ignore cached capture list and cached bytes
  --json                   print the machine record as well (it is always written to the results dir)

Cache: ~/scratch/DimResearchS/freetokens-backfill/ (FT_BACKFILL_DIR) — captures live forever, the capture list
for 24 h. At most one request per second, archive and channel alike (FT_WAYBACK_MIN_INTERVAL); a refused
connection or a 429/5xx answer is retried up to 4 times with 10/20/30 s waits, because the archive refuses in bursts.
Exit: 0 window found · 1 request failed · 2 bad arguments · 3 the archive cannot answer.
"""
import argparse, datetime as dt, gzip, hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

CDX = "https://web.archive.org/cdx/search/cdx"
UA = {"User-Agent": "freetokens-backfill/1 (+https://freetokens.fyi)", "Accept-Encoding": "gzip"}
MIN_INTERVAL = float(os.environ.get("FT_WAYBACK_MIN_INTERVAL", "1.0"))
CDX_TTL = float(os.environ.get("FT_WAYBACK_CDX_TTL", "86400"))
CACHE = Path(os.environ.get("FT_BACKFILL_DIR", "~/scratch/DimResearchS/freetokens-backfill")).expanduser()
FL = "timestamp,original,statuscode,digest,length,mimetype"
CDX_COLS = ("timestamp", "original", "statuscode", "digest", "length", "mimetype")
ID_FIELDS = ("id", "model", "model_id", "slug", "name", "key")
MAIN_PRICE = ("prompt", "completion", "input", "output", "request", "response")
PRICE_KEY = re.compile(r"(?i)^(prompt|completion|input|output|request|response|cache_read|cache_write|per_token|price|cost)$")
PRICE_BLOCK = re.compile(r"(?i)^(pricing|price|cost|costs|rates)$")
SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|bearer|authorization|cookie|password)")
JSON_PRICE = re.compile(r'\\?"(prompt|completion|input|output)\\?"\s*:\s*\\?"?(-?\d*\.?\d+)\\?"?')
LOOSE_PRICE = re.compile(r"(?i)(\$0(?![.\d])|\b0(?:\.0+)?\s*/\s*(?:1M|1K|1k|million|million tokens|tokens)\b|\bfree\b)")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_last = [0.0]


class Fail(Exception):
    pass


class Usage(Exception):
    pass


def polite():
    wait = _last[0] + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()


def http(url, timeout=120, tries=4):
    """One polite request -> (status, bytes). The archive stores bodies compressed and says so two ways, so
    Content-Encoding and the gzip magic are both checked."""
    err = ""
    for attempt in range(tries):
        polite()
        status, body, enc, after = 0, b"", "", None
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                status, body = r.status, r.read()
                enc, after = (r.headers.get("Content-Encoding") or "").lower(), r.headers.get("Retry-After")
        except urllib.error.HTTPError as e:
            status = e.code
            enc, after = (e.headers.get("Content-Encoding") or "").lower(), e.headers.get("Retry-After")
            try:
                body = e.read() or b""
            except Exception:
                body = b""
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        if enc == "gzip" or body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError:
                pass
        if (not status or status in (429, 500, 502, 503, 509)) and attempt < tries - 1:
            time.sleep(min(60.0, float(after) if str(after or "").isdigit() else 10.0 * (attempt + 1)))
            continue
        return status, body, err
    raise Fail(f"gave up on {url}")


def sha(*parts):
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:24]


def slug(url, model_id):
    p = urllib.parse.urlsplit(url)
    return re.sub(r"[^a-z0-9.]+", "-", f"{p.netloc}{p.path}__{model_id}".lower()).strip("-")[:110]


def cached(path, ttl=None):
    if not path.exists():
        return None
    if ttl is not None and time.time() - path.stat().st_mtime > ttl:
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def cdx(url, frm, to, match_type, limit, refresh):
    """Capture list for one URL: 200 responses only, one row per distinct content (collapse=digest)."""
    key = sha("cdx", url, frm, to, match_type, str(limit))
    path = CACHE / "cdx" / f"{key}.json"
    hit = None if refresh else cached(path, CDX_TTL)
    if hit is not None:
        return hit, False
    q = urllib.parse.urlencode({"url": url, "output": "json", "fl": FL, "filter": "statuscode:200",
                                "collapse": "digest", "matchType": match_type, "from": frm, "to": to, "limit": limit})
    for attempt in range(3):
        st, body, err = http(f"{CDX}?{q}")
        text = body.decode("utf8", "replace").strip()
        if st == 200 and (not text or text.startswith("[")):
            break
        if attempt < 2:
            print(f"  ? the CDX index answered HTTP {st}{': ' + clean(text[:60]) if text else ' ' + err}"
                  " — waiting for the archive to settle")
            time.sleep(20)
    else:
        raise Fail(f"the CDX index kept answering HTTP {st}{': ' + clean(text[:80]) if text else ' ' + err}".strip())
    rows = json.loads(text)[1:] if text else []
    out = sorted((dict(zip(CDX_COLS, r)) for r in rows if len(r) >= 4 and re.fullmatch(r"\d{14}", r[0] or "")),
                 key=lambda r: r["timestamp"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out, True


def grab(url, ts, refresh):
    """Raw bytes of one capture (`id_` = the archived record without the archive's own toolbar)."""
    path = CACHE / "snap" / f"{sha(url, ts)}.gz"
    if path.exists() and not refresh:
        return gzip.decompress(path.read_bytes()), True
    st, body, err = http(f"https://web.archive.org/web/{ts}id_/{url}")
    if st != 200 or len(body) < 200:
        raise Fail(f"HTTP {st}, {len(body)} bytes {err}".strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body, 6))
    return body, False


def iso(ts):
    return dt.datetime.strptime(ts, "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%MZ")


def link(ts, url):
    return f"https://web.archive.org/web/{ts}/{url}"


def clean(s, n=150):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return "[redacted]" if SECRET.search(s) else s[:n]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def walk(obj):
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def record_prices(rec):
    """Every price number one catalogue record carries: {field: value}."""
    out = {}

    def scan(d, depth=0):
        if depth > 3:
            return
        for k, v in d.items():
            n = num(v)
            if n is not None and PRICE_KEY.match(str(k)):
                out.setdefault(str(k).lower(), n)
            elif isinstance(v, dict) and PRICE_BLOCK.match(str(k)):
                scan(v, depth + 1)
    scan(rec)
    return out


def read_json(text, model_id, price_mode):
    """Find MODEL_ID as a record inside a catalogue/API body, and read its price."""
    try:
        data = json.loads(text)
    except Exception:
        return {"state": "unknown", "note": "body did not parse as JSON"}
    rec = next((d for d in walk(data) if isinstance(d, dict) and any(isinstance(d.get(k), str)
                and d[k].strip().lower() == model_id.lower() for k in ID_FIELDS)), None)
    if rec is None:
        return {"state": "absent"}
    prices = record_prices(rec)
    main = {k: v for k, v in prices.items() if k in MAIN_PRICE}
    ev = {"prices": prices, "record_name": clean(rec.get("name") or rec.get("title") or "", 80)}
    if price_mode == "off":
        return {"state": "present", "price_basis": "off", "evidence": ev}
    if not main:
        return {"state": "present", "price_basis": "unreadable", "evidence": ev}
    return {"state": "free" if all(v == 0 for v in main.values()) else "paid",
            "price_basis": "catalogue-fields", "evidence": ev}


def page_price(text, hits, mode, regex):
    """The price shown for the model on a text page: the nearest price block after the id."""
    if regex:
        rx = re.compile(regex)
        for h in hits[:80]:
            m = rx.search(text[max(0, h - 300):h + 1500])
            if not m:
                continue
            nums = [num(g) for g in m.groupdict().values()]
            nums = [n for n in nums if n is not None]
            if nums:
                return {"state": "free" if all(n == 0 for n in nums) else "paid", "price_basis": "custom-regex",
                        "evidence": {"match": clean(m.group(0), 160)}}
            return {"state": "free", "price_basis": "custom-regex", "loose": True,
                    "evidence": {"match": clean(m.group(0), 160), "note": "the regex matched no number"}}
        return {"state": "present", "price_basis": "unreadable", "evidence": {"note": "the regex never matched near the id"}}
    for h in hits[:80]:
        found = {m.group(1).lower(): num(m.group(2)) for m in JSON_PRICE.finditer(text[max(0, h - 300):h + 1500])}
        found = {k: v for k, v in found.items() if k in MAIN_PRICE and v is not None}
        if found:
            return {"state": "free" if all(v == 0 for v in found.values()) else "paid",
                    "price_basis": "page-fields", "evidence": {"prices": found}}
    if mode == "loose":
        for h in hits[:80]:
            m = LOOSE_PRICE.search(text[max(0, h - 120):h + 120])
            if m:
                return {"state": "free", "price_basis": "page-text", "loose": True,
                        "evidence": {"context": clean(text[max(0, h - 120):h + 120])}}
    return {"state": "present", "price_basis": "unreadable", "evidence": {"first_snippet": clean(text[hits[0]:hits[0] + 160])}}


def read_text(text, model_id, price_mode, price_regex):
    """Find MODEL_ID in a page body (plain, JSON-escaped, or URL-encoded), then read its price nearby."""
    variants = {model_id, model_id.replace("/", "\\/"), urllib.parse.quote(model_id, safe="")}
    hits = sorted({m.start() for p in variants for m in re.finditer(re.escape(p), text)})
    if not hits:
        return {"state": "absent"}
    if price_mode == "off":
        return {"state": "present", "price_basis": "off", "evidence": {"first_snippet": clean(text[hits[0]:hits[0] + 160])}}
    v = page_price(text, hits, price_mode, price_regex)
    v.setdefault("evidence", {})["id_hits"] = len(hits)
    return v


def read_body(body, model_id, shape, price_mode, price_regex):
    text = body.decode("utf8", "replace")
    shape = shape if shape != "auto" else ("json" if text[:4096].lstrip()[:1] in "[{" else "html")
    if shape == "json":
        v = read_json(text, model_id, price_mode)
        if v["state"] == "unknown":
            v = read_text(text, model_id, price_mode, price_regex)
            v["note"] = "the body did not parse as JSON, so it was read as text"
            shape = "text"
    else:
        v = read_text(text, model_id, price_mode, price_regex)
    v["shape"] = shape
    return v


def hit(v, predicate):
    """Does this verdict answer yes to the signal we bracket? None = the capture told us nothing."""
    if predicate == "present":
        return None if v["state"] == "unknown" else v["state"] != "absent"
    if v["state"] == "free":
        return True
    if v["state"] in ("paid", "absent"):
        return False
    return None


def edge(probe, f, t):
    """Narrow between a capture known to miss (f) and one known to hit (t). Returns (t, f, unreadable_index)."""
    gap = None
    while abs(t - f) > 1:
        m = (f + t) // 2
        try:
            v = probe(m)
        except Fail:
            gap = m
            break
        if v is None:
            gap = m
            break
        if v:
            t = m
        else:
            f = m
    return t, f, gap


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("url", nargs="?")
    ap.add_argument("model_id", nargs="?")
    ap.add_argument("--from", dest="frm", default="")
    ap.add_argument("--to", default="")
    ap.add_argument("--predicate", choices=("free", "present"), default="free")
    ap.add_argument("--shape", choices=("auto", "json", "html"), default="auto")
    ap.add_argument("--price", choices=("auto", "loose", "off"), default="auto")
    ap.add_argument("--price-regex", default="")
    ap.add_argument("--grid", type=int, default=12)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--max-fetch", type=int, default=40)
    ap.add_argument("--limit", type=int, default=4000)
    ap.add_argument("--match-type", default="exact")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args(argv)
    if a.help or not (a.url and a.model_id):
        print(__doc__)
        return 0 if a.help else 2
    url = a.url.strip()
    for day, name in ((a.frm, "--from"), (a.to, "--to")):
        if day and not DAY.fullmatch(day):
            raise Usage(f"{name} wants YYYY-MM-DD, got {day!r}")
    if a.price_regex:
        try:
            re.compile(a.price_regex)
        except re.error as e:
            raise Usage(f"--price-regex does not compile: {e}")
    CACHE.mkdir(parents=True, exist_ok=True)
    snaps, fresh = cdx(url, a.frm.replace("-", ""), a.to.replace("-", ""), a.match_type, a.limit, a.refresh)
    span = f"{iso(snaps[0]['timestamp'])} → {iso(snaps[-1]['timestamp'])}" if snaps else "no captures"
    print(f"· {url}\n  {len(snaps)} distinct captures in the archive ({span}){' · list from cache' if not fresh else ''}")
    if not snaps:
        print("✗ the archive holds no capture of this URL in that window: widen --from/--to, or use the channel's "
              "catalogue / API URL instead of a page that was never archived")
        return 3
    if a.list:
        for r in snaps:
            print(f"  {iso(r['timestamp'])}  {link(r['timestamp'], url)}")
        return 0

    n = len(snaps)
    notes, unreadable, fetched = [], [], [0]
    states, verdicts = {}, {}

    def probe(i):
        if i in verdicts:
            return verdicts[i]
        if fetched[0] >= a.max_fetch:
            raise Fail(f"--max-fetch {a.max_fetch} reached before the probe at {iso(snaps[i]['timestamp'])}: "
                       f"raise --max-fetch, narrow the window, or let the cache do the rest")
        try:
            body, from_cache = grab(url, snaps[i]["timestamp"], a.refresh)
        except Fail as e:
            print(f"  ? {iso(snaps[i]['timestamp'])} unreadable ({e}) — treated as a gap, never as absence")
            unreadable.append(snaps[i]["timestamp"])
            states[i], verdicts[i] = {"state": "unknown"}, None
            return None
        fetched[0] += 1
        v = read_body(body, a.model_id, a.shape, a.price, a.price_regex)
        states[i], verdicts[i] = v, hit(v, a.predicate)
        price = v.get("evidence", {}).get("prices") or ""
        print(f"  {'+' if verdicts[i] else '-' if verdicts[i] is False else '?'} {iso(snaps[i]['timestamp'])} "
              f"{v['state']:<8}{v.get('shape','')}{(' ' + json.dumps(price, separators=(',', ':'))) if price else ''}"
              f" {'(cache)' if from_cache else ''}")
        return verdicts[i]

    g = min(max(a.grid, 2), n)
    grid = list(range(n)) if (a.scan or n <= 12) else sorted({round(i * (n - 1) / (g - 1)) for i in range(g)})
    for i in grid:
        probe(i)
    if a.predicate == "free" and any(s.get("price_basis") == "unreadable" for s in states.values()):
        print("  ⚠️ no machine-readable price next to the id on this page: bracketing presence instead, which says "
              "when the model was listed, not when it was free. Use the channel's catalogue/API URL, or --price loose.")
        a.predicate, states, verdicts, notes = "present", {}, {}, notes + ["price not readable on this page: fell back to --predicate present"]
        for i in grid:
            probe(i)
    sig = "free" if a.predicate == "free" else "listed"
    trues = sorted(i for i, v in verdicts.items() if v is True)
    if not trues:
        falses = sum(1 for v in verdicts.values() if v is False)
        print(f"✗ no hit: {falses} of the {len(verdicts)} captures read say the model is not {sig} there. "
              f"The window may sit between two captures (spacing here is often days), the id may be spelled "
              f"differently on this page, or it was {sig} outside {span}. "
              f"Re-read every capture with --scan, or widen the window; {fetched[0]} downloads used.")
        return 3
    seed = trues[len(trues) // 2]
    falses = sorted(i for i, v in verdicts.items() if v is False)
    left = max([i for i in falses if i < seed], default=None)
    right = min([i for i in falses if i > seed], default=None)

    if left is None:
        first, before, gap_l = min(trues), None, None
        notes.append(f"already {sig} at the oldest usable capture: the real start is earlier than the archive can show")
    else:
        first, before, gap_l = edge(probe, left, seed)
    if right is None:
        last, after, gap_r = max(trues), None, None
        notes.append(f"still {sig} at the newest usable capture: this is not an end date")
    else:
        last, after, gap_r = edge(probe, right, seed)
    for gap, where in ((gap_l, "before the start"), (gap_r, "after the end")):
        if gap is not None:
            notes.append(f"capture {iso(snaps[gap]['timestamp'])} ({where}) could not be read, so the interval is at "
                         f"least as wide as reported")
    outside = [i for i in trues if not first <= i <= last]
    if outside:
        notes.append(f"the signal is not one clean window: {len(outside)} probe(s) also hit outside it "
                     f"({', '.join(iso(snaps[i]['timestamp']) for i in outside[:6])}) — re-run with --scan")
    if not a.scan:
        notes.append(f"located with a {g}-point grid: a window shorter than the capture spacing in one segment "
                     f"could still be missed (--scan reads every capture)")

    def point(i):
        if i is None:
            return None
        s = states.get(i, {})
        return {"date": iso(snaps[i]["timestamp"]), "snapshot": link(snaps[i]["timestamp"], url),
                "state": s.get("state"), "price_basis": s.get("price_basis"),
                "prices": s.get("evidence", {}).get("prices"), "evidence": s.get("evidence", {}).get("context")
                or s.get("evidence", {}).get("match") or s.get("evidence", {}).get("record_name")}

    live = None
    if a.live:
        st, body, err = http(url, timeout=60, tries=1)
        live = {"url": url, "http": st or f"error {err}"}
        if st == 200:
            lv = read_body(body, a.model_id, a.shape, a.price, a.price_regex)
            live.update({"state": lv["state"], "price_basis": lv.get("price_basis"), "prices": lv.get("evidence", {}).get("prices")})
        else:
            live.update({"state": "unreadable", "note": "the live page did not answer 200"})
        print(f"  {'+' if live.get('state') == 'free' else '-'} live page: HTTP {live['http']} · {live.get('state')}")

    res = {"url": url, "model_id": a.model_id, "predicate": a.predicate, "price_mode": a.price,
           "read_as": states.get(first, {}).get("shape"), "requested": {"from": a.frm or None, "to": a.to or None},
           "archive": {"captures": n, "first_capture": iso(snaps[0]["timestamp"]), "last_capture": iso(snaps[-1]["timestamp"]),
                       "probes": len(states), "downloads": fetched[0], "cache": str(CACHE)},
           "first_seen": point(first), "last_seen": point(last), "first_absent_after": point(after),
           "not_there_at": point(before),
           "interval_start": [point(before), point(first)], "interval_end": [point(last), point(after)],
           "start_clipped": left is None, "end_clipped": right is None,
           "unreadable_captures": [iso(t) for t in unreadable], "live": live, "notes": notes}
    out = CACHE / "results" / f"{slug(url, a.model_id)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))

    print(f"\n  first seen {sig}  {point(first)['date']}   {point(first)['snapshot']}")
    if point(before):
        print(f"   not there at  {point(before)['date']}   {point(before)['snapshot']}")
        print(f"   → started between {point(before)['date']} and {point(first)['date']}")
    else:
        print(f"   → start unknown: {sig} already at the oldest usable capture ({point(first)['date']})")
    print(f"   last seen {sig}  {point(last)['date']}   {point(last)['snapshot']}")
    if point(after):
        print(f"   gone by  {point(after)['date']}   {point(after)['snapshot']}")
        print(f"   → ended between {point(last)['date']} and {point(after)['date']}")
    else:
        print("   → no end in the archive: " + sig + " at its newest capture"
              + ("" if live else " (add --live to check the live page)"))
    if live:
        print(f"   live page now: HTTP {live['http']} · {live.get('state')}")
    for nt in notes:
        print(f"   ⚠️ {nt}")
    print(f"   record: {out}")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Usage as e:
        print(f"✗ {e}")
        sys.exit(2)
    except Fail as e:
        print(f"✗ {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
