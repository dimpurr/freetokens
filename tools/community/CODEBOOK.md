# Community take · codebook v0

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

3–5 per model. Prefer `measured` and `forensic`, then `hands_on`; cover both sides when sentiment is split. Each quote ≤25 words, verbatim, with platform, handle, date and URL. If the source later disappears, keep the card and mark it `gone`.

## Double coding

Two coders (different models) code the same harvest report independently. Cells where they disagree on direction or differ by more than one post are flagged `disputed` and shown only after review. If more than 30% of cells disagree, fix the codebook before going on (ADR-038 regret condition).

## Data shape

One file per model: `data/community/<model-id>.json`

```json
{
  "model": "crouton-alpha",
  "collected": "2026-11-04",
  "pass": "day1",
  "harvest": {"channel": "grok-cli", "report": "<private path>"},
  "authors": 18,
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

- v0 (2026-11-04): derived from the first two harvests (Crouton Alpha, Pulse Alpha).
