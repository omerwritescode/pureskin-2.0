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

None has been supplied yet. Each slot is wired to the path below and shows a plain
chip-colour block until its file is dropped into `frontend/static/media/`.

Rules for every file:

- A real adult (18+) who gave written consent. The consent forms are kept outside this
  repository, and nothing here names the person.
- Natural daylight. No retouching, smoothing, filters, beauty mode or portrait mode. No
  products in the frame, no before/after pairs, no stock models.
- GPS and other metadata stripped on export.
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
