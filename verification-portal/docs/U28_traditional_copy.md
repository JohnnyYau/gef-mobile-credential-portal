# U28 — one voice: Traditional Chinese, Hong Kong

## The gap

U27 fixed what the screen *said*. It did not ask *what language it said it in*.

The product spoke Simplified — `这张证书是真的吗`, `機構签发一张证书`, `验证次数`.
The poster, the deck and the audience were Traditional. A judge walking from the
poster to the laptop read two different products: the printed material promised
one voice, the screen delivered another. Nobody would call it a bug, but on a
showcase table it is the first thing that reads as unfinished.

## What changed

| Area | Before | After |
|---|---|---|
| Served copy (16 files) | Simplified | Hong Kong Traditional, 2,664 chars |
| `<html lang>` (6 pages) | `zh-CN` / `zh-HK` | `zh-Hant-HK` |
| Stage headline | 一張證書，四個步驟 | 一張證書，四個環節 (matches poster + deck) |
| `/api/extract/pdf` rejection | 仅支持 PDF 文件。请上传证书 PDF（.pdf）。 | 僅支援 PDF 檔案。請上傳證書 PDF（.pdf）。 |
| Auto-fill note | 自动填充仅供输入辅助… | 自動填入僅供輸入輔助… |

The conversion is `scripts/to_traditional.py`. It rewrites **CJK runs only** —
`[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+` — so no tag, no identifier, no
ASCII byte and no file structure can move. opencc `s2hk` does the bulk (it keeps
平台 and 後台, which `s2t` turns into 平臺 / 後臺), then three overrides for terms
Hong Kong reads differently:

- 鏈接 → 連結
- 裏 → 裡
- 默認 → 預設

The script is idempotent and has `--check` (report) vs `--apply` (rewrite), so
the next round can re-run it after adding copy and see only the new strings.

## What deliberately did **not** move

- `app/pdf_extractor.py` — its Chinese strings are **parse labels** for
  Simplified sample PDFs (烧鸡.pdf). Converting them would stop the extractor
  from reading the very file the demo uploads.
- `app/config.py` — `自制凭证-outputs` is a default directory name, not copy.
- Data on the chain, sample hashes, fingerprints, `docs/` and the English docs.

## Tests

Two assertions pinned the old copy and had to move with it — that is the test
doing its job, not a workaround:

- `tests/test_frontend.py`: `开一张证书` → `開一張證書`, `四个步骤` → `四個環節`
- `tests/frontend/assertions.js`: `真实有效` → `真實有效` (×2)

Full suite after the change: **39/39 modules green**, including `test_u22_text_fit`
(no line overflows after the character swap) and the JS harness at 34/34.

## Assets rebuilt after the copy change

The poster and deck show real screenshots, so their pixels were stale the moment
the copy moved. Rebuilt in this order:

1. `/showtime?auto=1` once (a real run — chain 23 → 27, receipts 第 26 塊 · 14 ms,
   第 27 塊 · 10 ms). Any run adds two blocks, so this is unavoidable, not drift.
2. `/verify?hash=…` at 2× — reads 整條鏈 27 塊, matching the stage shot.
3. `poster.html` number 23 → 27, step meta 16 ms → 14 ms (the measured call).
4. Poster PNG (4967 × 7022, 150 dpi) → PDF → deck; showcase deck rebuilt with
   the same receipts (第 26 塊 · 14 ms / VALID · 10 ms / 第 27 塊 · 10 ms /
   REVOKED · 10 ms).
5. Both QR codes re-decoded off the final render: still 3 codes, YouTube and
   GitHub intact.

## Still open

- If the demo chain is reset before the show, the poster's 27 and the two
  screenshots become a snapshot of a different state. Note it or don't reset.
- The legacy `/portal` and `/staff` pages are converted but were not
  re-screenshotted; they are not on the demo path.
