# How freetokens works

## What a row means

A **lane** is one model × one channel × one free condition. Each lane records when the free offer started, when it is announced or expected to end, how we last checked it, and the events behind those dates. Every fact links to its source.

For SiliconFlow, the rendered pricing table is authoritative; the model plaza's `price` field is only a lead.

**Statuses:**
- **live:** it answered our last call.
- **past end:** still live after its announced end date.
- **listed:** the provider lists it as free, but we have not called it.
- **not answering:** listed, but not usable at our last check.
- **ended:** no longer free, with the event that shows it.

**End-date confidence:**
- **official:** the provider published the date.
- **inferred:** derived from an announced duration ("two weeks from Sep 26"), with the reasoning in the note.

## "Tested by us"

These are limits we measured ourselves, such as how many coding-agent runs worked in parallel. Every measurement comes from our own account, was run once, and is light, with its date. It is never a load test and never a guarantee. Please don't stress-test shared free tiers.

## FTAA and EST (estimated FTAA)

**FTAA** is the one intelligence score used across the site. It is fixed on the scale of the [Artificial Analysis](https://artificialanalysis.ai) Intelligence Index v5. A model that has a v5 score there shows it as is (`FTAA 33`) and links to its page. A model that only has a score from an older index version shows a converted value (`FTAA ≈33`; the tooltip gives the original score). Models with no Artificial Analysis score get an EST band.

**Conversion.** Older scores go through a quadratic curve fitted on the 36 models that have both an older score and a v5 score: FTAA = 10.6538 − 0.5766·x + 0.02499·x², for old scores x from 12.9 to 57.6 (below that the curve runs straight to zero; above it the score carries over one-for-one). Leaving each of the 36 models out of the fit in turn and converting it, the result misses its real v5 score by 3.09 points on average (a straight line misses by 4.56), and 61% land within 3 points. A converted value is an approximation of about that size. When Artificial Analysis moves to a newer version, FTAA is not rescaled: one more conversion line is added. The curve and its error are stored in `schema/schema.json` (`ftaa`) and refitted by `tools/ftaa.py`.

FTAA is based on data from Artificial Analysis. It is created by freetokens and does not represent the views or endorsement of Artificial Analysis.

New and stealth models usually have no FTAA. For those we show an **EST** band, always 5 points wide (for example `EST 43–48`), computed from public benchmark scores.

How an EST band is computed:
1. **Collect public scores.** We record public scores for the model with their sources. Official, leaderboard, third-party and community or leaked results all count, but only if they are for this exact model, never a rumoured identity or a predecessor.
2. **Fit each benchmark against reference models.** For each benchmark we take reference models that have both a score on the same benchmark and an FTAA score (direct or converted). We need at least 4 of them, and we fit a straight line. A benchmark is used only if the fit's correlation is at least 0.6. Benchmarks fitted today (Oct 6): AI Coding Daily (17 reference models, r = 0.85), SWE-bench Verified (110, r = 0.82), SWE-bench Pro (62, r = 0.87) and Terminal-Bench 2.1 (77, r = 0.87). When a reference model has several published scores on one benchmark we use their median.
3. **Convert each benchmark to an implied FTAA value.** The model's score goes through that benchmark's line.
4. **Combine.** The implied values are combined with a weighted median: official and leaderboard sources weigh 1, third-party 0.75, community and leaks 0.5.
5. **Make the band.** The band is 5 points wide around that median.
6. **Minimum evidence.** At least 1 benchmark fitted this way is required (until then the site shows `EST —`). An EST built on a single benchmark is labelled "1 benchmark" in its evidence panel; treat it as a rough guide.

Partial question sets (for example 60 of the GPQA questions) are listed, but not used.

**How EST is ranked:**
- EST models sort alongside FTAA scores by the middle of their band.
- They never get a single rank number, only a range such as "about #10–15".
- Models with an FTAA score rank #1, #2, #3… among themselves. An EST model is placed between them: "≈#2–3" means it would sit between #2 and #3.
- The home page shows the top 10 scored models first; "Show all" reveals the rest, including the models with no FTAA and too little evidence for an estimate.
- When Artificial Analysis publishes a v5 score, the EST is replaced, and we record whether that score fell inside the band.

Tap the ⓘ on any EST badge to see every benchmark used, its source, and why any excluded score was left out.

All data and the method's parameters are in this repository: [`data/benchmarks.json`](data/benchmarks.json), [`data/anchors.json`](data/anchors.json), and `est_rules` in [`schema/schema.json`](schema/schema.json).

<!-- BEGIN:est-scorecard -->
**Scorecard** (generated by `build.py` from the backtest and the forward exam; do not edit by hand).

Leave-one-out backtest of the method above, on 136 reference models (method version 2, 5-point band): mean absolute difference **5.27** points, 5-point hit rate **34%**.

Method version 2 is the change of scale to FTAA (ADR-035): most reference scores are converted from the earlier index version, and version 1 numbers were on the earlier AA scale, so the two are not comparable.

By evidence depth: 1 benchmark 8.61 · 2 benchmarks 4.92 · 3 benchmarks 5.28 · 4 benchmarks 4.27 · 5 benchmarks 4.54 · 6 benchmarks 0.87 — more benchmarks, closer estimates.

Forward exam: **0** estimates have so far been replaced by a published v5 score and settled against their band. The 34% above is the backtest, not the future; the forward number is what will judge the method, and it fills itself in as Artificial Analysis publishes scores.
<!-- END:est-scorecard -->

## Cost to start a channel

"Free" can still need something first. Each channel has one record in [`data/channels.json`](data/channels.json) with the cheapest way in and its source:

- **$0 · no account**: usable without paying or signing up.
- **$0 · account**: free after signing up, no card.
- **$0 · invite only**: free, but sign-up needs an invitation or an established account elsewhere.
- **plan first** (for example $10/mo): a paid subscription must be active before the free models work.
- **top-up first** (for example $20): a minimum credit purchase is needed.

Lanes on a channel that needs money first carry a small **$** wherever they appear, and the "no payment needed" filter hides them.

## How the free models can be used

Each channel also records how its free models can be reached, in [`data/channels.json`](data/channels.json) (`access`), with a source:

- **API · format**: an API key works from your own tools. The badge names the format (OpenAI chat, OpenAI Responses, Anthropic Messages, Gemini) or says how many it accepts.
- **CLI only**: the free models answer only inside the vendor's own CLI or app (for example OpenCode Zen's free models return 403 outside OpenCode).
- **App only**: only inside the vendor's desktop or web app.
- **human only**: the terms forbid scripts, bots or autonomous agents.

Rules that nearly every provider shares (no reselling access, one account per person, no bulk accounts) apply everywhere and are not repeated per channel. A lane can override its channel when its free route differs.

## Use-case views

The switch in the top bar (All · Humans · Agents) shows the whole site for one kind of use. It never changes a score; it only decides which lanes count.

- **All**: every free lane (live, listed, or past its announced end but still answering).
- **Humans**: free lanes that need no payment first. Lanes that only work inside the vendor's own app or CLI, or whose terms forbid automation, still count: a person can use them by hand.
- **Agents**: free lanes that a script or coding agent may use: an API key works, or the vendor's CLI may be run unattended. Lanes whose terms forbid automation ("human only") or that only work in a desktop or web app are left out. Lanes that need a paid plan first are kept and marked with **$**.

Within a view, models are ranked among the models usable in that view (FTAA scores first, estimates placed between them). Models free only through lanes that don't fit the view are listed at the bottom as "Not usable this way". Free lanes limited to one region stay in every view with a region tag. The view is remembered on your device and can be shared with `?use=humans` or `?use=agents`.

## Fallback ladder

In the Agents view, the home page shows which free route to use first and what to step down to when it runs out.

- **Volume tier.** Each lane can carry a rough tier: *a few dozen a day* (about 100 requests or fewer), *hundreds a day* (or only a few at once), or *10+ at once, all day* (ten or more parallel agent runs worked in our tests). The tier comes from the route's published limits or from our own concurrency runs, and the lane records which. We never run a quota dry to measure it: exact numbers change by account, by IP and by day, so a coarse tier stays true longer.
- **The ladder.** Start from the most generous tier and take its highest score. Moving to a less generous tier, a route earns a rung only if it scores more than 2 points above every rung below it, because a smaller allowance is only worth it for a clearly smarter model. Routes within 2 points of a rung's leader in the same tier are listed as stand-ins (EST bands are wider than 2 points).
- **What counts.** Only routes usable by agents (an API key or a CLI whose terms allow automation) with a score. By default only routes that worked in our tests; *Include unconfirmed* also counts routes that are listed free but have not worked for us yet.

## Daily free tokens

The home page (below "Free periods") plots estimated free tokens per day, by channel, from 2026-10-04 to today.

- **Unit.** Estimated tokens/day in millions (M). Each lane's amount comes from its volume tier (taste = 0.3M, daily = 3M, bulk = 30M) unless the provider publishes a TPD/RPD, in which case that official number is converted (1 request = 8k tokens) and the lane is marked as measured. Lanes without a volume tier are excluded; their count is shown beneath the chart.
- **Pools.** Lanes that share a quota (channel `limit_scope` or a shared free condition such as Zen per IP, Cloudflare 10k Neurons/day, ModelScope daily shared) are counted once per day, taking the largest tier among the pool's qualifying models. Other lanes count individually.
- **Thresholds.** Buttons split by FTAA: All / 20+ / 25+ / 30+ / 35+ / 50+, default 30+. A lane counts only when its model's score (FTAA, or EST centre where there is none) meets the threshold.
- **Presets.** Common (no payment, no mainland real-name, API or official CLI) / All / + min pay (adds paid-plan channels). `own_cli` channels whose rules include `no_automation` appear only under All.
- **Stacking.** Channels are stacked; the six with the largest totals over the range get their own colour, the rest merge into "Other N" grey. Hatched fills are tier estimates; solid fills are official numbers.
- **Top free FTAA.** The red line is the highest free FTAA in the selected preset (threshold-independent, preset-dependent).
- **Events.** Up to four days with the largest absolute change in total are marked, labelled like "Zen −3 lanes" or "Model +".
- **Stats card.** Now / 30-day high / 30-day low / top free FTAA.
- **Details.** A collapsible channel × day heat map; cell colour is the strongest free model's FTAA band for that channel on that day.
- **Models view.** A separate toggle plots the count of distinct free models reaching the threshold, as a single step line, from the earliest data date; the card shows now / peak / low.
- **No description on the page.** Each word on the page is data or a data label; this note is the explanation (ADR-016).

## Makers

Every model points at one maker in `data/makers.json` (name, parent company, country, official links). Different spellings of one company are merged there (for example THUDM under Z.ai). Stealth models belong to "Undisclosed"; when the community has linked one to a maker, the model carries a `suspected_maker` with its source and is shown as "possibly X · unconfirmed" on the model page and in a separate "Possibly theirs" list on that maker's page. It never counts as the maker's own model.

## Vendor numbers and comparison tables (ADR-023)

Vendors report their own models' benchmark scores in their own harness, and small models tend to score far higher on coding benchmarks than their overall intelligence would suggest. Mapping those raw numbers through a fit learned from independent leaderboards overestimates them (Xing 4.0 29B came out at 27; its vendor table shows it level with Qwen3.6 35B A3B, 18; both numbers are on the earlier AA scale). So a vendor score that comes from a comparison table is read against the other models in that same table: for each comparison model with a known FTAA score and a benchmark score within 10 points, the implied FTAA is that model's FTAA plus the fit slope times the score difference, weighted toward the closest models. The estimate is the weighted mean of the benchmarks. Vendor-reported scores with no usable comparison models get a band twice as wide and are marked low confidence.

## Privacy and re-checks

The site sets no cookies and records no sessions. It counts page views and which outbound links are clicked with PostHog (EU-hosted, memory only, anonymised IPs, Do Not Track respected), sends one empty request to its own server when a page is shown (to tell people from scrapers; it carries no identifier), and reads the standard web server log (page, time, referrer, user agent) to count visits and AI crawlers. Nothing identifies you across visits; how it works is in OBSERVE.md. A live lane that hasn't been re-checked for 7 days is marked "re-check due" and is no longer counted as confirmed until it is checked again.

## Free programs (offers)

A lane is a model that costs $0 on a channel, with caps that only stop abuse. A free program gives you something you can spend across many models: credits, a daily allowance (Neurons, Freebucks, a shared call quota), a student plan or a perk that comes with a plan you already pay for. Programs live on their own page (/offers) and are never ranked with the models; a model page lists them under "Also free through". Amounts are kept in each provider's own unit and never converted. The list is sorted by how easy a program is to get (fewest requirements first), then by how often it refills. Only official, lawful routes are listed. A program not re-checked for 14 days is due for a re-check.

## Pooled lanes (meter: pooled)

A lane is "pooled" when several models share one credit or allowance pool instead of each having its own limit. The `meter` field says which: `per_model` for a model with its own rate limit or allowance, `pooled` for models that draw on a shared pool (ADR-033). A pooled lane always carries a `pool` object: `pool.offer` names the offer that owns the pool (its requirements, registration and allowance text live there), and `pool.cap` states the pool's own allowance (`amount`, `unit`, `per`) — read that as the shared cap for the whole pool, not a per-model limit. The lane's own `limits_stated` / `limits_observed` describe reachability and quirks, not the pool size. So `per_model` lanes never carry `pool`, and a `pooled` lane without `pool.offer` + `pool.cap` is invalid.
