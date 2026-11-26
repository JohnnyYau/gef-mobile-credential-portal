# U27 — UI pass for the showcase: wrong words out, the process on screen

## The gap

The showcase is in two days. The complaint was not "it does not work" but
"people can't see it work": the product verified correctly, yet the screen a
visitor landed on showed a phone-sized card in the middle of a 1440 projector,
the verdict fell below the fold, and the only trace of the machinery was one
sentence. A judge could believe the sentence or not — there was nothing to
watch.

So this pass is not a redesign. It is three things:

1. find every place where the UI *says something that is wrong*;
2. make the largest screen the primary target, not the fallback;
3. put the real process — block numbers, timings, what was looked up — on
   screen, using data the server already returns.

## What was actually wrong

Audited by rendering every page in headless Chrome at 1440×900 and reading the
DOM, not by eyeballing the source.

| # | Where | What it said | Why it is wrong |
|---|-------|--------------|-----------------|
| 1 | `/showtime` | 按**右下角**「开始」 | the button sits bottom-*left*; anyone following the text points at empty space |
| 2 | `/` REVOKED result | `原因：DEMO SAMPLE: issued by mistake。` | a staff free-text field from the seed data, in English, with a Chinese full stop — reads like a debug line |
| 3 | `/issue` footer | 完整控制台 `/staff` | prints a raw route as link text, and `/staff` is a 303 to the sign-in page, not the console the audience should see |
| 4 | `/portal` stat card | 验证次数 **Checks** | "Checks" in this repo means the six verification checks, not the number of verifications |
| 5 | `/` at 1440×900 | 560 px card, 17 px body | looks like a phone app opened on a projector; the verdict landed under the fold |
| 6 | `/` brand link | `Credential Verification Portal` → `/portal` | clicking the home logo left the one-screen page |
| 7 | `/` result | one sentence, nothing else | the process — issue block, signature check, hash compare, revocation lookup — was invisible |
| 8 | `/showtime` step row | four empty boxes | the four cards were decoration; they said nothing about what happened in each step |
| 9 | `/showtime` step timings | `VALID · 2.4s` | that number included a deliberate `await wait(2400)`, so it claimed the API took seconds when it took milliseconds |

Nos. 2, 3 and 9 are the ones that would have been visible from the front row.

## What changed

**`/` (one-screen verify)**

- desktop first: at ≥900 px the card is 900 px wide with 42 px headline, 18 px
  body; below 900 px it stays the phone layout.
- after a verdict the input form folds away (`hidden`), which lifts the verdict
  and the trace into the first screen — no more scrolling to see the answer.
- new block under the verdict: 「这次查验做了什么」, four numbered rows built
  from the response itself —
  1. 取回链上记录 — 第 N 块，签发于 …
  2. 验证数字签名 — 用机构的公钥验过，签名有效
  3. 比对证书内容 — 文件与链上哈希一致 / 只给了编号，本次没有文件可比
  4. 查询撤销名单 — 没有记录 / 第 N 块写过一笔注销
  plus a footer line: 整条链 N 块完整性检查通过 · 本次查验 XX ms. The chain
  height comes from `/healthz`, the milliseconds are measured in the page
  around the `fetch` — both real, neither hard-coded.
- revocation reasons get a small dictionary (`issued by mistake` → 当初签发有误
  （课程演示样例）, `revoked on stage` → 在展示现场当场注销（演示）); unknown
  reasons are shown as typed, never invented.
- the brand link points at `/` again, and a three-pill nav (验证 / 签发 /
  现场演示) makes the whole demo one click away from any page.

**`/issue` (three fields)**

- footer now points at `/portal` (the real console) instead of the bare
  `/staff` route;
- same nav header as `/`.

**`/showtime` (stage)**

- 「按左下角「开始」」 — the text now matches the button;
- each of the four step cards keeps a receipt once it finishes: `第 18 块 ·
  127 ms`, `VALID · 10 ms`, `第 19 块 · 10 ms`, `REVOKED · 10 ms`;
- timings measure the `fetch` only, not the 2.4 s pause used for pacing;
- the revoke call now writes a Chinese, audience-facing reason
  (在展示现场当场注销（演示）) instead of `SHOWCASE demo: revoked on stage`;
- the QR is 260 px with a caption (扫一下，用手机看它现在的状态), because judges
  scan from a distance;
- after the fourth step 「开始」 hides and 「重来」 takes its place — one
  unambiguous button at the end.

**`/portal`**

- 验证次数 Verifications (the old label said Checks).

## How it was verified

| Check | Result |
|-------|--------|
| `tests.test_frontend` | 29 / 29 |
| `tests.test_hardening` | 11 / 11 |
| `tests.test_api` | 16 / 16 |
| `/` at 1440×900, valid hash | verdict + four trace rows + `整条链 15 块…15 ms` all above the fold |
| `/` revoked sample | 原因 reads 当初签发有误（课程演示样例）, trace shows 第 3 块 / 第 4 块 |
| `/showtime` `?auto=1` | four steps complete, receipts show 127 / 10 / 10 / 10 ms, ends 「↩ 已注销」 |
| 500 px viewport | no horizontal overflow; the 390 px screenshot that looked clipped was Chrome's ~500 px minimum window width, not the CSS |

## Still open

- The mobile breakpoint was tuned by arithmetic and one 500 px render, not on a
  real phone. `/` and `/issue` are fine; `/showtime` is a stage page and is not
  meant for phones.
- The trace rows are a fixed four. A file-based check (`hash_match`) replaces
  row 3's text but adds no row; if the six checks ever split, this needs a
  rethink.
- No dark mode, no reduced-motion pass. `/showtime` relies on CSS transitions
  only, so it is cheap to add later.
