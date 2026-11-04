# Community take · codebook v0.2

How freetokens turns public discussion of a model into countable, sourced cells. Decision record: ADR-038 (private). This is method, not opinion: every cell is a count of posts, and every post links back to its source. Nothing here feeds FT Intelligence.

## Unit of coding

- **Post** = one public item by one author: an X post, a Reddit post or top-level comment, a forum topic or reply, a blog article. Replies by the same author in one thread count once.
- **Independent authors** = distinct handles. Fewer than 3 ⇒ the block shows "Too little discussion yet" and nothing else.
- Skip: reposts with no added content, the vendor's own announcement (goes in lane/offer data instead), freetokens pages, and zero-engagement posts that only guess a name with no reason.

## Source grade (per post)

| Grade | Meaning | Example |
|---|---|---|
| `measured` | Author ran something and reports numbers | tok/s, a private benchmark, needle test |
| `forensic` | Technical evidence about identity or behaviour | tokenizer comparison, geo-block list, API parameters, error text |
| `hands_on` | Used it and describes the experience | "stops mid-task in OpenCode" |
| `opinion` | Impression without stated use | "looks like Spark" |

## The nine cells

| # | Cell | Values | Rule |
|---|---|---|---|
| 1 | `tier` | `frontier` / `mid` / `flash` / `small` → post count each | Only posts that place it, explicitly or by comparison. Show the distribution, never a single verdict. |
| 2 | `compared_to` | model id (ours if we have it, else name) × `better` / `similar` / `worse` → post count | Direction is *this model relative to the other*. |
| 3 | `maker_guess` | maker id → post count, evidence types (`tokenizer`, `geo_block`, `api_shape`, `self_report`, `style`, `other`) | Always rendered as rumoured. Note contrary forensic evidence (e.g. "tokenizer mismatch ×3"). On reveal, the answer moves to `revealed_as` in models.json. |
| 4 | `size_guess` | parameter guess → post count, or `not discussed` | Never leave empty. |
| 5 | `strengths` / `weaknesses` | `coding`, `agentic`, `search_subagent`, `writing`, `vision`, `reasoning`, `long_context`, `speed`, `instruction_following`, `other` → +count / −count | A post can hit several. |
| 6 | `issues` | `hallucination`, `stops_mid_task`, `verbose`, `instruction_following`, `region_block`, `rate_limit`, `other` → post count | |
| 7 | `numbers` | list of {metric, value, unit, url, date, grade} | Listed as reported. Not scored. |
| 8 | `sentiment` | `positive` / `mixed` / `negative` → post count | Overall tone of the post toward the model. |
| 9 | `sources` | platform → post count; `first_seen` {date, url} | |

## Quotes

3–5 per model. Prefer `measured` and `forensic`, then `hands_on`; cover both sides when sentiment is split. Each quote ≤25 words, verbatim, with platform, handle, date and URL. If the source later disappears (404 or removed notice), keep the card and mark it `gone`. A login wall or 403 is not `gone`.

## Two stages: one post ledger, then labels

v0 let each coder pick and count posts from the harvest report; coders disagreed on the post set itself (24 vs 35 authors), so every count diverged. v0.1 separates the two jobs.

1. **Extract** (one worker, once per pass): turn the harvest report into `posts`: one row per post with `id`, `url`, `platform`, `author`, `date`, `grade`, and an optional verbatim `quote` (≤25 words). A script dedupes by URL and by author per thread, and fixes `authors`.
2. **Label** (two coders, different model families, same `posts` list): for each post, fill only the cells the post speaks to: `tier`, `compared_to` [{model, direction}], `maker_guess` [{maker, evidence}], `size_guess`, `strengths`, `weaknesses`, `issues`, `sentiment`. Silent = absent, not a guess.
3. **Count** (script): all cell counts are computed from the labels. Coders never write counts.

## Decision rules (v0.2)

- `tier`: only when the post names a tier ("flash-class", "frontier") or places it against a model of known tier. A bare comparison goes in `compared_to`, not `tier`.
- `sentiment`: the post's overall verdict on the model, not any single sentence. Praise plus a serious complaint = `mixed`. No verdict = absent.
- `numbers.metric` ∈ `throughput`, `latency`, `context`, `max_output`, `needle`, `suite_score`, `benchmark`, `tokenizer_match`, `price`, `other`; anything finer goes in `note`.
- `size_guess`: numeric range plus unit (e.g. `30-40B total, 2-5B active`); spelling is cleaned by script.
- Model and maker names may be written as in the post; the counting script normalizes them to `data/models.json` / `data/makers.json` ids through an alias table before counting.

## Agreement

Measured per post × cell, on direction or value only (not on counts), and only where both coders filled the cell; one coder filling a cell the other left empty is reported separately as `one_sided`, not as disagreement. A cell is `disputed` when the coders disagree on it for any post; disputed labels are dropped from counts unless a reviewer resolves them. If fewer than 70% of post×cell labels agree, fix the codebook before going on (ADR-038 regret condition).

## Enumerations

- `platform`: `x`, `reddit`, `hn`, `linux_do`, `v2ex`, `zhihu`, `bilibili`, `blog`, `news`, `github`, `discord`, `other`.
- `pass`: `day1`, `day3`, `day7`, `reveal`, `retrospective` (back-test harvests of already revealed models).
- `size_guess`: `{"<guess>": posts}`, or the string `not discussed`.
- `compared_to` targets without an FT Intelligence score (e.g. 2024–25 models) are kept for display but excluded from any peer estimate.

## Data shape

One file per model: `data/community/<model-id>.json`

```json
{
  "model": "crouton-alpha",
  "collected": "2026-11-04",
  "pass": "day1",
  "harvest": {"channel": "grok-cli", "report": "<private path>"},
  "authors": 18,
  "posts": [{"id": "p1", "url": "…", "platform": "reddit", "author": "u/…", "date": "2026-11-03", "grade": "hands_on", "quote": "…", "gone": false,
             "labels": {"a": {"tier": "flash", "sentiment": "negative", "issues": ["hallucination"]}, "b": {"tier": "flash", "sentiment": "negative", "issues": ["hallucination"]}}}],
  "tier": {"flash": 7, "mid": 2},
  "compared_to": [{"model": "minimax-m3.1-flash", "direction": "similar", "posts": 4}],
  "maker_guess": [{"maker": "meta", "posts": 5, "evidence": ["geo_block", "api_shape", "style"], "against": {"tokenizer": 3}}],
  "size_guess": "not discussed",
  "strengths": {"search_subagent": 4, "speed": 6},
  "weaknesses": {"coding": 3},
  "issues": {"hallucination": 4, "stops_mid_task": 3},
  "numbers": [{"metric": "throughput", "value": 333.7, "unit": "tok/s", "url": "…", "date": "2026-11-03", "grade": "measured"}],
  "sentiment": {"positive": 5, "mixed": 4, "negative": 7},
  "sources": {"x": 9, "reddit": 7, "blog": 2},
  "first_seen": {"date": "2026-11-03", "url": "…"},
  "quotes": [{"platform": "reddit", "author": "u/…", "date": "2026-11-03", "text": "…", "url": "…", "grade": "hands_on", "gone": false}],
  "disputed": []
}
```

## Refresh

Collected on intake day, day 3, day 7 and reveal day; frozen after that. Each pass overwrites the file; history stays in git.

## Changelog

- v0.2 (2026-11-04): decision rules for tier and sentiment, metric enumeration, size format, alias normalization, one-sided fills counted separately. Cause: P0b disagreement patterns (92.3% agreement overall).
- v0.1 (2026-11-04): two stages (post ledger, then per-post labels; counts by script); agreement per post×cell ≥70%; enumerations; 403 ≠ gone. Cause: v0 double coding diverged on the post set (P0 back-test).
- v0 (2026-11-04): derived from the first two harvests (Crouton Alpha, Pulse Alpha).
