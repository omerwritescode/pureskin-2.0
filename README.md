# PureSkin

AI-driven personalized skincare platform — combines computer vision, generative AI, NLP,
and MLOps to turn a selfie and short questionnaire into a data-backed Skin Profile,
adaptive routine, and conversational skincare advisor.

MSc Data Science project, NMIMS NSOMASA, Mumbai.

> **Status:** early build. See [Build status](#build-status) below for where things stand.

## What it does

- **Objective diagnosis** — a selfie + questionnaire produces a structured Skin Profile
  (acne, redness, wrinkles, pigmentation, pore visibility) instead of a generic quiz result
- **Adaptive routines** — AM/PM recommendations that account for the user's Skin Profile,
  existing products, and ingredient conflicts
- **Ingredient intelligence** — flags conflicting actives (e.g. retinol + benzoyl peroxide)
  across a routine or scanned product
- **Visual trust-building** — a generative "4 weeks from now" preview tied to a routine
- **Conversational guidance** — a chatbot grounded in the user's own Skin Profile via RAG

Full feature list, sitemap, architecture, and NFRs: [`docs/spec.md`](docs/spec.md)

## Tech stack

- **Frontend:** plain HTML, CSS, and vanilla JavaScript — no framework
- **Backend:** Python, FastAPI — one microservice per AI capability
- **Database:** PostgreSQL, run locally in Docker + encrypted object storage for images
- **AI/ML:** fine-tuned CV backbone (EfficientNet/ViT) for image analysis, a lightweight
  classifier for the questionnaire, a RAG + LLM pipeline for chat, a generative model for
  the visual preview
- **Auth:** OAuth 2.0 / JWT
- **MLOps:** MLflow/Kubeflow, containerized via Docker/Kubernetes

See [`docs/spec.md`](docs/spec.md) §7 for the full stack breakdown.

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
- Python 3.11+ and FastAPI
- Docker (runs the local PostgreSQL instance)
- An Anthropic API key (only needed once the Conversational AI service is built)

```bash
git clone <repo-url>
cd pureskin
cp .env.example .env   # fill in local values
# setup/run commands will be added here once the backend is scaffolded
```

## Build status

Tracking against the roadmap in [`docs/spec.md`](docs/spec.md) §8:

- [ ] 1. Project scaffold
- [ ] 2. Database schema + migrations
- [ ] 3. Auth end-to-end
- [ ] 4. Static frontend shell (nav + empty pages)
- [ ] 5. Onboarding funnel (mocked scoring)
- [ ] 6. Core pages on real, rule-based data
- [ ] 7. AI services (one at a time)
- [ ] 8. Secondary features, testing, deploy

## Documentation

- [`docs/spec.md`](docs/spec.md) — full project spec: features, sitemap, architecture, NFRs, evaluation plan
- [`CLAUDE.md`](CLAUDE.md) — conventions and hard constraints for Claude Code sessions

## License

Academic project — MSc Data Science, NMIMS NSOMASA.
