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
  - [ ] 7c. Recommendation Engine
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
- Bump `CONFIG_VERSION` (questionnaire_config.py) or `MERGE_CONFIG_VERSION`
  (skin_profile_config.py) whenever a weight, threshold or rule there changes: profiles
  store these versions. `app/tests/test_config_versions.py` fingerprints the values and
  fails on any change without a bump; record the new version's fingerprint there.
- The questionnaire page's input names/values ARE the scorer's field names/values, and the
  score-band cutoffs exist only in `skin_profile_config.py` and `frontend/static/js/bands.js`.
  `app/tests/test_frontend_contract.py` checks both, so keep them in sync.

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
python seed.py                               # load/refresh product catalog + ingredient conflicts (idempotent)
pip install -r requirements-dev.txt          # + pytest, httpx2 (tests)
python -m app.services.image_analysis.download_models   # MediaPipe face model (gitignored, once)
python -m pytest                             # everything (DB tests need Docker; they use throwaway DBs)
python -m pytest app/services/image_analysis # image analysis tests
python -m pytest app/services/questionnaire app/services/skin_profile   # 7b-i services
python -m app.services.skin_profile.merge_cases          # merge-case table (report)
python -m app.services.skin_profile.time_analyze         # /api/scan/analyze timing (needs samples/)
python -m app.services.image_analysis.check_funnel_resolution   # one photo at several upload sizes
python -m app.services.ingredients.review    # ingredient review: unknown tokens, cutoff dismissals
UPDATE_SNAPSHOTS=1 python -m pytest app/tests # re-record routine behaviour snapshots (check the diff!)
pip install -r requirements-train.txt        # GPU training only: CUDA 12.8 torch (~2.5 GB)
python -m app.services.image_analysis.train_skin_type   # train the skin-type classifier
```

Frontend pages are served by the same FastAPI app: http://localhost:8000/scan/, /auth/, /app/.

**Windows gotcha:** `--reload` can silently hang when the server isn't attached to a real
console. It logs "Reloading...", but the old worker keeps serving the old code (new routes
404/405). If a change doesn't show up, stop the server and start it again.
