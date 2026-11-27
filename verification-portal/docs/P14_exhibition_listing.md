# P14 — exhibition listing text

The 2023 and 2024 showcases publish each project as a row of fields on a shared
GitHub Pages site: **Project ID**, title, student names, a short English
abstract paragraph, a *Video Demo* link, a *GitHub* link, and the poster image.
The abstract there is 60–90 words of plain prose, not bullets.

This file is the paste-ready version of those fields for P14. Nothing here
invents a number: every figure comes from the running portal.

---

**Project ID:** P14

**Title:** Mobile Credential Verification Portal — One Certificate, Four Checks

**Students:** Yau Ka Chai Johnny · Yu Siu Kui · Yu Yeuk Lan Serena

**Abstract (≈85 words):**

> An employer holding a diploma PDF has no cheap way to check that it is real,
> so they email the registry and wait. This portal puts one certificate through
> four checks on a single screen — the chain's integrity, the issuer's
> signature, the certificate's hash, and its revocation status — and returns a
> plain verdict with the measured milliseconds for each step. Credentials are
> signed with ML-DSA-65 or RSA-PSS-2048. Only hashes and signatures reach the
> chain, so no name or grade is ever stored there.

**Abstract (繁體，for the booth or a Chinese page):**

> 一張文憑，四個環節。僱主收到一份 PDF，不必再打電話去教務處：入口網站把證書
> 依次做鏈完整性、簽發方簽名、憑證雜湊、撤銷狀態四項查驗，在同一頁給出結論與
> 每一步實測毫秒。簽名用 ML-DSA-65 或 RSA-PSS-2048；上鏈的只有雜湊與簽名，
> 姓名與成績不會上鏈。

**Video Demo:** https://youtu.be/nVgevH43FYA

**GitHub:** https://github.com/JohnnyYau/gef-mobile-credential-portal

**Poster:** `P14-A0-Poster.pdf`（A0 841×1189 mm，150 dpi）

---

## Where this differs from the published template

The 2023/24 posters are one house style: a blue header band with the CityU and
Department of EE logos, the programme line, the project title, `Student: …`,
`Project ID: Pxx`; then two columns of **Abstract / Objective·Background·
Motivation / Methodology** on the left and **Results·Application /
Discussion·Conclusion / Reference** on the right, with two QR codes labelled
*Source Code* and *Demo Video*.

P14's poster keeps the last of those (two QR codes, one to GitHub, one to the
demo video) but replaces the section list with the thing that is actually hard
to believe on a poster: the four steps, their real timings, and the fact that
zero PII goes on chain. There is no separate *Methodology* block because the
method is the demo; the four receipt times are the results.

If the organisers need the listing fields above, use this file. If they need the
poster rebuilt inside their template, that is a reprint and a new layout — worth
doing only if they ask explicitly.
