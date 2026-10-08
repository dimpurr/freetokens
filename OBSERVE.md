# OBSERVE.md — how freetokens watches itself

Read this before you add a tracker, change the health checks or rely on the weekly numbers. It covers traffic, search visibility, reliability and data freshness. The data model lives in METHOD.md; ADR-024 (private) records why things are set up this way.

## §1 What we watch, and where it comes from

```
visitors ──► nginx on kafu ──► freetokens.access.log (own log since 2026-10-08; before that, lines picked from the shared access.log)
                                   │
                                   ▼
                    tools/observe.py logs / report --weekly ──► Telegram (Hermes, Mondays)
data/*.json ──────► tools/observe.py health ──► Telegram only when something is wrong (Hermes, daily)
public catalogues ► tools/watch.py ──► Telegram on changes (Hermes, daily 09:00)
search engines ───► Google Search Console (domain property) · Bing Webmaster (BingSiteAuth.xml) · IndexNow key file
```

No cookies, no client-side trackers, no session replay. Counts come from the standard server log that every web server keeps.

## §2 Tool registry

| Tool | What it answers | How to run |
|---|---|---|
| `tools/observe.py logs FILE...` | per-day views, visitors, browsers, top pages, referrers, AI crawlers, search bots, feed and llms.txt hits | JSON |
| `tools/observe.py health [--watch PATH]` | key pages answer 200, deployed build date, live lanes due for a re-check, catalogue watch freshness | JSON |
| `tools/observe.py links` | channel links and limit sources that are broken (403/429 count as bot-blocked, not broken) | JSON |
| `tools/observe.py report --daily / --weekly` | Telegram text; daily prints nothing when all is well | text |
| `tools/watch.py` | free-catalogue diff (new, gone, back) and promo page changes | see its docstring |
| `tools/query.py` | stable JSON for other tools: scores, lanes (incl. `stale`), events, agent pool | see its docstring |
| Google Search Console | indexed pages, queries, impressions, clicks | web UI for now (API access pending, see §6) |
| Bing Webmaster Tools | the same for Bing | web UI for now |

The runner scripts that hold host names and own IPs are private: `.private/observe-fetch.sh` (fetches 8 days of logs from kafu) and the Hermes wrapper `~/.hermes/scripts/freetokens-observe.sh`.

## §3 Definitions

- **Browsers**: distinct IPs that loaded `/assets/data.js`, i.e. a real browser ran the page. This is the best "real visitor" number.
- **Visitors**: distinct IPs with a page view. This includes link previews and scanners that don't announce themselves, so treat it as an upper bound.
- **Page views**: 2xx responses for pages (not assets).
- **Excluded**: bots by user agent (see `BOT`, `LLM_BOTS`, `SEARCH_BOTS` in observe.py) and the IPs in `FT_OBSERVE_IGNORE_IPS` (our own machines). A maintainer's phone on mobile data is not excluded.
- **Pages AI assistants read for someone**: hits from ChatGPT-User, Perplexity-User, Claude-User on our own paths. The assistant sends only the URL, never the person's question; the page tells you the topic. Scanners fake these user agents, so hits on paths we don't serve are dropped.
- **Visitors who came from an AI answer**: landings with `utm_source=chatgpt.com` (or perplexity, claude.ai, copilot, gemini): a person clicked a citation. We see the landing page, not the question.
- **AI crawlers**: OAI-SearchBot and ChatGPT-User (ChatGPT fetching a page for a user, i.e. a real person asked about it), ClaudeBot, PerplexityBot, GPTBot, Bytespider and others. ChatGPT-User and Perplexity-User are the closest thing to "an AI assistant cited us".

## §4 Data freshness rules

- A **live** or **overdue** lane not re-checked for **7 days** is "re-check due". The site shows it next to the check date, the Agents fallback ladder stops counting it as confirmed, and `query.py lanes` returns `stale: true`. The daily health report lists these on Thursdays.
- A negative finding needs repeated checks (ADR-022). The 7-day rule only says "look again"; it never marks a lane as ended.
- A free program (offers.json) not re-checked for **14 days** is listed in the weekly report.
- The catalogue watch must have run in the last 30 hours, otherwise the daily report says so.

## §5 Query recipes

```bash
# last 8 days of logs, then this week's numbers
.private/observe-fetch.sh ~/scratch/DimResearchS/freetokens-observe
FT_OBSERVE_IGNORE_IPS=… python3 tools/observe.py logs ~/scratch/DimResearchS/freetokens-observe/{shared,freetokens}.log

# which lanes need a re-check
python3 tools/observe.py health | python3 -c "import json,sys; print(json.load(sys.stdin)['stale_lanes'])"

# everything the weekly Telegram report would say, right now
python3 tools/observe.py report --weekly --watch ~/scratch/DimResearchS/freetokens-watch/latest.json --logs <logs>
```

## §6 Known blind spots and pending work

- **No in-page events.** We can't tell which features people use (view switch, filters, ladder) or which channel links they click. Plan: PostHog EU, cookieless, in the DimWorks organisation. Pending Dim (the project has to be created in the browser).
- **Search data needs the web UI.** Plan: a read-only service account for the Search Console API, and a Bing Webmaster API key. Pending Dim.
- Logs older than 14 days are rotated away; the weekly report only looks at 7 days.
- Visitors behind one NAT count as one IP; one person on several networks counts several times.

## §7 Maintenance checklist (quarterly)

- [ ] Compare `LLM_BOTS` / `SEARCH_BOTS` with the user agents in the logs; add new crawlers.
- [ ] Check that `freetokens.access.log` is still written and rotated (`/etc/logrotate.d/nginx` covers `*.log`).
- [ ] Run `observe.py links` by hand and read the bot-blocked list: a site that blocks us might also be gone.
- [ ] Re-read §6: drop items that shipped, add new blind spots.
