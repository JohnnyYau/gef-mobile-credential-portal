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

## The captioned walkthrough

`demo-media/GEF-mobile-walkthrough.mp4` — 1600 × 900, 67.8 s, 678 frames, no
audio. Five shots in one browser tab: the home page, a valid credential, a
revoked one, an issuance, then the four-step stage run. Because it is one tab,
the block heights in the footage belong to one session and rise 47 → 48 → 50 the
way they really did.

`scripts/record_walkthrough.py`. Two things learned the hard way:

- **One socket, one reader.** Responses and events share the DevTools socket. A
  "read until my id comes back" helper eats the other caller's replies, so with a
  capture loop and a step driver running together, both hang — the first two runs
  sat there for minutes with zero frames. The client now demultiplexes by id, and
  fails fast: a 6 s timeout per screenshot, a closed socket rejects every pending
  call, and no frame within 8 s aborts with a message instead of hanging.
- **Timestamps, not a frame counter.** Frames carry their capture time and are
  resampled onto a 10 fps grid, so a slow frame cannot stretch the video and the
  page's own "140 ms" receipts stay true to the wall clock.

Captions are burned in rather than narrated, for the same reason the stage clip
is silent: a visitor at the booth reads them, and text cannot fall out of sync
with the picture. They also survive a muted autoplay on a laptop screen. No
caption mentions the tunnel address — that URL dies with the tunnel; the closing
card points at the GitHub repo instead.


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

- Whether to reset `data/` before the show.
- Whether the poster's QR should be reprinted to point at the new cut.
