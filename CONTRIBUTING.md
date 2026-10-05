# Contributing to freetokens

Thanks for helping. freetokens is only as good as its data, and free LLM offers change every week.

## Two ways to contribute

| | Who it's for | What you do |
|---|---|---|
| **1 · Open an issue** | anyone | [Open an issue](../../issues/new) with the link and what changed ("X is free on Y until Oct 12", "Z now returns 404, here's the error"). We turn it into data. |
| **2 · Open a pull request** | if you're comfortable editing JSON | Edit [`data/`](data/), make sure every fact has a source link and a date, run `python3 build.py --validate`, and open a PR. |

Both are welcome; an issue with a good link is just as useful as a PR. The rest of this guide is for route 2, but the rules below apply to both.

## What we're looking for

| You found… | Edit | Example |
|---|---|---|
| A new free model on a channel | add a lane to `data/lanes.json` and an `announced` / `listed` / `available` event to `data/events.json` | "X is free on OpenRouter from today" |
| An end date being announced | add an `end_announced` event with `end_date`, and set the lane's `ends` | "free until Oct 5" |
| A free offer that stopped | set the lane's `status` to `ended` and add an `ended` event | calls start returning 404 / 402 |
| A changed limit | add a `limit_changed` event and update `limits_stated` | "now 300 requests/day" |
| A limit you measured yourself | `limits_observed` with the date (see the rules below) | "10 parallel agent runs OK, 15 hung" |
| A new model's facts | add it to `data/models.json` | context window, image input, AA index |
| A mistake | fix it, and say in the PR how you know | |

## The rules (the build checks most of them)

1. **Every fact has a source.** Events need `source.url` (or a `source.label` such as "own check" plus a note on what you did). A stated limit gets `limits_stated.source`. No source, no fact.
2. **Every fact has a date.** Use UTC. Formats: `2026-10-05`, `2026-10-05T19:02Z`, or `2026-10` when only the month is known.
   - **Posts on X:** the post time is encoded in the post ID. Use `(id >> 22) + 1288834974657` milliseconds since the Unix epoch.
3. **Unknown is not empty.** Write the unknown out:
   - `unstated`: the provider says nothing;
   - `not checked`: nobody looked;
   - `not recorded`: seen, but the detail wasn't kept.
4. **Distinguish what was announced from what we infer.** `ends.announced` is a date someone published. `ends.expected` is our inference, with `confidence: "inferred"` and a `note` saying how it was derived ("two weeks from the announcement").
5. **Status follows the evidence:**
   - `live`: answered at the last check;
   - `overdue`: still answering after its announced end;
   - `unavailable`: listed but not answering;
   - `ended`: no longer free.

   The build refuses a lane that is `live` after its announced end, or `ended` without an `ended` event.
6. **A catalogue listing is not proof of life.** Providers often keep a model in their list after it stops working. Say how you checked (`checked.method`): `agent_run`, `api_call`, `catalogue` or `listing`.
7. **Measured limits come from your own account, measured lightly, once.**
   - Don't load-test shared free tiers.
   - Give the date and what you ran ("15 parallel coding-agent runs, each a small task, all passed").
   - Never include API keys, account names or request IDs that identify you.
8. **No descriptions or opinions.** freetokens records facts with sources. The only estimate on the site is the EST band for models without an official AA index, and it is computed by a published method, not written by hand.
9. **Benchmarks for a model that isn't the one listed don't count.** A stealth model's rumoured identity, a predecessor or a sibling model are different models.

## Field reference

`schema/schema.json` lists every required field and every allowed value (status, confidence, check method, channel type, data policy, event kind). The legend on the website and in the README is generated from it.

A minimal lane:

```json
{"id": "example-or", "model": "example-model", "channel": "OpenRouter", "type": "router",
 "model_id": "vendor/example-model:free",
 "free_condition": "OpenRouter account",
 "limits_stated": {"text": "unstated"},
 "limits_observed": null,
 "started": {"date": "2026-10-05"},
 "ends": {"announced": null, "expected": null, "confidence": "none"},
 "data_policy": "not_checked", "status": "live",
 "checked": {"date": "2026-10-05", "method": "api_call"}}
```

and the event that backs its start date:

```json
{"date": "2026-10-05", "lanes": ["example-or"], "kind": "listed",
 "text": "Listed as free on OpenRouter",
 "source": {"label": "OpenRouter", "url": "https://openrouter.ai/vendor/example-model"}}
```

Lane IDs are short and stable (`model-channel`). Model IDs become page URLs, so use lowercase letters, digits, `.` and `-` only.

## Checking your change

```sh
python3 build.py --validate   # checks data/ only and writes nothing; this is all a PR needs
python3 build.py              # optional: regenerate README tables and the pages to preview locally
```

Only Python 3's standard library is needed. In your PR, you can leave out the regenerated files (`README.md` tables, `index.html`, `models/`, `channels/`); the maintainer rebuilds them on merge.

## License of contributions

By contributing data you agree to license it under [CC BY 4.0](data/LICENSE.md), the same as the rest of `data/`. Code contributions to `build.py` and `schema/` are under [MIT](LICENSE).
