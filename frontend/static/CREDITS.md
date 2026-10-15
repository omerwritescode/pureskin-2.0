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

One file is served: the hero film (the last row). Each other slot is wired to the path
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
| B1 photo background (Dashboard, Skin Profile, Routine, Catalog, product detail) | `media/backdrop-1-desktop.{webp,jpg}`, `media/backdrop-1-phone.{webp,jpg}` | supplied, not processed yet (Unit 4b) | Canva library: a close-up of a cream being applied under a closed eye (stock) | Open-To-Use, as recorded by the team |
| B2 photo background (Settings hub, Account, Privacy) | `media/backdrop-2-desktop.{webp,jpg}`, `media/backdrop-2-phone.{webp,jpg}` | supplied, not processed yet (Unit 4b) | Canva library: a close-up of a cream being applied to a cheek (stock) | Open-To-Use, as recorded by the team |
| A1 header band (About, Contact) | `media/band-desktop.{webp,jpg}`, `media/band-phone.{webp,jpg}` | supplied, not processed yet (Unit 1c) | the B2 photo, a clear crop | as B2 |
| Hero video (the landing page's first screen) | `media/hero-video.mp4`: the file as received, unchanged (12,559,666 bytes; SHA-256 `48579925b6ae43f66740004de37825f39f45cf15faafd2e4ec80688eb0d0874d`). H.264, 1920×1080, 25 fps, 30 s, no audio track; no location data or other metadata box (checked 2026-10-15). | served as is, with the credit "Video: Dove, used with permission. PureSkin isn't affiliated with Dove." under it | Dove (Unilever): the film "Your skin. Our planet.", with Dove's logo and captions | Film: Dove (Unilever), 'Your skin. Our planet.' Used with written permission for this project, granted 15th October, 2026. Scope: this academic project only; as is only (no trim, crop, re-encode or extracted poster); the email is kept outside the repository. |
