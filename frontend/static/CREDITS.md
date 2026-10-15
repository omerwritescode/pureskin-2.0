# Credits

Every font, photo and video the frontend serves, with its source and licence. Everything
is self-hosted under `frontend/static/`; no page loads a file from another website.

## Fonts

### Archivo

| | |
|---|---|
| File | `fonts/archivo/Archivo-Variable-latin.woff2` (92,416 bytes) |
| Licence | SIL Open Font License 1.1, in `fonts/archivo/OFL.txt` (the text unchanged; the download has CRLF line endings, which git stores as LF) |
| Copyright | Copyright 2020 The Archivo Project Authors (https://github.com/Omnibus-Type/Archivo) |
| Reserved Font Name | None. The OFL.txt header declares none; the phrase appears only in the licence's own definitions. |
| Source | Google Fonts, the official "Download family" list for Archivo: https://fonts.google.com/download/list?family=Archivo, file `Archivo-VariableFont_wdth,wght.ttf` (v25: https://fonts.gstatic.com/s/archivo/v25/k3kQo8UDI-1M0wlSTd7iL0nAMaM.ttf, 652,084 bytes) and `OFL.txt` |
| Downloaded | 2026-10-14, 17:54 UTC |
| Upstream | https://github.com/Omnibus-Type/Archivo (Omnibus-Type; no GitHub release is published) |
| Changes | Subset to Latin and converted to WOFF2 (an OFL "Modified Version"; the name may stay because there is no Reserved Font Name). Both variable axes kept: weight 100-900, width 62-125. Only the upright style ships. |

The subset was made with fontTools 4.66.1 and brotli 1.2.0, installed into
`backend/.venv` only (they are not in any requirements file):

```bash
backend/.venv/Scripts/pyftsubset "Archivo-VariableFont_wdth,wght.ttf" \
  --unicodes="U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+20B9,U+2122,U+2212" \
  --layout-features='*' --flavor=woff2 \
  --output-file=frontend/static/fonts/archivo/Archivo-Variable-latin.woff2
```

That keeps Basic Latin, Latin-1, the Œ/œ and dotless-i letters, general punctuation (curly
quotes, dashes), €, ₹, ™ and the minus sign, with all OpenType features (including
tabular figures).

## Photos and video

The hero strip (the last row) and the two photo backgrounds are served. Each other slot is wired to the path
below and shows a plain chip-colour block until its file is dropped into
`frontend/static/media/`.

Rules for team-shot photos and video:

- A real adult (18+) who gave written consent. The consent forms are kept outside this
  repository, and nothing here names the person.
- Natural daylight. No retouching, smoothing, filters, beauty mode or portrait mode. No
  packaging, brand, logo or on-screen text in the frame (a product being applied is fine), no
  before/after pairs, no stock models.

Licensed media: only the files `PRODUCT.md` (Imagery) names. Each row gives its source and
licence or permission, never "own work".

Rules for every file:

- Team-shot files: GPS and other metadata stripped on export. A licensed file whose
  permission allows no changes is served byte for byte, so it is checked for location data
  instead (and its size and SHA-256 recorded here).
- One row per file below: what it shows, who made it, the date, and the licence or
  permission.

| Slot | File(s) | Status | Source | Licence / permission |
|---|---|---|---|---|
| V1 video (How a scan works) | `media/v1-selfie-window.webm`, `media/v1-selfie-window.mp4`, poster `media/v1-selfie-window-poster.jpg` | not supplied yet | | |
| M1 Acne (fan blade) | `media/m1-acne.jpg` | not supplied yet | | |
| M2 Redness | `media/m2-redness.jpg` | not supplied yet | | |
| M3 Wrinkles | `media/m3-wrinkles.jpg` | not supplied yet | | |
| M4 Pigmentation | `media/m4-pigmentation.jpg` | not supplied yet | | |
| M5 Pores | `media/m5-pores.jpg` | not supplied yet | | |
| G1-G3 selfie guide (optional) | `media/g1-light-window.jpg`, `media/g2-light-backlit.jpg`, `media/g3-light-overhead.jpg` | not supplied yet | | |
| B1 photo background (Dashboard, Skin Profile, Routine, Catalog, product detail) | `media/backdrop-1.png`: the original file, unchanged (1920×1080 PNG, 3,249,050 bytes, SHA-256 `64534ddbdf43507a0341c4d571ccba3385cc5abe7288015d3398497764bd0945`). Metadata: one XMP tag ("CreatorTool: Canva"); no location data (checked 2026-10-15). | served as is (Unit 4b): the page background from 1024px under a 60% ground veil, a 200px band below that | Canva library: a close-up of a cream being applied under a closed eye (stock) | Used with Canva's written permission by email (15 October 2026), on condition that no changes are made to the image; served byte for byte. |
| B2 photo background (Settings hub, Account, Privacy, About, Contact) | `media/backdrop-2.png`: the original file, unchanged (1920×1080 PNG, 2,805,909 bytes, SHA-256 `00e4936b4a9c382e53076891771ba89a0038836738aa478c20b826bccbd6ed98`). Metadata: one XMP tag ("CreatorTool: Canva"); no location data (checked 2026-10-15). | served as is (Unit 4b), as B1 | Canva library: a close-up of a cream being applied to a cheek (stock) | Used with Canva's written permission by email (15 October 2026), on condition that no changes are made to the image; served byte for byte. |
| A1 header band (About, Contact) | `media/backdrop-2.png` (B2 itself; the band's framing is CSS only) | served as is (Unit 4b): the band below 1024px | the B2 photo | as B2 |
| Hero strip (the landing page's first screen) | `media/hero-strip.webm` (1,838,155 bytes, SHA-256 `e4c29e9e159081b2d4bd5d2f871de0b0eaabd8288adfd5c9678f90d73ad8382c`); `media/hero-strip.mp4` (2,434,844 bytes, SHA-256 `38f592d38f12e813272b65e90cca97d3f835150c8610dce5d8bd011858540ba4`); `media/hero-strip-phone.webm` (1,306,872 bytes, SHA-256 `cbd99654065b555fcb044436eff12b4a610d6aea9023b4942006e3717d3d3424`); `media/hero-strip-phone.mp4` (1,639,155 bytes, SHA-256 `29453fa01f2c3d06ef5578ac92a6088c383fb36055e7c3577ad462d0b64176cb`); `media/hero-strip-poster.jpg` (36,830 bytes, SHA-256 `7389d33791dbb00a95e11313d3fd08f3866ab7ed67322ef71c4cb8abc47dd534`); `media/hero-strip-phone-poster.jpg` (32,460 bytes, SHA-256 `273e381c54510817176b37ca6973205157e2a48f83c33e0b4764e91391e61a5d`). A 9.77 s loop (244 frames) edited from Dove's film: frames 0-72, 110-156, 299-343, 393-432 and 459-497 at 25000/1001 fps (0.00-2.92, 4.40-6.29, 11.97-13.77, 15.74-17.34 and 18.38-19.94 s: the eyelid and the gardenia, a leaf and wet skin, an aerial river, mushrooms, a tree trunk and the forest before its caption). Desktop: the 1920×600 middle band (y 240-840); phone: a 996×1080 centre crop (x 462) scaled to 720×780, served below 600px. VP9 (CRF 34) and H.264 (CRF 23, slow, fast start); no audio track; metadata stripped (only the fields the formats require remain: WebM's muxing app "Lavf", MP4's handler "VideoHandler" and language "und"); each poster is its size's first frame. The original file (12,559,666 bytes) is no longer served; it stays outside git. | served, with the credit "Video: Dove, used with permission. PureSkin isn't affiliated with Dove." under it | Dove (Unilever): the film "Your skin. Our planet.", cut and cropped by the team (no captions, no logo, no scar or stretch-mark shots) | Film: Dove (Unilever), 'Your skin. Our planet.' Used with written permission for this project, granted 15th October, 2026. Scope: this academic project only. Edited under a second email from Dove the same day (15 October 2026), which cleared cropping and editing the film as the team likes. The credit stays. The emails are kept outside the repository. |
