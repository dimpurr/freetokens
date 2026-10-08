# How freetokens works

## What a row means

A **lane** is one model × one channel × one free condition. Each lane records when the free offer started, when it is announced or expected to end, how we last checked it, and the events behind those dates. Every fact links to its source.

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

## AA index and EST (estimated AA index)

The **AA index** is the [Artificial Analysis](https://artificialanalysis.ai) Intelligence Index. It is shown only when Artificial Analysis publishes it, and it links to the model's page there.

New and stealth models usually have no AA index. For those we show an **EST** band, always 5 points wide (for example `EST 43–48`), computed from public benchmark scores.

How an EST band is computed:
1. **Collect public scores.** We record public scores for the model with their sources. Official, leaderboard, third-party and community or leaked results all count, but only if they are for this exact model, never a rumoured identity or a predecessor.
2. **Fit each benchmark against reference models.** For each benchmark we take reference models that have both a score on the same benchmark and an official AA index. We need at least 4 of them, and we fit a straight line. A benchmark is used only if the fit's correlation is at least 0.6. Benchmarks fitted today (Oct 6): AI Coding Daily (17 reference models, r = 0.85), SWE-bench Verified (110, r = 0.82), SWE-bench Pro (62, r = 0.87) and Terminal-Bench 2.1 (77, r = 0.87). When a reference model has several published scores on one benchmark we use their median.
3. **Convert each benchmark to an implied AA value.** The model's score goes through that benchmark's line.
4. **Combine.** The implied values are combined with a weighted median: official and leaderboard sources weigh 1, third-party 0.75, community and leaks 0.5.
5. **Make the band.** The band is 5 points wide around that median.
6. **Minimum evidence.** At least 1 benchmark fitted this way is required (until then the site shows `EST —`). An EST built on a single benchmark is labelled "1 benchmark" in its evidence panel; treat it as a rough guide.

Partial question sets (for example 60 of the GPQA questions) are listed, but not used.

**How EST is ranked:**
- EST models sort alongside official AA scores by the middle of their band.
- They never get a single rank number, only a range such as "about #10–15".
- Models with an official AA score rank #1, #2, #3… among themselves. An EST model is placed between them: "≈#2–3" means it would sit between official #2 and #3.
- The home page shows the top 10 scored models first; "Show all" reveals the rest, including the models with no AA score and too little evidence for an estimate.
- When Artificial Analysis publishes an official score, the EST is replaced, and we record whether the official score fell inside the band.

Tap the ⓘ on any EST badge to see every benchmark used, its source, and why any excluded score was left out.

All data and the method's parameters are in this repository: [`data/benchmarks.json`](data/benchmarks.json), [`data/anchors.json`](data/anchors.json), and `est_rules` in [`schema/schema.json`](schema/schema.json).

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

Within a view, models are ranked among the models usable in that view (official AA scores first, estimates placed between them). Models free only through lanes that don't fit the view are listed at the bottom as "Not usable this way". Free lanes limited to one region stay in every view with a region tag. The view is remembered on your device and can be shared with `?use=humans` or `?use=agents`.

## Fallback ladder

In the Agents view, the home page shows which free route to use first and what to step down to when it runs out.

- **Volume tier.** Each lane can carry a rough tier: *a few dozen a day* (about 100 requests or fewer), *hundreds a day* (or only a few at once), or *10+ at once, all day* (ten or more parallel agent runs worked in our tests). The tier comes from the route's published limits or from our own concurrency runs, and the lane records which. We never run a quota dry to measure it: exact numbers change by account, by IP and by day, so a coarse tier stays true longer.
- **The ladder.** Start from the most generous tier and take its highest score. Moving to a less generous tier, a route earns a rung only if it scores more than 2 points above every rung below it, because a smaller allowance is only worth it for a clearly smarter model. Routes within 2 points of a rung's leader in the same tier are listed as stand-ins (EST bands are wider than 2 points).
- **What counts.** Only routes usable by agents (an API key or a CLI whose terms allow automation) with a score. By default only routes that worked in our tests; *Include unconfirmed* also counts routes that are listed free but have not worked for us yet.

## Makers

Every model points at one maker in `data/makers.json` (name, parent company, country, official links). Different spellings of one company are merged there (for example THUDM under Z.ai). Stealth models belong to "Undisclosed"; when the community has linked one to a maker, the model carries a `suspected_maker` with its source and is shown as "possibly X · unconfirmed" on the model page and in a separate "Possibly theirs" list on that maker's page. It never counts as the maker's own model.

## Vendor numbers and comparison tables (ADR-023)

Vendors report their own models' benchmark scores in their own harness, and small models tend to score far higher on coding benchmarks than their overall intelligence would suggest. Mapping those raw numbers through a fit learned from independent leaderboards overestimates them (Xing 4.0 29B came out at 27; its vendor table shows it level with Qwen3.6 35B A3B, AA 18). So a vendor score that comes from a comparison table is read against the other models in that same table: for each comparison model with a known AA score and a benchmark score within 10 points, the implied AA is that model's AA plus the fit slope times the score difference, weighted toward the closest models. The estimate is the weighted mean of the benchmarks. Vendor-reported scores with no usable comparison models get a band twice as wide and are marked low confidence.

## Privacy and re-checks

The site sets no cookies and runs no trackers or session recording. We read the standard web server log (page, time, referrer, user agent) to count visits and AI crawlers; how it works is in OBSERVE.md. A live lane that hasn't been re-checked for 7 days is marked "re-check due" and is no longer counted as confirmed until it is checked again.

## Free programs (offers)

A lane is a model that costs $0 on a channel, with caps that only stop abuse. A free program gives you something you can spend across many models: credits, a daily allowance (Neurons, Freebucks, a shared call quota), a student plan or a perk that comes with a plan you already pay for. Programs live on their own page (/offers) and are never ranked with the models; a model page lists them under "Also free through". Amounts are kept in each provider's own unit and never converted. The list is sorted by how easy a program is to get (fewest requirements first), then by how often it refills. Only official, lawful routes are listed. A program not re-checked for 14 days is due for a re-check.
