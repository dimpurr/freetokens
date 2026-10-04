# freetokens

Where can you use a capable LLM for free **right now**, through which channel, under which conditions, and **until when**?

This is a hand-curated demo (v0, 2026-10-04). It tracks **free lanes**: one model × one channel × one free condition. The focus is on the offers existing lists miss: limited-time free models inside **subscription and agent tools** (OpenCode Zen / Go, Command Code, …) and router listings, together with the **dates they started and are expected to end**.

## How to read this

- **Every fact carries a date and a source.** A row is only as good as its `Checked` date. If that date is old, treat the row as stale.
- **Unknown is written as unknown**, never left blank: `unstated` means the provider says nothing; `not checked` means we haven't looked.
- **End-date confidence**
  - `official`: the provider published a date.
  - `inferred`: derived from an announced duration (for example "two weeks" counted from the post time), or from a sibling channel.
  - `none`: no end announced. It can still stop at any time.
- **Status**
  - 🟢 live
  - 🟡 live, but past its announced end, so it can stop without notice
  - ⚪ listed, but not answering
  - 🔴 ended
- **Observed limits** are one-off light readings from our own account, with their date. They are not load tests and not guarantees.
- Post times on X are decoded from the post ID (UTC).

## 1 · Free lanes

| Model | Channel | Type | Model ID | Free condition | Limits (stated) | Limits (observed) | Started | Ends | Data policy | Status | Checked |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Ling 3.1 Flash | Command Code | agent tool | `inclusionai/ling-3.1-flash:free` | Command Code account, 0 credits ("while it lasts") | **300 requests/day** ([src](https://x.com/CommandCodeAI/status/2106576422655680856)) | 15 parallel agent runs OK (10-04) | 2026-09-30 | none | may be used to improve the model | 🟢 | 2026-10-04 · agent run |
| MiMo V2.6 Flash | OpenCode Zen | agent tool | `opencode/mimo-v2.6-flash-free` | no key; **only works from inside OpenCode** (raw API → 403 `FreeTierError`) | unstated | 15 parallel agent runs OK (10-04) | 2026-09-21 | 2026-09-28 · official ("next week"), **passed** | Zen free models may be logged / used for training | 🟡 | 2026-10-04 · agent run |
| LongCat 2.5 Preview | OpenCode Go | agent tool | `opencode-go/longcat-2.5-preview-free` | OpenCode Go; does **not** use Go plan quota | unstated | 15 parallel agent runs OK (10-04) | 2026-09-26 | ≈ 2026-10-10 13:38 UTC · inferred ("two weeks") | zero retention, no training | 🟢 | 2026-10-04 · agent run |
| Space Bunny (stealth) | OpenCode Go | agent tool | `opencode-go/space-bunny-free` | OpenCode Go; does **not** use Go plan quota | unstated | ≤ 10 parallel; at 15, 6 runs hung with no 429 (10-04) | 2026-09-23 ([src](https://x.com/opencode/status/2102767716666941864)) | 2026-09-30 official ("next week"), **passed**; likely 10-05 with the stealth period · inferred | zero retention, no training | 🟡 | 2026-10-04 · agent run |
| Space Bunny Alpha (stealth) | Command Code | agent tool | `stealth/space-bunny-alpha` | Command Code, all plans, 0 credits | unstated | 15 parallel agent runs OK (10-04) | not recorded | **2026-10-05** · official ([src](https://x.com/CommandCodeAI/status/2105492145033330916)); time and zone not given | unstated | 🟢 | 2026-10-04 · agent run |
| Space Bunny Alpha (stealth) | OpenRouter | router | exact ID not recorded | OpenRouter account | not checked | not checked | 2026-09-23 | **2026-10-05** · official (listing banner "Going away October 5") | not checked | 🟢 | 2026-10-04 · listing only |
| DeepSeek V4 Flash | OpenCode Zen | agent tool | `opencode/deepseek-v4-flash-free` | no key; "available for a limited time" | unstated | — | back in catalogue 2026-08-16 | none | Zen free models may be logged / used for training | ⚪ shown as unavailable | 2026-10-04 · catalogue |
| Nemotron 3 Ultra | OpenRouter | router | `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter account | not checked | not checked | 2026-06 | none | not checked | 🟢 (as of last check) | **2026-07-25** · API call — stale |

Also listed but not yet tracked here: Ling 3.1 Flash on Cline (reportedly free until 10-13) and on OpenCode (reportedly free from 10-02). Both are unverified.

## 2 · Timeline

Newest first. `→` marks expected future events.

| Date (UTC) | Lane | Event | Source |
|---|---|---|---|
| → ≈ 2026-10-10 | LongCat 2.5 Preview · OpenCode Go | expected end (two weeks from 09-26 13:38) | inferred |
| → 2026-10-05 | Space Bunny · OpenRouter, Command Code (and likely OpenCode Go) | announced end of free stealth period | [Command Code](https://x.com/CommandCodeAI/status/2105492145033330916) · OpenRouter banner |
| 2026-10-04 02:45 | Ling 3.1 Flash · Command Code | free limit raised to 300 requests/day | [Command Code](https://x.com/CommandCodeAI/status/2106576422655680856) |
| 2026-10-04 | DeepSeek V4 Flash · OpenCode Zen | shown as unavailable in the catalogue | own check |
| 2026-10-01 02:57 | Space Bunny Alpha · Command Code | "continues to be free … till Oct 5 on all plans" | [Command Code](https://x.com/CommandCodeAI/status/2105492145033330916) |
| 2026-09-30 | Space Bunny · OpenCode Go | announced week passes; still live on 10-04 | own check |
| 2026-09-30 01:10 | Ling 3.1 Flash · Command Code | made free ("while it lasts") | Command Code on X (link not recorded) |
| 2026-09-28 | MiMo V2.6 Flash · OpenCode Zen | announced week passes; still live on 10-04 | own check |
| 2026-09-26 13:38 | LongCat 2.5 Preview · OpenCode Go | free "for two weeks" on OpenCode | OpenCode and Meituan on X (link not recorded) |
| 2026-09-23 14:48 | Space Bunny Alpha · OpenRouter | listed as a free anonymous model | OpenRouter |
| 2026-09-23 14:31 | Space Bunny · OpenCode Go | free "for the next week" | [OpenCode](https://x.com/opencode/status/2102767716666941864) |
| 2026-09-21 21:19 | MiMo V2.6 Flash · OpenCode Zen | free "for the next week" | OpenCode on X (link not recorded) |
| 2026-08-16 | DeepSeek V4 Flash · OpenCode Zen | free tier back in the catalogue (HTTP 200) | own check |

## 3 · Models

Benchmarks are kept here once per model rather than repeated per lane. The AA column is the [Artificial Analysis](https://artificialanalysis.ai) Intelligence Index, read on 2026-10-04 unless noted.

| Model | Maker | Context | Image input | AA index | Notes |
|---|---|---|---|---|---|
| Ling 3.1 Flash | inclusionAI (Ant) | 262K | ❌ | 41 | |
| MiMo V2.6 Flash | Xiaomi | not checked (Zen free tier has been capped at 200K before) | ❌ | 38 | |
| LongCat 2.5 Preview | Meituan | 1M | ⚠️ accepts images; one colour test answered wrongly | not ranked (LongCat 2.0: 19) | ~1.6T total / 48B active MoE; released 2026-09-25 |
| Space Bunny (stealth) | undisclosed | 1M | ✅ | not ranked | **Rumoured:** MiniMax family (several independent tokenizer tests), possibly M3.1 / M3.1-Flash. Some sources dispute the exact version, and there is no official confirmation. |
| DeepSeek V4 Flash | DeepSeek | 200K on the Zen free tier | ❌ | 34 | |
| Nemotron 3 Ultra (550B-A55B) | NVIDIA | 1M | ❌ | ≈ 23 | |

## Scope and method

- **In scope:** models you can call for free (no per-token charge) through a public channel, including those that require an account or a paid plan in which the model is zero-credit.
- **Out of scope (for now):** subscription prices and quotas in general (see [tokenplans.dev](https://tokenplans.dev)); permanent free API tiers in general (see [freellm.net](https://freellm.net)); institutional or private gateways.
- **"Agent run" check:** a real coding-agent task (OpenCode) completed and independently verified on that date.
- **"Catalogue" / "listing" check:** we read the provider's model list or page, without making a successful call.
- Nothing here is a load test. Free shared tiers are not to be stress-tested.

## Status of this repo

Demo v0, curated by hand in one pass. There is no automation, and there is no promise of updates yet.
