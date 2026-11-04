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

## FT Intelligence (FTI)

**FTI** is the one intelligence score used across the site. freetokens computes it from public benchmark scores, on a scale that was fixed once on Nov 1, 2026 and does not move when any single source changes its own scale. Every model goes through the same method.

How it is shown:
- `FTI 33`: three or more sources, at least one of them independent of the model's vendor (Artificial Analysis does not count as that one), no two of them more than 8 points apart, and no source's value cut off at the bottom or top of the scale.
- `FTI 31–36`: fewer sources, or only the vendor's own numbers. A band 5 points wide around the computed centre. The same band is shown when three or more sources disagree by more than 8 points: then Artificial Analysis is added as one more source and the score is recomputed, and if they still disagree it stays a band.
- `—`: no usable source yet.

How it is computed:
1. **Collect public scores.** For each model we record public benchmark scores with their sources. Leaderboard, third-party, vendor and community results all count, but only for this exact model, never a rumoured identity or a predecessor. Partial question sets are listed, not used.
2. **Fit each benchmark once.** A reference set of models has a frozen reference score on the FTI scale. For each benchmark we take the reference models that also have a score on it and fit a straight line. A benchmark is used only with at least 4 reference models and a correlation of at least 0.6, and not when most reference models share one score (a floor or ceiling effect). Vendor-reported scores get their own line where there are enough of them, because vendors report higher than independent runs. Today: AI Coding Daily (r = 0.89, 17 reference models), Aider Polyglot (r = 0.94, 17 reference models), SWE-bench Verified (r = 0.72, 86 reference models), SWE-bench Pro (r = 0.82, 25 reference models), Terminal-Bench 2.1 (r = 0.76, 45 reference models), LiveCodeBench (r = 0.76, 9 reference models), tau-bench (r = 0.81, 6 reference models), GPQA Diamond (r = 0.61, 68 reference models), Humanity's Last Exam (r = 0.74, 46 reference models) and the Epoch AI Benchmarking Hub (the Epoch Capabilities Index, r = 0.89, 95 reference models, and 12 of its benchmarks). The lines are in [`data/ft_lines.json`](data/ft_lines.json).
3. **Convert each benchmark to an implied FTI.** The model's score goes through that benchmark's line. A score far outside the range the reference models cover is read at the edge of that range.
4. **Combine.** The implied values are combined with a weighted median. Leaderboard sources weigh 1, third-party and Artificial Analysis 0.75, community and leaks 0.5, vendor claims 0.4. A vendor table that also lists models with known reference scores is read against those models (the implied value is their score plus the line's slope times the score gap, weight 0.6), so the vendor's own harness cancels out.
5. **Count sources.** All Epoch AI benchmarks count as one source. Several claims on one benchmark count once.
6. **Artificial Analysis is one source among the others.** It is used when fewer than 3 other sources exist, or when 3 or more disagree by more than 8 points, with the weight of a third party, and is listed by name and link only.
7. **Snapshots.** A model whose weights were replaced under the same name keeps one entry, with its `snapshots` (id, date, source; the last one is current). Each claim carries the snapshot it measured, and only the current snapshot's evidence is scored. A claim without a snapshot is attributed by its date; when neither is known it counts as current. If the current snapshot has no evidence yet, older evidence is used and shown as a band. The trend chart applies each snapshot's own score from its date, so an upgrade does not rewrite earlier days. A model gets a separate entry only when users can pick the old and the new version by ID on the same channel for a long time. Which snapshot a third-party channel serves is mostly unknown; a lane records `serves` only when it was checked and found to be older.
8. **Reasoning mode.** A claim's mode (thinking or effort level) is written into its variant. The vendor's default configuration is assumed when none is stated, and different modes of one benchmark are never mixed.

Sources: AI Coding Daily, SWE-bench, Scale SEAL, Terminal-Bench, Vals AI, llm-stats, Aider, LiveCodeBench, BFCL, tau-bench, vendor model cards and technical reports, [Artificial Analysis](https://artificialanalysis.ai), and [Epoch AI](https://epoch.ai/benchmarks) (Epoch AI, "Capabilities & benchmarking", epoch.ai/benchmarks, CC BY 4.0; only its main benchmark data and the Epoch Capabilities Index are used).

**Ranking.** Scores are published as whole numbers. Models sort by the centre of their score. A model shown as an integer gets a single rank (`#7`); a model shown as a band gets a range (`#10–15`), counted against the centres of all other scored models. The home page shows the top 10 scored models first; "Show all" reveals the rest, including the models with no usable source.

Tap the ⓘ next to any FTI to see every source with its value and link, and why any listed score was not used.

All data and the method's parameters are in this repository: [`data/benchmarks.json`](data/benchmarks.json), [`data/ft_lines.json`](data/ft_lines.json), [`data/ft_scores.json`](data/ft_scores.json), and `ft_rules` in [`schema/schema.json`](schema/schema.json).

<!-- BEGIN:ft-scorecard -->
**Scorecard** (generated by `build.py` from `data/ft_scorecard.json`; do not edit by hand).

Leave-one-out backtest on 166 reference models: hide one model's reference score, refit the benchmark lines on the others, then score that model from its own published benchmark scores only (Artificial Analysis is not a source in this test). On 138 models the mean absolute difference is **4.04** points, the 5-point hit rate **36%**, and 41% land within 3 points. By number of sources: 1 5.05 · 2 4.02 · 3 3.47 · 4+ 3.90 (more sources, smaller error).

Using only vendor self-reports and comparison tables, on 80 models: mean absolute difference **3.89** points, bias +0.19 (vendor numbers run high).
<!-- END:ft-scorecard -->

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

Within a view, models are ranked among the models usable in that view (ranked by FTI, a band model gets a range). Models free only through lanes that don't fit the view are listed at the bottom as "Not usable this way". Free lanes limited to one region stay in every view with a region tag. The view is remembered on your device and can be shared with `?use=humans` or `?use=agents`.

## Fallback ladder

In the Agents view, the home page shows which free route to use first and what to step down to when it runs out.

- **Volume tier.** Each lane can carry a rough tier: *a few dozen a day* (about 100 requests or fewer), *hundreds a day* (or only a few at once), or *10+ at once, all day* (ten or more parallel agent runs worked in our tests). The tier comes from the route's published limits or from our own concurrency runs, and the lane records which. We never run a quota dry to measure it: exact numbers change by account, by IP and by day, so a coarse tier stays true longer.
- **The ladder.** Start from the most generous tier and take its highest score. Moving to a less generous tier, a route earns a rung only if it scores more than 2 points above every rung below it, because a smaller allowance is only worth it for a clearly smarter model. Routes within 2 points of a rung's leader in the same tier are listed as stand-ins (bands are wider than 2 points).
- **What counts.** Only routes usable by agents (an API key or a CLI whose terms allow automation) with a score. By default only routes that worked in our tests; *Include unconfirmed* also counts routes that are listed free but have not worked for us yet.

## Daily free tokens

The home page (below "Free periods") plots estimated free tokens per day, by channel, from 2026-10-04 to today.

- **Unit.** Estimated tokens/day in millions (M). Each lane's amount comes from its volume tier (taste = 0.3M, daily = 3M, bulk = 30M) unless the provider publishes a TPD/RPD, in which case that official number is converted (1 request = 8k tokens) and the lane is marked as measured. Lanes without a volume tier are excluded; their count is shown beneath the chart.
- **Pools.** Lanes that share a quota (channel `limit_scope` or a shared free condition such as Zen per IP, Cloudflare 10k Neurons/day, ModelScope daily shared) are counted once per day, taking the largest tier among the pool's qualifying models. Other lanes count individually.
- **Thresholds.** Buttons split by FTI: All / 20+ / 25+ / 30+ / 35+ / 50+, default 30+. A lane counts only when its model's FTI (the centre, for a band) meets the threshold.
- **Presets.** Common (no payment, no mainland real-name, API or official CLI) / All / + min pay (adds paid-plan channels). `own_cli` channels whose rules include `no_automation` appear only under All.
- **Stacking.** Channels are stacked; the six with the largest totals over the range get their own colour, the rest merge into "Other N" grey. Hatched fills are tier estimates; solid fills are official numbers.
- **Top free FTI.** The red line is the highest free FTI in the selected preset (threshold-independent, preset-dependent).
- **Events.** Up to four days with the largest absolute change in total are marked, labelled like "Zen −3 lanes" or "Model +".
- **Stats card.** Now / 30-day high / 30-day low / top free FTI.
- **Details.** A collapsible channel × day heat map; cell colour is the strongest free model's FTI band for that channel on that day.
- **Models view.** A separate toggle plots the count of distinct free models reaching the threshold, as a single step line, from the earliest data date; the card shows now / peak / low.
- **No description on the page.** Each word on the page is data or a data label; this note is the explanation (ADR-016).

## Makers

Every model points at one maker in `data/makers.json` (name, parent company, country, official links). Different spellings of one company are merged there (for example THUDM under Z.ai). Stealth models belong to "Undisclosed"; when the community has linked one to a maker, the model carries a `suspected_maker` with its source and is shown as "possibly X · unconfirmed" on the model page and in a separate "Possibly theirs" list on that maker's page. It never counts as the maker's own model.

## Vendor numbers and comparison tables (ADR-023)

Vendors report their own models' benchmark scores in their own harness, and small models tend to score far higher on coding benchmarks than their overall intelligence would suggest. Mapping those raw numbers through a line learned from independent leaderboards overestimates them. So a vendor score that comes from a comparison table is read against the other models in that same table: for each comparison model with a known reference score and a benchmark score within 10 points, the implied FTI is that model's reference score plus the line's slope times the score difference, weighted toward the closest models. Vendor-reported scores with no usable comparison models are read through the vendor line where one exists and weigh least; when they are the only source the score is a band, marked low confidence.

## Privacy and re-checks

The site sets no cookies and records no sessions. It counts page views and which outbound links are clicked with PostHog (EU-hosted, memory only, anonymised IPs, Do Not Track respected), sends one empty request to its own server when a page is shown (to tell people from scrapers; it carries no identifier), and reads the standard web server log (page, time, referrer, user agent) to count visits and AI crawlers. Nothing identifies you across visits; how it works is in OBSERVE.md. A live lane that hasn't been re-checked for 7 days is marked "re-check due" and is no longer counted as confirmed until it is checked again.

## Free programs (offers)

A lane is a model that costs $0 on a channel, with caps that only stop abuse. A free program gives you something you can spend across many models: credits, a daily allowance (Neurons, Freebucks, a shared call quota), a student plan or a perk that comes with a plan you already pay for. Programs live on their own page (/offers) and are never ranked with the models; a model page lists them under "Also free through". Amounts are kept in each provider's own unit and never converted. The list is sorted by how easy a program is to get (fewest requirements first), then by how often it refills. Only official, lawful routes are listed. A program not re-checked for 14 days is due for a re-check.

## Pooled lanes (meter: pooled)

A lane is "pooled" when several models share one credit or allowance pool instead of each having its own limit. The `meter` field says which: `per_model` for a model with its own rate limit or allowance, `pooled` for models that draw on a shared pool (ADR-033). A pooled lane always carries a `pool` object: `pool.offer` names the offer that owns the pool (its requirements, registration and allowance text live there), and `pool.cap` states the pool's own allowance (`amount`, `unit`, `per`) — read that as the shared cap for the whole pool, not a per-model limit. The lane's own `limits_stated` / `limits_observed` describe reachability and quirks, not the pool size. So `per_model` lanes never carry `pool`, and a `pooled` lane without `pool.offer` + `pool.cap` is invalid.

## Community take

For a brand-new or still-anonymous model the FTI is `—` for the first days, yet there is already a lot of public discussion. The "Community take" block on a model page turns that discussion into countable facts, coded to the rules in `tools/community/CODEBOOK.md`: the level people place it at, the models it is compared to and in which direction, the rumoured maker (always shown as a rumour), a parameter-size guess, strengths and weaknesses, known issues, the hard numbers authors report, the overall tone and the mix of platforms. Every cell is a count of posts, and the block carries a few self-rendered quote cards (platform, author, date, a verbatim quote of ≤25 words, a link; a source that later disappeared is kept and marked deleted). No third-party embed from X, Reddit or any other platform is loaded.

How the block is drawn: a count is read as a row of small bars, one bar per post, not as a number in a sentence. A cell with nothing to say is not drawn at all — an empty field, an "other" bucket or a "not discussed" placeholder leaves no cell behind, and a term named under both weaknesses and issues is said once. Each cell is at most two lines of reading at any width; whatever does not fit folds behind a single "+N more" control, and the same folding keeps the maker guesses and the reported numbers short. A reported number says every word once: when its unit or its metric only restates the value (a value of "mismatch" under a metric "tokenizer match", a value of "6 toy tasks" carrying the unit "tasks"), the repeated word is printed a single time; the author's fuller wording stays in that row's tooltip. Quote cards sit up to three in a row, equal height, and a short last row fills its own line instead of leaving an empty slot beside it.

It is deliberately not part of FTI: nothing here feeds the score (the footer says "Not part of FTI"). A model with fewer than three independent authors shows only "Too little discussion yet". Peer estimates (an FTI guessed from the models a new one gets compared to) are computed only as private back-test data and are never published or shown. If a post or quote is wrong or should come down, open a GitHub issue.
