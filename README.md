# PureSkin

AI-assisted personalised skincare platform: a selfie and a short questionnaire become a
structured Skin Profile, which drives a rule-based AM/PM routine with ingredient-conflict
checks. A chat answers skincare questions from a small knowledge base and the user's own
profile, with a local model. A generative "4 weeks from now" preview is planned.

MSc Data Science project, NMIMS NSOMASA, Mumbai.

> **Status:** in development. See [Build status](#build-status) for where things stand, and
> [Deviations from the original spec](#deviations-from-the-original-spec) for what differs
> from [`docs/spec.md`](docs/spec.md).

## What it does

**Implemented:**

- **Skin Profile from a selfie + questionnaire.** Five 1-100 scores (acne, redness,
  wrinkles, pigmentation, pore visibility) shown as Low / Moderate / High, plus skin type
  and sensitivity. The photo is checked right after it's taken; an unusable one (too dim,
  uneven light, no face...) gets a retake screen with tips. The scores are unvalidated
  heuristics and self-reports, not clinical assessments.
- **Routine.** A rule-based AM/PM routine built from the latest Skin Profile, using
  products in the catalog. It checks for conflicting ingredients (e.g. retinoids +
  benzoyl peroxide) between the products in each session, leaves strong actives and
  fragrance out for sensitive skin, takes the user's current products and avoided
  ingredients into account, and shows why any product was left out. A content-based
  ranker (hand-set weights, not ML-trained) orders each step's eligible products, with a
  "why" and up to two alternatives.
- **Product catalog.** Searchable and filterable by category: 37 real products
  (`backend/catalog/products.json`). Their ingredient lists are sourced from the cited
  pages; spot-checked by a person: not yet. 13 lists come from a brand's non-India
  website and are labelled "Global ingredient list" in the app. It is not a complete
  market; some routine steps still have no product (see the
  [recommendation README](backend/app/services/recommendation/README.md)).
- **Chat.** A local LLM with retrieval (RAG). Questions are answered from 24 short notes,
  written for PureSkin from public health pages (mostly US: MedlinePlus and the NIH) and the
  app's own docs, and from the user's Skin Profile and routine. The model is open-weights
  (qwen3.5:4b through Ollama, on the same machine; no cloud model).
  - Messages with red flags (such as a severe allergic reaction or thoughts of self-harm) get
    fixed, sourced safety replies before any model call.
  - Every sentence of an answer is checked before it is released, and the answer arrives
    whole, once the model has finished, not word by word.
  - Questions the notes don't cover often, but not always, get a fixed "I don't know" (12 of
    22 such test questions did); the model sometimes answers from general knowledge, and
    sometimes wrongly.
  - It is not a clinical tool, and its answers are not medical advice. Nothing typed is
    stored.

  See the [chat README](backend/app/services/chat/README.md).
- **Accounts.** Sign up and log in. The Dashboard and Skin Profile pages show the latest
  scan.

**Planned, not implemented yet:**

- A conflict check for a single scanned or looked-up product. The product page says
  "coming soon".
- A generative "4 weeks from now" preview (7e).
- Progress tracking, a privacy dashboard, notifications and subscriptions (step 8). The
  progress and settings pages exist only as empty shells. **The step 8 data export
  must include each Skin Profile's `questionnaire_tags`** (the current products, avoid
  list and goal saved since 7c-i c); they are already deleted with the user.

Full feature list, sitemap, architecture and NFRs (the original target):
[`docs/spec.md`](docs/spec.md).

## Tech stack

What is in the repo today:

- **Frontend:** plain HTML, CSS and vanilla JavaScript. No framework and no external
  libraries.
- **Backend:** Python 3.14, FastAPI, SQLAlchemy, Alembic. One FastAPI app; each AI
  capability is its own service package under `backend/app/services/`, buildable and
  testable on its own.
- **Database:** PostgreSQL 16 in Docker (`docker-compose.yml`). **Images are analysed in
  memory and never stored:** there is no object storage.
- **Image analysis:** MediaPipe face landmarks + classical computer-vision heuristics
  (OpenCV, NumPy). An EfficientNet-B0 skin-type classifier (PyTorch) was trained but is
  not served, because it scored at chance on a leak-free split. See
  [the service README](backend/app/services/image_analysis/README.md).
- **Questionnaire:** a rule-based scorer with a small lexicon extractor for the free-text
  answers. No ML classifier.
- **Skin Profile:** a documented, rule-based merge of the two.
- **Recommendations:** documented rules decide which products each step may use; a
  content-based ranker orders them (IDF × rank-decay weighting over rule-eligible sets; hand-set weights, not
  ML-trained). The product catalog is `backend/catalog/products.json`, loaded through a
  checked loader (every ingredient name reviewed, provenance required).
- **Auth:** JWT (python-jose), passwords hashed with bcrypt (passlib). No OAuth or social
  login.
- **Chat:** a local LLM, qwen3.5:4b (Apache-2.0), run by Ollama on the same machine and pinned
  to its digest; hand-written BM25 retrieval over a 24-note knowledge base (RAG); a
  rule-based red-flag router and an output gate. The page reads the answer as NDJSON events.

**Planned:**
- **Visual preview (7e):** Stable Diffusion 1.5 img2img.

It is not in the repo yet.

**Not implemented:**
- **MLOps and monitoring:** MLflow/Kubeflow, Kubernetes, Prometheus/Grafana.
- **Microservices:** splitting the services into separately deployed microservices.
- **Containers:** the app itself isn't containerised; Docker runs PostgreSQL only.

[`docs/spec.md`](docs/spec.md) §7 lists the original target stack; its addendum records
what changed.

## Project structure

```
/frontend    plain HTML/CSS/JS, one folder per page/section
/backend     API service(s) — one folder per microservice once split out
/docs        spec.md and other project documentation
.env.example template for required environment variables (never commit .env)
CLAUDE.md    context and conventions for Claude Code sessions in this repo
```

## Getting started

Prerequisites:
- Python 3.14 (what the project is developed and tested on; other versions are untested)
- Docker (runs the local PostgreSQL 16 instance)

Run these in order, from the repo root unless noted:

```bash
git clone <repo-url>
cd <repo-folder>

# 1. Configuration. Then edit .env: set POSTGRES_PASSWORD (and the same password
#    inside DATABASE_URL) and SECRET_KEY (the file says how to generate one).
cp .env.example .env                  # PowerShell: Copy-Item .env.example .env

# 2. PostgreSQL 16 on localhost:5432 (container pureskin-db)
docker compose up -d

# 3. Python environment and dependencies
cd backend
python -m venv .venv
.venv/Scripts/activate                # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt       # or requirements-dev.txt to also run the tests

# 4. Face landmark model for the Image Analysis service (3.7 MB, checksum-verified, once)
python -m app.services.image_analysis.download_models

# 5. Database schema, then the product catalog and ingredient-conflict rules
alembic upgrade head
python seed.py

# 6. Start the API, which also serves the frontend
uvicorn app.main:app --reload         # http://localhost:8000: /scan/, /auth/, /app/, GET /health
```

On Windows, `--reload` can hang silently when the server isn't attached to a real
console: if a code change doesn't show up, stop the server and start it again.

**Optional, 7. The chat's local model.** The chat (`/app/chat`) runs an open-weights model,
qwen3.5:4b (Apache-2.0), through [Ollama](https://ollama.com) on the same machine; without
it, the chat answers "unavailable" (HTTP 503), except for its fixed safety replies, and nothing
else changes.
1. Install Ollama (Windows: the installer from ollama.com; developed on 0.40.2).
2. Keep it local-only: set the user environment variable `OLLAMA_NO_CLOUD=1`, then restart
   Ollama (its log then shows `Ollama cloud disabled: true`).
3. `ollama pull qwen3.5:4b-q4_K_M` (3.3 GB). The tag is pinned to its digest in
   `ALLOWED_MODELS` (`backend/app/services/chat/chat_config.py`); a tag whose local digest
   differs is refused.
4. In `.env`, set `CHAT_MODEL=qwen3.5:4b-q4_K_M` (as `.env.example` has it); set `OLLAMA_HOST`
   only if Ollama isn't on `http://127.0.0.1:11434` (it must be a loopback address). Restart
   the API: its log says `Chat: available (...)` or why not, and `GET /api/chat/status`
   says the same.
5. Warm it up before a demo: ask the chat one question. The first answer after a model is
   pulled or loaded can take longer than the 60 s timeout and fail (the page then says the
   model may still have been starting up: ask again); `ollama ps` should then show `100% GPU`.

**Tests** (from `backend/`, after `pip install -r requirements-dev.txt`):
`python -m pytest`. The database tests need Docker running; they create and drop their
own throwaway databases and never touch the one in `.env`. Tests that need real selfies
are skipped until you add photos (see below).

**Not in the repo** (gitignored, never committed):
- `.env`: your local secrets. `.env.example` is the template.
- The MediaPipe face model, `backend/app/services/image_analysis/models/`: fetched by
  step 4 above.
- Training datasets (`image_analysis/datasets/`) and trained classifier weights
  (`image_analysis/weights/`). The skin-type classifier is trained but not served (it
  performs at chance), so the app runs without them. See
  `backend/app/services/image_analysis/README.md`.
- Sample photos for the photo-based tests and dev tools (`image_analysis/samples/`): add
  your own, as described in that README.
- Database dumps (`backups/`).

**Optional, GPU training only:** `pip install -r requirements-train.txt` (CUDA 12.8
PyTorch, about 2.5 GB), then `python -m app.services.image_analysis.train_skin_type`.
Not needed to run the app.

## Build status

Tracking against the roadmap in [`docs/spec.md`](docs/spec.md) §8:

- [x] 1. Project scaffold
- [x] 2. Database schema + migrations
- [x] 3. Auth end-to-end
- [x] 4. Static frontend shell (nav + empty pages)
- [x] 5. Onboarding funnel (mocked scoring)
- [x] 6. Core pages on real, rule-based data
- [ ] 7. AI services (one at a time)
  - [x] 7a. Image Analysis: photo-quality checks + five heuristic scores (backend)
  - [x] 7b. Questionnaire/NLP + Skin Profile, wired into the scan funnel
    - [x] 7b-i. Questionnaire scorer, Skin Profile merge, schema (backend)
    - [x] 7b-ii. Funnel: new questions, photo check, real analysis, bands (frontend)
  - [x] 7c. Recommendation Engine
    - [x] 7c-i (a). Shared ingredient normaliser; routine matching on whole tokens
    - [x] 7c-i (b). Rule fixes, product format fields, class-level conflicts, visible reasons
    - [x] 7c-i (c). The user's current products and avoid list (questionnaire tags)
    - [x] 7c-ii. Content-based ranker, explanations, evaluation
    - [x] 7c-iii. Catalog expansion (sourced ingredient lists)
  - [ ] 7d. Conversational AI
    - [x] Units 1-3. Knowledge base and retrieval, red-flag router, output gate, local model
          and endpoint, model bake-off
    - [x] Unit 4. Chat page. The manual browser checklist was run by the author; its
          real-phone item was not run and is still to do, together with the outstanding
          real-phone scan test (see the [chat README](backend/app/services/chat/README.md))
    - [ ] Unit 5. Open items: the rate limiter before the router, a manual faithfulness
          check, the evaluation write-up
  - [ ] 7e. Generative Visualizer
- [ ] 8. Secondary features, testing, deploy

The details of each step, and where the code lives, are in [`CLAUDE.md`](CLAUDE.md).

## Deviations from the original spec

[`docs/spec.md`](docs/spec.md) is the original specification. Its text is unchanged, and
an addendum at its end records these deviations:

- **Image analysis is classical computer vision**, not a fine-tuned CV backbone:
  MediaPipe face landmarks plus documented, hand-designed measurements.
- **The EfficientNet-B0 skin-type classifier is gated off.** It was trained on two
  public datasets but scored at chance on a leak-free split (test accuracy 0.309 against
  0.25 chance), so it is not served.
- **The questionnaire is rule-based:** documented rules and a lexicon for the free-text
  answers, not an ML classifier.
- **Skin type and sensitivity come from the questionnaire only.** Sensitivity is its own
  flag (`is_sensitive`), not a skin type.
- **No object storage.** Photos are analysed in memory and discarded; nothing is stored.
- **No on-device inference option.** Since 7b-ii the funnel sends the photo to the server
  for analysis (in memory, never stored); the on-device/in-browser choice in the spec is
  not built.
- **The product catalog is 37 real products** whose ingredient lists are sourced from the
  cited pages; spot-checked by a person: not yet (13 from non-India pages). Not a complete
  market.
- **The recommendation ranker is not ML-trained**: IDF × rank-decay weighting over
  rule-eligible sets, with hand-set weights; there is no outcome data to train or
  validate on.
- **The chat's answer arrives whole, not as it is generated.** The server checks every
  sentence and releases the answer only when the model has finished, so the spec's "chat
  streams within 1-2 s of first token" doesn't hold. After the fixes, the whole answer took a
  median of 1.7 s (p90 2.4 s) on the development machine.

## Documentation

- [`docs/spec.md`](docs/spec.md) — original project spec: features, sitemap, architecture, NFRs, evaluation plan (addendum at the end)
- [`CLAUDE.md`](CLAUDE.md) — conventions and hard constraints for Claude Code sessions
- Service READMEs: [`image_analysis`](backend/app/services/image_analysis/README.md), [`questionnaire`](backend/app/services/questionnaire/README.md), [`skin_profile`](backend/app/services/skin_profile/README.md), [`ingredients`](backend/app/services/ingredients/README.md), [`recommendation`](backend/app/services/recommendation/README.md), [`chat`](backend/app/services/chat/README.md)
- [`backend/catalog/README.md`](backend/catalog/README.md) — the product catalog: where each list comes from, the loader's checks, how to add a row

## License

Academic project — MSc Data Science, NMIMS NSOMASA.
