# U29 — the booth fallback, and why the poster stopped counting blocks

## The recording

`demo-media/GEF-mobile-stage-run.mp4` — 1600 × 900, 21.9 s, 175 frames, no audio.
It is one real run of `/showtime?auto=1`: issue → verify → revoke → re-verify,
with the receipts filling in as they happen.

`scripts/record_stage.py` makes it, and the way it does so is the point:

- Chrome runs `--headless`, so nothing appears on the presenter's desktop and no
  other window can leak into the frame.
- Capture goes through DevTools (`Page.captureScreenshot` on a fixed interval),
  not `Page.startScreencast`. Screencast only emits frames on repaint; on a page
  that mostly sits still it produced ~1 frame per second — a slideshow. The
  interval loop gave 8 fps over the same run.

First attempt failed twice, both worth remembering: `-pattern_type glob` does not
exist in every Windows ffmpeg build (use `%05d`), and grabbing a screenshot while
navigation is in flight returns `Not attached to an active page` (wait for
`document.readyState === "complete"`).

Silent on purpose: at the booth the presenter narrates, and a voice-over recorded
off a desk mic would age badly the moment the screen copy changes.

**The QR on the poster still points at the team's existing YouTube video.** If the
new recording is uploaded and the poster should point at it instead, the QR has
to be regenerated (`poster_qr.py`) and the poster reprinted — decide before
printing, not after.

## Why the poster no longer counts blocks

The four-figure strip used to end with `23 / 鏈上塊數 BLOCKS`. Every rehearsal of
the stage adds two blocks, so that number was stale within an hour — it read 23,
then 27, then 30, then 33, all on the same day. A printed poster cannot chase a
counter.

It now ends with **`0 / 上鏈的姓名與成績 PII ON CHAIN`**, which is a property of
the design, not a snapshot: names and grades never touch the chain, only hashes
and signatures. It cannot go stale, and it carries the same claim as the
「三件我們不妥協的事」 list.

The two screenshots still contain a height (they are real captures). They are now
date-stamped in their captions — 「截圖取自 11 月 27 日的一次真實查驗」 — so the
number reads as a moment, not as a live counter.

## Still open

- The narrated two-minute cut (the original pipeline: five screen clips +
  `narration.wav` + concat) has not been rebuilt against the new copy.
- Whether to reset `data/` before the show.
