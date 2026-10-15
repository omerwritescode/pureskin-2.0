# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are adults (18+).

Primary (their needs win when groups conflict):

- **Skincare beginners**: young adults in India who want a sensible routine without knowing
  ingredients. They need plain words, a guided path and reassurance.
- **Privacy-sensitive users**: people who want skin analysis without giving up their photo or
  their data. They need to see what is kept and what isn't, at the point where it matters.

Secondary (`docs/spec.md` §1): ingredient-conscious users avoiding conflicting actives, and
skincare-conscious millennials/Gen Z generally. The NMIMS evaluation panel sees the product in a
live demo (see Operating Context).

## Product Purpose

A selfie and a short questionnaire become a **Skin Profile**: five 1-100 scores (acne, redness,
wrinkles, pigmentation, pore visibility) shown as Low / Moderate / High, plus a skin type and a
sensitivity flag. The profile drives an AM/PM **Routine** built from a catalog of real products,
with ingredient-conflict checks and a reason for every product left out, and a **Chat** that
answers skincare questions from a small knowledge base and the user's own profile. It replaces
guesswork and generic advice with a routine built for this person.

MSc Data Science project, NMIMS NSoMASA, Mumbai. The spec's evaluation plan (§9) names usability
sessions and a trust score above 4/5 as product measures.

## Positioning

Core claims (confirmed):

- **Privacy-first.** The photo is analysed in memory and never stored; the chat model runs on the
  same machine (no cloud model); data export and account deletion are in one place.
- **Ingredient safety.** Conflicting actives never share a session, sensitive skin gets no strong
  actives or fragrance, the user's avoid list and current products are respected, and every
  left-out product says why.
- **Personalised by AI.** A selfie plus a questionnaire gives a routine built for this person.

The AI claim stays within what the system is (see Capabilities and Constraints): the image scores
are unvalidated heuristics from classical computer vision, skin type and sensitivity come from the
questionnaire, the routine is rule-based, and the ranker uses hand-set weights, not training.

## Operating Context

- Two paths in: a pre-account scan funnel (`/scan` selfie, `/scan/questionnaire`,
  `/scan/report`, then `/auth`) and the logged-in app with a persistent nav (Dashboard, Skin
  Profile, Routine, Catalog, Chat, Progress, Settings). Sitemap and click-depth budget:
  `docs/spec.md` §5.
- Mostly used on phones; the funnel takes the selfie with the camera or an upload, and checks
  each photo straight away (a retake screen for an unusable one).
- Photo upload is a first-class path, not an error state: a phone that opens the app over plain
  HTTP on the LAN gets no camera, so upload is how it scans. Design it as a peer of the camera.
- Demoed live on a laptop running everything locally: FastAPI serves the pages and the API,
  PostgreSQL runs in Docker, the chat model runs through Ollama. Desktop has to look right too.
- A chat answer arrives whole once the model has finished (several seconds), not word by word.

## Capabilities and Constraints

- Frontend is plain HTML, CSS and vanilla JavaScript: no framework, no bundler.
- No page loads files from another website (scripts, stylesheets, fonts, images, frames), and
  none has advertising or analytics. The Privacy page states this and
  `backend/app/tests/test_frontend_settings.py` enforces it, so any font or library is served
  from `/static`.
- English only; no translation planned.
- Honest wording is enforced across the product: scores are unvalidated heuristics and
  self-reports, not clinical assessments; the chat is not medical advice. No wording may claim
  that a person or a dermatologist checked something.
- Catalog wording, exactly as the Catalog and Routine pages show it today (the note at the top
  of both pages):

  > Ingredient lists are copied from brand pages and may differ by market or batch.
  > **Global ingredient list:** the list comes from the brand's non-India website; the version
  > sold in India may differ.

  13 of the 37 products carry the badge "Global ingredient list" (`frontend/static/js/ui.js`).
- Score-band cutoffs live only in `frontend/static/js/bands.js` and `skin_profile_config.py`.
- Chat page: a reply appears only whole, everything is set as text, nothing is stored in the
  browser, and the emergency number (India's 112) comes only from `chat_config.EMERGENCY_NUMBER`.
- Light theme only. Every page declares `<meta name="color-scheme" content="light">` and
  `color-scheme: light` in CSS, so browsers don't apply their own dark mode.
- Public pages: the landing page at `/`, About at `/about/` and Contact at `/contact/` (plain
  contact details, no form).
- Not built: the Pricing page, subscription and checkout, notifications, the
  generative before/after preview (roadmap step 7e, pending), the scan detail page, and
  on-device analysis.
- Terms in use: Skin Profile, Skin Report (the pre-signup result), Routine (AM and PM steps),
  Catalog, the bands Low / Moderate / High, the "Sensitive" indicator, an "(assumed)" skin type.

## Brand Commitments

- Name: PureSkin. No logo exists; the redesign will create an original wordmark. No other brand
  assets exist yet.
- Voice: calm and reassuring for beginners; never clinical, never salesy. As shipped it is plain,
  short sentences that say exactly what is and isn't true (the Privacy page, the score notes, the
  reasons on the Routine page).

## Imagery

- A range of Indian skin tones, showing real, unretouched skin.
- Nothing that implies a result: no before/after pairs, no flawless "after" skin.
- Team-owned photos and video of people who agreed to appear, including close-ups of a product
  being applied to skin, are allowed on the landing page, About, Contact, Dashboard, Skin
  Profile, Routine, Catalog and Settings. No packaging, brand, logo or on-screen text may be
  visible, and no shot may suggest a result.
- Stock photos only as listed here: two photos from Canva's library, each a close-up of a cream
  being applied to a cheek, used with Canva's written permission by email (15 October 2026), on
  condition that no changes are made to the images. They are served byte for byte (no crop,
  resize, blur, wash, re-export or metadata stripping), as the photo backgrounds and the About and
  Contact header band (`docs/redesign.md` §5). Whether they were retouched isn't known. No other
  stock models posing with products.
- One licensed film: Dove (Unilever), "Your skin. Our planet.", used with written permission for
  this project (granted 15 October 2026 by email; academic project only; the emails are kept
  outside the repository). The first permission was for use as is; a second email the same day
  cleared cropping and editing it as the team likes. The landing page's first screen plays the
  whole film, start to end, cropped to a strip (the crops are in the credits file): every shot,
  its captions (some cut on phones and tablets) and its closing card with Dove's logo; the
  original file isn't served. Below it the page says "Video: Dove, used with permission.
  PureSkin isn't affiliated with Dove.", and no PureSkin wording may suggest that Dove endorses
  or partners with PureSkin.
- Photo backgrounds sit behind solid cards. Only large ink text or an ink link sits on a photo,
  and readability comes only from CSS layers over the image (overlays of the page ground) and the
  cards, never from changing the file or a CSS filter on it: ink measures at least 4.5:1 at the
  darkest point it sits over.
- Every image and video is self-hosted (served from `/static`, like everything else), and its
  source and licence or permission are recorded in a credits file, never as "own work" unless
  the team made it.

## Evidence on Hand

- `backend/catalog/products.json`: 37 real products, each with its source URL, market and the
  date it was checked.
- 24 knowledge-base notes for the chat, written from public health pages (mostly MedlinePlus and
  the NIH) and the app's own docs.
- Absent, and never to be fabricated: testimonials, user counts or usage numbers, any accuracy or
  dermatologist validation for the scores (the skin-type classifier scored at chance and is not
  served), before/after photos, and pricing.

## Product Principles

1. **Beginners first.** Plain words and one clear next step; never assume the user knows what an
   ingredient is.
2. **Show the privacy, don't just promise it.** Say what is kept and what isn't where it matters:
   taking the photo, saving a scan, asking the chat.
3. **Safety before preference.** The rules decide what is eligible and ranking only orders it; a
   product left out always says why.
4. **Personal, not clinical.** The profile is about this person, worded as estimates from their
   photo and answers, never as a diagnosis.
5. **Phone first, demo-ready.** Every page works on a phone and reads well on a laptop screen.

## Accessibility & Inclusion

- `docs/spec.md` §6: mobile-first and responsive, WCAG-aligned, guided onboarding.
- Requirement: WCAG 2.2 AA. In particular: text and UI contrast, a visible focus indicator on
  every interactive element, everything operable by keyboard, and all motion respects
  `prefers-reduced-motion`.
- The spec's fairness requirement covers diverse skin tones (§6).
