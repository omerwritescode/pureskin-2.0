# Frontend redesign: direction B ("shade card")

Everything a new session needs to continue the frontend redesign. Product truth (users, voice,
imagery, accessibility) lives in `PRODUCT.md`; the design-direction contract lives in
`.impeccable/surfaces/frontend-pages-index-html.md`. This file records the decisions, the
tokens, the assets, the remaining units and the working rules.

**Status (2026-10-15).** Unit 1 is done: Archivo, the tokens and the shared shell
(`ffcf85e`), plus a Skin Profile fix (`96f2c87`). Unit 2 is done: the landing page at `/`
and `test_frontend_landing.py` (commit "Frontend redesign (2): landing page at /, landing
tests"). Next: Unit 3, auth. Every unit stops for the user's review at 360 px and 1440 px,
then waits for a separate commit authorisation (section 9).

## 1. The direction

**Concept.** The Skin Profile as a paint-shop shade card (a fan deck). The five scores are
the deck's blades, each band is a labelled chip, and every product left out of a routine
carries a printed reason. White card-stock slips with a rivet hole sit on a counter-grey
ground. There is one action colour, a deep brown.

**The five score blades:** Acne, Redness, Wrinkles, Pigmentation, Pores, the five scores
the Skin Profile shows. Skin type and sensitivity come from the questionnaire and are shown
as text, never as blades.

**The landing page's first screen (1440 px).** The deck is centred and pinned at its rivet,
with a macro photo of real skin under each blade's name. Below it come a two-line headline
("Every concern has a name. Every product has a reason."), a three-line lede, "Start your
free scan" in action brown with Log in and Sign up beside it, and then the privacy line. On
phones the copy comes first, then the deck closed into one upright strip card.

**The tone rule.** The five skin chips (`--chip-1` to `--chip-5`) and the macro photos are
decoration only.
- They never encode severity, a score, a band or any other quantity.
- They never appear as a light-to-dark (or dark-to-light) sequence. The blades, the
  wordmark's chips and the phone strip all use the mixed order of `--chip-1` to `--chip-5`.
- Bands are shown only as neutral ink chips (section 2). The macro photos are never sorted
  by tone either.

**Why the tone rule exists.** In India a shade card is tied to fairness-cream advertising,
which used shade cards to show skin moving from darker to lighter, with lighter presented as
better. A tone strip that runs light to dark, or tones tied to "more" or "less" of anything,
would echo that. A shade card can also suggest colour matching, which PureSkin doesn't do,
so no copy may suggest it measures, matches or scores skin tone.

**Risks still open.**
- The direction sits close to beauty marketing. The five named concerns and the mixed tone
  order are what keep it from reading as a foundation shade range.
- On desktop the fan's names are rotated up to 50°. The phone strip, and the list screen
  readers get ("The five scores in a Skin Profile"), are the plain versions.

**Reference sample.** `_design_samples/b-shade-card/index.html` (local only: the folder is
in `.git/info/exclude`, so a fresh clone won't have it). Its tinted, hatched blocks are
placeholders. The real build uses plain chip-colour blocks (section 5).

## 2. Tokens

The final values live in `:root` of `frontend/static/css/main.css`. Ratios use the WCAG 2
formula. The requirement is 4.5:1 for text and 3:1 for non-text, under WCAG 2.2 AA (see
`PRODUCT.md`).

| Token | Value | Role |
|---|---|---|
| `--counter` | `#eeeff0` | page ground |
| `--card` | `#ffffff` | cards, raised controls |
| `--ink` | `#191a1c` | text; the current band; the current nav item |
| `--ink-2` | `#55575c` | secondary text |
| `--band-off` | `#f0f0f1` | a band chip that isn't the current one (inside cards) |
| `--rule` | `#d9dadc` | decorative hairlines only, never a control's only edge |
| `--control` | `#7c7e84` | borders of inputs and outlined buttons |
| `--action` / `--action-hover` | `#3d261a` / `#2a1a12` | the one action colour (white text) |
| `--notice-bg` / `--notice-ink` / `--notice-rule` | `#fbf3e6` / `#5c4100` / `#e3cfa6` | notices (`.warning-box`) |
| `--error` | `#a1261b` | error text |
| `--chip-1` … `--chip-5` | `#b17a50` `#ebcfb4` `#5a3724` `#ddb48e` `#774a2f` | decoration only (the tone rule) |

| Pair | Ratio | Needed |
|---|---|---|
| ink on counter / card / band-off | 15.13 / 17.41 / 15.29 | 4.5 |
| ink-2 on counter / card / band-off | 6.28 / 7.23 / 6.35 | 4.5 |
| white on ink / action / action-hover | 17.41 / 14.09 / 16.73 | 4.5 |
| notice-ink on notice-bg | 8.62 | 4.5 |
| error on card / counter | 7.48 / 6.49 | 4.5 |
| ink on chip-4 (text selection) | 9.12 | 4.5 |
| control on card / counter | 4.06 / 3.53 | 3.0 (non-text) |
| action on counter (a button against the page) | 12.24 | 3.0 (non-text) |
| focus ring (3px ink, 3px offset) on counter / card | 15.13 / 17.41 | 3.0 (non-text) |
| rule on card | 1.40 | decorative only |

**Shape, space, depth and motion tokens:**
- `--radius` 6px and `--radius-card` 8px.
- `--gutter` 16px, or 32px from 900px wide.
- `--content-width` 1040px.
- `--lift`: `0 1px 2px rgb(0 0 0 / .08), 0 14px 28px -16px rgb(0 0 0 / .45)`.
- `--ease-out`: `cubic-bezier(0.16, 1, 0.3, 1)`.
- `--chip-strip`: the wordmark's five chips, drawn as a gradient.

**Light only.** Every page has `<meta name="color-scheme" content="light">`, and the CSS
sets `color-scheme: light`.

**Components already in `main.css`:**
- the wordmark (`.wordmark` and `.site-header__inner`: the text "PureSkin" lowercased by
  CSS, then the chips)
- the nav (one ink current item) and the "Skip to main content" link (`nav.js`)
- `.btn`, `.btn--secondary`, card slips with the rivet (`.card`), `.empty-state`, `.status`,
  `.warning-box`
- `.page-note` (no coloured edge) and `.market-badge`
- score strips: `ui.js` `scoreBars` draws one chip per band from
  `PureSkinBands.SCORE_BANDS`, each as wide as its range. No cutoff appears in CSS. The
  chips are white on the page ground and `--band-off` inside a card.
- `.sensitive-indicator`, `.skin-type-note`, `.media` (section 5), and a reduced-motion
  rule for every page

## 3. Type

**Archivo** only, self-hosted.
- **File:** `frontend/static/fonts/archivo/Archivo-Variable-latin.woff2` (92 KB), a Latin
  subset of the variable font with both axes kept: weight 100–900, width 62–125%.
- **Licence:** SIL OFL 1.1 in `OFL.txt` beside the font. No Reserved Font Name.
- **Records:** the source, the download date and the exact `pyftsubset` command are in
  `frontend/static/CREDITS.md`. fontTools and brotli are installed in `backend/.venv` only,
  never in a requirements file.
- **No italics:** only the upright style ships, and `font-synthesis: none` stops fake
  italics, so emphasis is by weight.
- **Preload:** pages that load `main.css` preload the font. On `/app` pages the preload
  `<link>` must come after `auth-guard.js`, because a test checks the guard comes before
  any `<link>`.
- **Write sizes as `font-size` declarations,** not inside the `font` shorthand. Impeccable's
  detector can't read `clamp()` in the shorthand and reports a flat hierarchy.

| Role | Weight / width | Size | Where |
|---|---|---|---|
| Landing headline | 850 / 112% | `clamp(2.4rem, 1.6rem + 2.4vw, 3.6rem)`, line-height 0.98, tracking −0.035em | `landing.css` (`.hero__title`; landing only) |
| Page title | 850 / 112% | `clamp(2rem, 1.6rem + 1.4vw, 2.75rem)`, line-height 1, −0.03em | `main.css` |
| Section heading | 800 / 112% | `clamp(1.6rem, 1.3rem + 1vw, 2.1rem)` | `landing.css` (`.landing-heading`); moves to `main.css` in Unit 4 |
| Card title (revised) | 800 / 112% | 1.5rem | `main.css` |
| Step heading (revised) | 800 / 106% | 1.35rem, line-height 1.15 | `landing.css` (`.step-heading`); moves to `main.css` in Unit 4 |
| Body / lede | 400 / 100% | 1.0625rem, line-height 1.55 / 1.12rem | body yes |
| Buttons, nav, labels | 600–700 / 100% | 0.95–1.1rem | yes |
| Band chips, codes | 600 / 87.5%, tabular figures | 0.8rem (0.75rem compact) | yes |

## 4. Motion and video

**Motion:**
- **The landing's one moment:** the deck fans open once after first paint (1.1 s,
  `--ease-out`, 55 ms between blades), with CSS only: the `fan-open` keyframes in
  `landing.css` run from upright to each blade's angle, with `backwards` fill and a delay of
  `--i` × 55 ms. No script is involved, so the deck opens without JavaScript and never
  flashes closed. Under `prefers-reduced-motion` the blades get `animation: none` and are
  open from the start.
- **Hover lift:** a pointer hover lifts one blade 16px along its own axis (0.35 s). Blades
  aren't focusable.
- **State changes:** 200 ms.
- **No scroll reveals,** and nothing loops except the V1 video.
- **Reduced motion:** `main.css` cuts every animation and transition to near zero.

**Video: V1 only, in the landing's "How a scan works" section.** It is the swatch of one
large sample card beside the three steps. It is not in the hero, because the fan opening is
the hero's one motion and a video inside a ~100px blade would be too small to read.
- `<video muted loop playsinline poster="…">`, with a WebM `<source>` first and then MP4.
- **No `autoplay` attribute.** `landing.js` calls `play()` only when reduced motion isn't
  set; under reduced motion the poster is all that shows.
- **A visible pause button** (WCAG 2.2.2): its label says what it will do ("Pause video" /
  "Play video"), its icon matches, and it has no `aria-pressed`. It is `hidden` until the
  video's first `playing` event, so no button shows while no file is supplied or under
  reduced motion.
- **`aria-hidden="true"` on the video:** the three steps beside it carry the meaning.
- 6–8 s seamless loop, no audio track, at most 2 MB per format.

## 5. Assets

Nothing has been supplied yet.

**Rules for every photo and video:**
- A real adult (18+) with written consent. The consent forms stay outside the repository,
  and nothing in it names the person.
- Natural daylight. No retouching, smoothing, filters, beauty mode or portrait mode.
- No products in the frame, no before/after pairs, no stock models.
- GPS and other metadata stripped on export.
- Each file gets a row in `frontend/static/CREDITS.md`: what it shows, who made it, the date
  and the licence or permission.

M1–M5 are five different people who together span light wheatish to deep brown skin. Keep
the macros gentle and in daylight: no ring light and no clinical look. Photos can be
exported with Pillow, which is in the backend's requirements. Encoding the video needs
ffmpeg or HandBrake, and neither is installed.

| Slot | Path(s) under `frontend/static/` | Shot | Aspect | Deliver | Ship | Used on |
|---|---|---|---|---|---|---|
| V1 | `media/v1-selfie-window.webm`, `media/v1-selfie-window.mp4`, poster `media/v1-selfie-window-poster.jpg` | A person taking a selfie by a window, small natural movement, tripod, plain wall, phone screen not visible | 4:5 | 1080p+ at 25 fps, 10–12 s raw | 6–8 s loop, 720×900, VP9 + H.264, ≤2 MB each; poster 720×900 JPEG ≤120 KB | Landing, "How a scan works" |
| M1 | `media/m1-acne.jpg` | Macro: a cheek or jawline with a few breakouts | 1:2 | ≥2000 px long side, area centred | 480×960 JPEG | Fan blade "Acne", phone strip, auth strip |
| M2 | `media/m2-redness.jpg` | Macro: a flushed cheek or the sides of the nose | 1:2 | as M1 | as M1 | Blade "Redness", strip, auth |
| M3 | `media/m3-wrinkles.jpg` | Macro: fine lines at the outer eye or forehead | 1:2 | as M1 | as M1 | Blade "Wrinkles", strip, auth |
| M4 | `media/m4-pigmentation.jpg` | Macro: dark spots or uneven patches on a cheek | 1:2 | as M1 | as M1 | Blade "Pigmentation", strip, auth |
| M5 | `media/m5-pores.jpg` | Macro: pores on the nose or inner cheek | 1:2 | as M1 | as M1 | Blade "Pores", strip, auth |
| G1–G3 (optional) | `media/g1-light-window.jpg`, `media/g2-light-backlit.jpg`, `media/g3-light-overhead.jpg` | One person: facing a window (good), backlit, harsh overhead light | 1:1 | ≥1600×1600 | 640×640 JPEG | Selfie guide on `/scan/` |

**How the slots are wired.** `main.css` has a `.media` block: a plain chip-colour block at a
set aspect ratio, with the photo as a background image:

```html
<span class="media" style="--media-src: url('/static/media/m1-acne.jpg'); --media-chip: var(--chip-1); --media-ratio: 1 / 2"></span>
```

- A missing file draws nothing, so the chip colour shows. A file dropped into
  `frontend/static/media/` appears with no code change.
- A `<video>` inside `.media` fills it, and the block's colour shows until the poster loads.
- Use root-absolute paths (`/static/...`) inside the custom property.
- The paths are listed in `CREDITS.md`. The pages that use them arrive in Units 2–4.

## 6. Remaining units

Each unit ends with a stop: screenshots at 360 px and 1440 px, the detector output, the file
list and full pytest counts. Then a separate commit authorisation. Existing contract tests
are never edited; new test files are added only when the user approves them. Test names
below are from `backend/app/tests/`.

**Unit 2: the landing page at `/`. Done.**
- **Files:** `frontend/pages/index.html`, `frontend/pages/landing.css` and
  `frontend/pages/landing.js` (video play/pause only; no URL literals). The fan opens with
  CSS only (section 4). The static mount at `/` serves the page with no backend change.
- **Sections:**
  - hero
  - How a scan works (V1 and three steps: selfie by camera or upload, a few questions, the
    Skin Report)
  - one example routine step with its real-format reason, labelled "Example"
  - what's kept and what isn't (only sentences the code backs)
  - what PureSkin isn't (estimates, not a diagnosis; the chat isn't medical advice; the
    catalog note word for word from `PRODUCT.md`)
  - a closing call to action
  - a footer with "PureSkin is a student project (MSc Data Science, NMIMS).", Log in and
    Sign up
- **Links:** "Start your free scan" → `/scan/`, Log in → `/auth/`, Sign up →
  `/auth/#signup`. No About or Pricing page.
- **New test (approved): `test_frontend_landing.py`.** Its checks:
  - no testimonials, user counts or percentages, and none of "dermatologist",
    "clinically", "proven", "verified" or before/after wording (text, `aria-label`, `alt`,
    `title` and the meta description, with entities decoded)
  - every link targets an existing route (`/scan/`, `/auth/`, `/auth/#signup`), and
    `landing.js` makes no links and never navigates
  - the video has its required attributes (muted, loop, playsinline, a poster, a WebM
    source then an MP4 one, no `autoplay`), and its pause button exists
  - `GET /` serves the landing page
  - the catalog note is word for word the Catalog page's
  - the example is labelled "Example", its caption states a made-up profile in bands, and
    the step is what the engine builds today for that profile on
    `backend/catalog/products.json`. **A catalog or rules change that alters the example
    fails this test, with a message naming each field that differs:** rebuild the routine
    for `EXAMPLE_PROFILE` and copy the step again, word for word, or pick another one.
- **Existing tests touched:**
  - `test_frontend_settings`: `test_every_page_names_any_website_it_loads_from_and_today_there_are_none`,
    `test_no_script_talks_to_another_website`
  - `test_frontend_contract`: `test_nothing_calls_the_removed_mock_endpoint`,
    `test_storage_keys_are_defined_only_in_scan_guard`, `test_no_answer_text_lives_in_the_frontend`

**Unit 3: auth.**
- **Files:** `auth/index.html` and `auth.css` move onto `main.css`; delete auth.css's own
  `:root` copies of the old tokens. Tabs become chips; add the wordmark and, on desktop, the
  closed M1–M5 strip beside the form. `auth.js` is unchanged, so `#signup` keeps working.
- **Tests touched:** `test_pages_after_the_photo_steps_drop_the_photo[pages/auth/index.html]`
  and the two outside-host tests.

**Unit 4: the scan funnel (selfie, questionnaire, report).**
- **Step rail:** three chips replace the "Step 1 of 3" label above headings, which the craft
  rules ban as an eyebrow. "Step n of 3" stays as visually hidden text.
- **Camera and upload side by side from the start:** a small `scan.js` change, since today
  the upload control is hidden until the camera fails. `PRODUCT.md` calls upload a
  first-class path.
- **Questionnaire:** options become chip rows; inputs, fieldsets, legends and `aria-live`
  are untouched.
- **Also:** restyle the dark camera box in `scan.css`. The optional G1–G3 guide goes here.
- **Heading styles:** move the section heading (`.landing-heading`) and the step heading
  (`.step-heading`) from `landing.css` to `main.css`, and delete them from `landing.css`.
- **The landing's selfie sentence:** once upload is a peer of the camera, update step 1 of
  "How a scan works" in `frontend/pages/index.html` ("Take one with your camera, or upload
  a photo if the camera isn't available.") so it says either way works.
- **The questionnaire's "Not sure" sentence:** `scan/questionnaire/index.html` says
  "\"Not sure\" is always fine", but the goal, sleep and stress questions don't offer it.
  Correct the sentence; don't add options. (No test reads that sentence today.)
- **Tests touched:**
  - the landing: all of `test_frontend_landing` (`index.html` changes)
  - questionnaire: `test_every_input_name_is_a_scorer_field`,
    `test_the_old_skin_type_question_is_gone`, `test_every_new_question_is_asked`,
    `test_radio_values_match_the_scorer_exactly`, `test_checkbox_values_match_the_scorer_exactly`,
    `test_text_fields_are_accepted_and_fit_the_limit`, `test_a_full_form_scores`,
    `test_goal_helper_text_says_it_only_chooses_between_suitable_products`
  - selfie and report: `test_selfie_page_states_the_privacy_line`,
    `test_report_has_no_sample_data_note`,
    `test_pages_after_the_photo_steps_drop_the_photo[pages/scan/report/index.html]`
  - funnel scripts: `test_funnel_calls_existing_endpoints`,
    `test_storage_keys_are_defined_only_in_scan_guard`, `test_frontend_logic_in_node` (`scan-api.js`)
- **Detector findings to clear:** the captured-photo `<img>` with no `src` until the script
  sets one, and the camera box with no inner padding.

**Unit 5a: Dashboard, Skin Profile, Progress.**
- **Files:** page CSS, plus the quick links in `dashboard.js`.
- **Tests touched:**
  - `test_frontend_contract`: `test_dashboard_and_profile_show_the_same_skin_details`,
    `test_dashboard_save_uses_the_shared_failure_policy`,
    `test_dashboard_saves_the_tags_and_tells_the_user_when_they_were_dropped`,
    `test_pages_after_the_photo_steps_drop_the_photo[pages/app/index.html]`
  - `test_frontend_profile.py` (Node render of `profile.js`)
  - all of `test_frontend_progress`: script order, no chart (and no `<svg>` in the Progress
    files), the endpoint, the two notes, the 0/1/2+ views, band cells, the accessible table
    (`.progress-table-wrap` keeps `overflow-x: auto`), text only, no improvement claims
- **Detector finding to clear:** the 4px coloured side border in `progress.css`.

**Unit 5b: Routine, Catalog, product detail.**
- **Files:** page CSS; class names only in the JS.
- **Tests touched:** `test_catalog_and_routine_pages_carry_the_list_notes_and_no_placeholder_wording`
  (exactly one `.page-note`, both lines, no "verified" or "spot-checked"),
  `test_catalog_and_routine_scripts_render_the_market_badge`,
  `test_routine_page_shows_reasons_and_detects_no_profile_by_message`,
  `test_routine_page_shows_why_and_alternatives_as_text_only`,
  `test_routine_page_says_when_current_products_are_not_considered`,
  `test_the_placeholder_note_style_is_gone_and_the_badge_is_styled`.

**Unit 5c: Settings hub, Account, Privacy.**
- **Files:** CSS and classes only.
- **Tests touched:** all of `test_frontend_settings`, including:
  - script order, `test_the_hub_reaches_privacy_and_account_in_one_click`
  - the Subscription item: text only, no link
  - text-only scripts, the endpoints, the download and the delete form
  - the export statements word for word, the student-project sentence
  - `test_the_settings_pages_claim_nothing_the_code_lacks`, which bans words including
    "secure" and "safe"
  - the token-lifetime, chat, logging and source-link sentences

**Unit 6: chat.**
- **Files:** `chat.css` and classes in the HTML; class names only in `chat.js`.
  `chat-stream.js` is untouched.
- **Tests touched:** `test_chat_page_carries_the_disclaimer_with_the_one_emergency_number`,
  `test_chat_page_loads_the_guard_first_and_its_scripts_in_order`,
  `test_chat_page_box_live_regions_and_keys`,
  `test_chat_page_shows_cautions_sources_and_safety_and_never_the_servers_detail`,
  `test_chat_history_is_the_reply_text_only_and_nothing_survives_the_page`,
  `test_chat_scripts_render_text_only_and_store_nothing`, `test_no_answer_text_lives_in_the_frontend`.
- **Detector finding to clear:** the 4px coloured side border in `chat.css`.

**In every unit 3–6:**
- Switch that page's input borders from `var(--border)` (a faint hairline) to `--control`.
- Replace its hard-coded colours with tokens (section 8).
- Stop using the temporary aliases (section 8).

**Unit 7: finish.** Its checklist:
1. **Token-alias check (a new test).** It fails if any of `--bg`, `--surface`, `--text`,
   `--muted`, `--border`, `--accent` or `--accent-soft` is still defined in `main.css`, or
   used through `var()` in any stylesheet, `auth.css` included. Then delete the alias block
   from `main.css`.
2. Impeccable's detector over all of `frontend/`: no findings left, or each one explained.
3. An accessibility pass: contrast (section 2), visible focus on every control, everything
   by keyboard, reduced motion, 360 px with no sideways page scroll.
4. Impeccable's finish review, then `DESIGN.md` and `.impeccable/design.json` written from
   the built pages by Impeccable's documenter.
5. `CLAUDE.md` and `PRODUCT.md` updated: fonts and media under `/static`, the credits file,
   this redesign marked done. The user updates the deadline line in CLAUDE.md themselves.
6. Full `pytest`, real counts reported.
7. Real-phone checks added to "Deferred verification" in CLAUDE.md if they can't be run.
8. **An SVG favicon made from the wordmark chips** (`--chip-1` to `--chip-5` in their mixed
   order, as in the wordmark: the tone rule applies), self-hosted under `/static` and linked
   from every page. Today every page requests `/favicon.ico` and gets a 404.

## 7. Contract tests: what never changes

From the user's brief, these stay exactly as they are and keep passing:
- questionnaire input names and values
- `bands.js` (`PureSkinBands` as a bare `const`, one band per line)
- the `ui.js` display helpers and their names
- `scan-api.js`, `chat-stream.js`, the storage keys (only in `scan-guard.js`), `auth-guard.js`
  and `scan-guard.js`
- `textContent` for anything user-supplied (never `innerHTML`)

No page loads anything from another website. Fonts, images and video are self-hosted under
`frontend/static/`. Copy promises nothing the code doesn't do: the scores are unvalidated
heuristics, not clinical; the catalog is not "verified"; the chat is not medical advice.

## 8. Temporary token aliases

`main.css` maps the old token names onto B's tokens, so pages not yet restyled keep working.
Each goes when the last stylesheet using it is restyled; Unit 7's check (section 6) enforces
that. Usage as of `96f2c87` (paths under `frontend/pages/`):

| Alias | Maps to | Still used in |
|---|---|---|
| `--bg` | `--counter` | `app/chat/chat.css`, `app/settings/settings.css`, `auth/auth.css` |
| `--surface` | `--card` | `app/catalog/catalog.css`, `app/chat/chat.css`, `app/dashboard.css`, `app/progress/progress.css`, `app/settings/settings.css`, `auth/auth.css`, `scan/questionnaire/questionnaire.css`, `scan/scan.css` |
| `--text` | `--ink` | `app/catalog/catalog.css`, `app/chat/chat.css`, `app/dashboard.css`, `app/routine/routine.css`, `app/settings/settings.css`, `auth/auth.css` |
| `--muted` | `--ink-2` | `app/catalog/catalog.css`, `app/chat/chat.css`, `app/dashboard.css`, `app/profile/profile.css`, `app/progress/progress.css`, `app/routine/routine.css`, `app/settings/settings.css`, `auth/auth.css`, `scan/questionnaire/questionnaire.css`, `scan/report/report.css`, `scan/scan.css` |
| `--border` | `--rule` | `app/catalog/catalog.css`, `app/chat/chat.css`, `app/dashboard.css`, `app/progress/progress.css`, `app/routine/routine.css`, `app/settings/settings.css`, `auth/auth.css`, `scan/questionnaire/questionnaire.css`, `scan/scan.css` |
| `--accent` | `--ink` | `app/catalog/catalog.css`, `app/dashboard.css`, `app/profile/profile.css`, `app/progress/progress.css`, `app/routine/routine.css`, `app/settings/settings.css`, `auth/auth.css`, `scan/questionnaire/questionnaire.css`, `scan/scan.css` |
| `--accent-soft` | `--band-off` | `app/chat/chat.css`, `app/profile/profile.css`, `app/progress/progress.css`, `app/routine/routine.css`, `scan/questionnaire/questionnaire.css`, `scan/report/report.css` |

`auth/auth.css` doesn't load `main.css` yet. Its own `:root` defines the old values
(`--bg`, `--surface`, `--text`, `--muted`, `--border`, `--accent`, `--accent-text`,
`--error`, `--radius`) in the old sage-green palette, until Unit 3.

**Hard-coded colours from the old palette** (amber notices, dark reds, the dark camera box),
to replace with tokens in their units:
- `app/chat/chat.css`: `#5c4100`, `#8a3a06`, `#8c1d18`, `#b54708`, `#f0d9a8`, `#fff6e5`
- `app/routine/routine.css`: `#5c4100`, `#f0d9a8`, `#fff6e5`
- `app/settings/settings.css`: `#8c1d18`, `#e3b3ae`
- `scan/questionnaire/questionnaire.css`: `#8c1d18`
- `scan/scan.css`: `#2a2f2c`, `#5c1612`, `#5c4100`, `#8c1d18`, `#c9cfcb`, `#f0d9a8`, `#fbeceb`, `#fff6e5`

## 9. Working rules

- **Per unit:** build, then stop with screenshots at 360 px and 1440 px, the detector output
  (`impeccable detect --json <changed files>`), the file list and full pytest counts. Commit
  only after the user's explicit authorisation, with the commits and subjects they name.
- **Commits:**
  - Stage by explicit path only, and show `git diff --cached --stat` before each commit.
  - Check that every modified or untracked file belongs to exactly one authorised commit;
    otherwise stop and ask.
  - Run a forbidden-path scan before each commit: `.env*`, `*.dump`, `backups/`,
    `catalog_staging/`, `image_analysis/{models,weights,datasets,samples}/`, `*.task`,
    `*.pt`, `*.pth`, `*.onnx`, `__pycache__/`, `*.pyc`, `.venv*/`, `verify_commit.sh`, image
    files outside `frontend/static/`, `_design_samples/`.
  - Never `--amend`, `--no-verify`, force, reset or push. End messages with the
    Co-Authored-By trailer the repository's commits use.
- **After a commit:**
  - Run the frontend contract files and the Node test on a `git archive` export of the
    commit. Load `.env` into the test process's environment only; the export has none.
  - Then run the full suite in the working tree. Before timing it, stop any background
    processes the session started (servers, headless browsers). Report real counts and the
    time.
- **Network:** nothing from impeccable.style, no image generation and no API calls. Google
  Fonts is allowed only in the throwaway `_design_samples/`. One-off downloads from an
  official source only when the user approves them (as for Archivo).
- **Screenshots without the dev database:** run a small local server, outside the repo, that:
  - serves `frontend/pages` and `/static`
  - replaces the `auth-guard.js` script tag with
    `window.PureSkinAuth = { getToken: () => "harness", logout() {} }`
  - adds a fixtures script after `api.js` that overrides `apiFetch` with example data
  - seeds `sessionStorage["pureskin_scan_result"]` for `/scan/report/`

  Headless Chrome won't lay a page out as narrow as 360px (its minimum window is wider),
  so capture 360 px inside 360px iframes, or (as in Unit 2) drive Chrome over the DevTools
  protocol and set `Emulation.setDeviceMetricsOverride` to 360 px. For a full-page capture,
  grow the viewport to the page's height and wait: `captureBeyondViewport` restarted the
  landing deck's animation, so it showed the deck closed. Iframes in one page share `sessionStorage`: the
  Dashboard saves and clears a stored scan, and `/scan/` clears it, so capture the Skin
  Report on its own. The first harness (`harness.py`) lived in a session scratch folder
  outside the repo, so a new session won't have it.
