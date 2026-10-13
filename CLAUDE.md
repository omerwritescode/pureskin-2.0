# CLAUDE.md

This file is auto-loaded by Claude Code at the start of every session in this repo.
It should stay short — the full spec lives in `docs/spec.md`; read that for feature
details, the sitemap, or NFRs. This file is for conventions and current state.

## Project

PureSkin — an AI-driven personalized skincare platform (MSc Data Science project).
Selfie + questionnaire → Skin Profile → adaptive routine, ingredient-conflict checks,
a generative before/after preview, and a Skin-Profile-grounded chatbot.

Full spec: `docs/spec.md`

## Hard constraints — do not deviate without being asked

- **Frontend is plain HTML, CSS, and vanilla JavaScript. No React, no Vue, no frontend
  framework.** If a library is genuinely needed (e.g. a charting library), load it via
  a `<script>` CDN tag, never a bundler/npm frontend dependency.
- **Backend is Python + FastAPI. Database is PostgreSQL, run locally via Docker.**
  These are final — don't substitute Node.js, Flask, or MongoDB.
- Every authenticated page must stay reachable within the sitemap's click-depth budget
  (see `docs/spec.md` §5) — don't add a page without also adding it to the persistent
  nav or deciding deliberately that it's a deeper detail page.
- Don't add a new top-level page without checking `docs/spec.md` §5 first — the sitemap
  is the source of truth for what pages exist and how they link.

## Build order

Follow the roadmap in `docs/spec.md` §8 in order — don't jump ahead to AI services
before auth, the DB schema, and the static frontend shell are working. Currently at:

- [x] 1. Project scaffold
- [x] 2. Database schema + migrations
- [x] 3. Auth end-to-end
- [x] 4. Static frontend shell (nav + empty pages)
- [x] 5. Onboarding funnel (mocked scoring)
- [x] 6. Core pages on real, rule-based data
- [ ] 7. AI services (one at a time)
  - [x] 7a. Image Analysis (`backend/app/services/image_analysis/`; standalone at
        `POST /api/services/image/analyze`): photo-quality checks + five heuristic
        scores, live. Skin-type classifier trained, but at chance on a leak-free split,
        so it is not served (`skin_type_prediction` is null; see the service README).
        Every photo is analysed at a canonical 720 px (since 7b-ii).
  - [x] 7b. Questionnaire/NLP + Skin Profile, wired into the scan funnel.
    - [x] 7b-i (backend). `services/questionnaire/` (rules + free-text lexicon, standalone
          at `POST /api/services/questionnaire/score`), `services/skin_profile/` (merge,
          score bands, `score_sources`), `POST /api/scan/analyze` (image + answers, in
          memory), migration db1f2fceaf09 (`is_sensitive`, `score_sources`; skin_type
          'sensitive' is gone). The image acne score is unreliable, so acne is
          questionnaire-led: capped at 60 without corroboration, floored at 61 with it.
    - [x] 7b-ii (funnel). 8-step questionnaire whose input names/values are the scorer's;
          each photo checked right after capture/upload (retake screen on a hard
          rejection); `/api/scan/analyze` at the end; the full result (scores, skin_type,
          is_sensitive, score_sources) saved at signup. Shared bands in
          `frontend/static/js/bands.js`, a Sensitive indicator and "(assumed)" skin type on
          the Skin Profile. `/api/scan/mock-analyze` removed. The legacy "sensitive"
          skin_type mapping in `api/profile.py` is kept on purpose (harmless).
  - [x] 7c. Recommendation Engine (rules first, ranker second)
    - [x] 7c-i (a). Shared ingredient normaliser and vocabulary (`services/ingredients/`);
          step 6 rules moved unchanged into `services/recommendation/` (pure functions);
          whole-token matching, proven behaviour-unchanged.
    - [x] 7c-i (b). Rule fixes (routine-2.0.0): High-band triggers; sensitivity as a
          modifier (strong actives, L-ascorbic acid and fragrance left out, mineral
          sunscreen first, substitutions); fixed concern priority; evening-only
          retinoids/AHAs; core fallbacks; class-level conflict rows; product `spf`,
          `texture`, `foaming`; every left-out product has a visible reason. The 24 seeded
          products were synthetic placeholders (retired in 7c-iii; now the tests' fixture).
    - [x] 7c-i (c). `skin_profiles.questionnaire_tags` (migration 440d5393300d): the user's
          current products and avoid list (duplicates, conflicts with actives in use, the
          avoid list; routine-2.1.0); tag-drop notices.
    - [x] 7c-ii. Content-based ranker (ingredient TF-IDF, recommendation-1.0.0) within
          rule-eligible sets: it only orders them (keyword tier, strong actives outside
          their step last, conflict-safe, score, rule order); `why` and up to 2
          alternatives per step; routine-2.2.0 (note wording; the sensitive acne
          substitution also fires when no benzoyl-peroxide product exists). Evaluation:
          `python -m app.services.recommendation.evaluate`; results on the real catalog
          since 7c-iii (recommendation-1.0.1).
    - [x] 7c-iii. A catalog of real products for the thin slots; retire the placeholders.
      - [x] Unit 1: `backend/catalog/products.json` (37 products; lists copied from the cited
            pages and checked by script as exact text: sourced from the cited pages;
            spot-checked by a person: not yet), its loader (`services/catalog/`,
            catalog-1.0.0), page-text cleaning (`services/ingredients/clean.py`),
            ingredients-1.2.0 (additions only), routine-2.3.0 (the wrinkle step takes any
            retinoid; sensitive fragrance reasons name the kind of ingredient). No DB
            change yet.
      - [x] Unit 2: migration 1bb224b28584 (`products.source_url`, `market`,
            `fetch_status`, `date_checked`, `original_name`: set together or not at all);
            `seed.py` seeds `products.json` through the loader, making `products` exactly the
            catalog (it pruned the 24 placeholders); the placeholders are now the test-only
            fixture `app/tests/catalog_fixture.py` (test DB, digests, routine snapshots;
            `seed.py` never imports it); safety invariants and a snapshot on the real catalog
            (`recommendation/tests/test_real_catalog.py`, about a minute;
            machine-dependent). Backup
            `backups/pureskin_dev_20261007_before_7c-iii.dump`.
      - [x] Unit 2a: `find_conflict` checks each conflict row against the products' keys
            (results identical, proven against the old implementation; ~10x faster).
      - [x] Unit 3: evaluation on the real catalog (recommendation-1.0.1: the placeholder
            flag and banner removed; README results regenerated), the "Global ingredient
            list" badge and the list notes on the catalog and routine pages, the API's
            provenance fields and `config_versions["catalog"]`, spec addendum items 7-9.
  - [ ] 7d. Conversational AI
  - [ ] 7e. Generative Visualizer
- [ ] 8. Secondary features, testing, deploy

(Check off steps here as they're completed, so a new session knows where the project stands.)

## Folder structure

```
/frontend    plain HTML/CSS/JS, one folder per page/section
/backend     API service(s) — one folder per microservice once split out
/docs        spec.md and any other project documentation
.env.example template for required environment variables (never commit .env)
```

## Conventions

- Database migrations only — never hand-edit the schema directly.
- New environment variables go in `.env.example` (with a placeholder value) whenever
  they're added to `.env`, so the repo always documents what's required.
- Each AI service (Image Analysis, Questionnaire/NLP, Recommendation Engine,
  Conversational AI, Generative Visualizer) should be buildable and testable on its own
  before being wired into the frontend, per `docs/spec.md` §8 step 7.
- Secrets (API keys, DB credentials) are never committed — `.env` is gitignored.
- A 422 never echoes submitted input (passwords, emails, free text, photos): the global
  RequestValidationError handler in `main.py` strips it, and endpoints that parse their
  own body use `app/api/request_body.py`. Never log request bodies or `exc.errors()`.
- Rules, thresholds and weights live in each service's versioned config file
  (`*_config.py`), never as numbers in code. Bump the version string when a result can change.
- Bump `CONFIG_VERSION` (questionnaire_config.py), `MERGE_CONFIG_VERSION`
  (skin_profile_config.py), `INGREDIENT_CONFIG_VERSION` (ingredient_config.py, now
  ingredients-1.2.0), `ROUTINE_CONFIG_VERSION` (routine_config.py, now routine-2.3.0),
  `RECOMMENDATION_CONFIG_VERSION` (recommendation_config.py, now recommendation-1.0.1) or
  `CATALOG_CONFIG_VERSION` (catalog_config.py, now catalog-1.0.0) whenever a value there
  changes. `app/tests/test_config_versions.py` fingerprints the values and fails on any
  change without a bump; record the new version's fingerprint there (a version not yet
  committed may have its fingerprint updated in place). `backend/catalog/products.json`
  works the same way: bump its `version` and record its fingerprint in
  `app/services/catalog/tests/test_loader.py`.
- Catalog (7c-iii): products come only from `backend/catalog/products.json`. A row's
  `ingredients_verbatim` is never edited (its hash is checked); cleaning happens at load
  time, by rules in `ingredient_config.py` and reviewed per-row directives. Any problem in
  any row stops the whole load. A failed `expected_constraints` value is recorded in
  `known_mismatches` and reported, never fixed or weakened. Describe the lists as
  "sourced from the cited pages; spot-checked by a person: not yet" (each was copied from
  its cited page and checked by script as exact text against the staging copy); never
  with a word that claims a person checked them.
- Ingredients (7c): every ingredient decision goes through `services/ingredients/` (one
  canonical token per ingredient, never substrings) and the one membership function,
  `memberships(items, strict=...)`. AMBIGUOUS_MEMBERS (lactic/malic/tartaric acid, sodium
  salicylate, retinyl esters) count toward their class only at or before the first
  PRESERVATIVES entry (a proxy for the ~1% line); NEUTRAL tokens are known and class-less,
  never a cutoff. The avoid list uses strict membership; conflicts, strong actives and
  session rules use the cutoff. Unknown or invalid ingredient names fail closed (never
  recommended); review them with `python -m app.services.ingredients.review`, and never
  write a product's ingredient list from memory.
- Conflict rows may name a whole class as `class:<name>` (e.g. `class:retinoid`).
  Ingredient names can never contain `:` (the normaliser rejects it; DB CHECKs keep the
  two apart). `seed.py` makes the conflict table exactly `CONFLICTS`, printing what it
  inserts and prunes.
- `skin_profiles.questionnaire_tags` holds a fixed vocabulary only (never raw text, skin
  conditions or lifestyle tags), validated by `QuestionnaireTags`. Missing or invalid tags
  never fail a save: the profile is stored with NULL tags and the response says so. Never
  log tags. The step 8 data export must include them.
- The questionnaire page's input names/values ARE the scorer's field names/values, and the
  score-band cutoffs exist only in `skin_profile_config.py` and `frontend/static/js/bands.js`.
  `app/tests/test_frontend_contract.py` checks both, so keep them in sync.
- Chat (7d, in progress): a local Ollama on loopback only, and only a model pinned to its
  full digest in `chat_config.ALLOWED_MODELS` (never a cloud tag). Otherwise the chat is a
  503 whose reason `GET /api/chat/status` names: `non_loopback_host`, `cloud_tag`,
  `unpinned_model`, `unreachable`, `missing_model` or `moved_tag`. Red flags never reach the
  model. Never log chat text, chunk ids, red-flag groups or the user (one metadata line per
  request). Details: `backend/app/services/chat/README.md`.

## Commands

Run from the repo root unless noted. `.env` lives at the repo root (copy `.env.example`).

```bash
docker compose up -d                         # start PostgreSQL 16 (localhost:5432)
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows; use .venv/bin/activate elsewhere
pip install -r requirements.txt
uvicorn app.main:app --reload                # API on http://localhost:8000, GET /health
alembic revision -m "msg"                    # new migration (add --autogenerate once models exist)
alembic upgrade head                         # apply migrations
python seed.py                               # products = backend/catalog/products.json (prunes the rest) + conflicts (idempotent)
pip install -r requirements-dev.txt          # + pytest, httpx2 (tests)
python -m app.services.image_analysis.download_models   # MediaPipe face model (gitignored, once)
python -m pytest                             # everything (DB tests need Docker; they use throwaway DBs)
python -m pytest app/services/image_analysis # image analysis tests
python -m pytest app/services/questionnaire app/services/skin_profile   # 7b-i services
python -m app.services.skin_profile.merge_cases          # merge-case table (report)
python -m app.services.skin_profile.time_analyze         # /api/scan/analyze timing (needs samples/)
python -m app.services.image_analysis.check_funnel_resolution   # one photo at several upload sizes
python -m app.services.ingredients.review    # ingredient review of products.json: unknown tokens, cutoff dismissals
python -m app.services.ingredients.review --staging ../catalog_staging   # ... on every staging row
python -m app.services.catalog               # load products.json and print the load report
python -m app.services.catalog.promote --staging ../catalog_staging   # exact-text check vs staging
python -m app.services.recommendation.evaluate   # ranker evaluation report (~12 min here, machine-dependent; --no-timing)
python -m app.services.recommendation.evaluate --update-readme   # rewrite the README's results
UPDATE_SNAPSHOTS=1 python -m pytest app/tests # re-record routine behaviour snapshots (check the diff!)
pip install -r requirements-train.txt        # GPU training only: CUDA 12.8 torch (~2.5 GB)
python -m app.services.image_analysis.train_skin_type   # train the skin-type classifier
```

Frontend pages are served by the same FastAPI app: http://localhost:8000/scan/, /auth/, /app/.

**Windows gotcha:** `--reload` can silently hang when the server isn't attached to a real
console. It logs "Reloading...", but the old worker keeps serving the old code (new routes
404/405). If a change doesn't show up, stop the server and start it again.

## Deferred verification

Checks a person still has to do. Until they are done, the catalog's ingredient lists are
"sourced from the cited pages; spot-checked by a person: not yet".

- **Spot-check the catalog pages against the CSVs**: open each `source_url` and compare its
  list with `catalog_staging/` and `products.json`. None of the 50 rows has been checked by
  a person yet.
- **B29** (Anua azelaic serum): the page credits blue tansy oil, which its printed list
  doesn't have; the list has betaine salicylate (a BHA), so sensitive skin doesn't get it.
- **B17** (Neutrogena Sheer Zinc): the list is the US Drug Facts formula; the product the
  sheet's retailer link sells in India is a different one.
- **B06** (Dermatouch salicylic face wash): the page's "Key Actives" name niacinamide and a
  willowherb extract that its printed list doesn't have.
- **Left neutral, to confirm**: B37's cinnamomum cassia bark extract and B17's phenethyl
  alcohol (neither is in EU Annex III; cassia *leaf oil* is).
- **B34 replacement**: B34 fails `anhydrous_oil` (its first ingredient is gold flakes), so
  the dry-skin facial-oil step has no product. A replacement facial oil is needed.
- **A second centella product** for the sensitive morning serum step.
- **A retinol serum**: the evening wrinkle step has no product (A04, a cream, was held back).
- **B14** (Olay Regenerist): its list (the brand's India page) includes butylphenyl
  methylpropional (Lilial), which is prohibited in the EU (Regulation 1223/2009 Annex II,
  entry 1666).
- **B31** is the only tranexamic-acid option, and it lists mandelic acid (an AHA) and
  salicylic acid (a BHA): sensitive skin gets no tranexamic step.
- **Polish: the sensitive fragrance reason shows canonical names** ("It contains
  melaleuca alternifolia leaf oil, an essential oil"), not the name as printed.
- **Polish: B14's reason "It lists fragrance (declared fragrance)"** repeats itself.
- **`config_versions["catalog"]` is the shipped file's version**, not the database's: the
  routine reports the version of `products.json` in the code, which the DB matches only
  after `python seed.py` (the DB stores no version).
- **After the catalog additions above**: re-run the evaluation (`--update-readme`) and fix
  its duplicate "Catalog:" header line then.
- **The real-phone scan** and **the manual checklist** (still outstanding).
