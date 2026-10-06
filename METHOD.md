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
2. **Fit each benchmark against reference models.** For each benchmark we take reference models that have both a score on the same benchmark and an official AA index. We need at least 4 of them, and we fit a straight line. A benchmark is used only if the fit's correlation is at least 0.6.
3. **Convert each benchmark to an implied AA value.** The model's score goes through that benchmark's line.
4. **Combine.** The implied values are combined with a weighted median: official and leaderboard sources weigh 1, third-party 0.75, community and leaks 0.5.
5. **Make the band.** The band is 5 points wide around that median.
6. **Minimum evidence.** At least 1 benchmark fitted this way is required (until then the site shows `EST —`). An EST built on a single benchmark is labelled "1 benchmark" in its evidence panel; treat it as a rough guide.

Partial question sets (for example 60 of the GPQA questions) are listed, but not used.

**How EST is ranked:**
- EST models sort alongside official AA scores by the middle of their band.
- They never get a single rank number, only a range such as "about #10–15".
- A model with an official score can also get a range (for example #3–4) when an EST band overlaps its score, because we can't tell which of the two is higher. Ranks count only the models scored on this site.
- The home page shows the top 10 scored models first; "Show all" reveals the rest, including the models with no AA score and too little evidence for an estimate.
- When Artificial Analysis publishes an official score, the EST is replaced, and we record whether the official score fell inside the band.

Tap the ⓘ on any EST badge to see every benchmark used, its source, and why any excluded score was left out.

All data and the method's parameters are in this repository: [`data/benchmarks.json`](data/benchmarks.json), [`data/anchors.json`](data/anchors.json), and `est_rules` in [`schema/schema.json`](schema/schema.json).
