# PureSkin — Project Specification

AI-driven personalized skincare platform. MSc Data Science project, NMIMS NSOMASA.

## 1. Overview

PureSkin closes the gap between generic, one-size-fits-all skincare advice and objective,
data-backed guidance. It combines computer vision, generative AI, NLP, and MLOps into a
single product: a selfie + short questionnaire replaces guesswork with a structured
**Skin Profile**, which then drives adaptive routines, ingredient-conflict checking, a
generative "4 weeks from now" preview, and a conversational skincare advisor grounded in
the user's own profile.

**Target users:** skincare-conscious millennials/Gen Z wanting evidence-based routines;
ingredient-conscious users avoiding conflicting actives; skincare beginners; privacy-sensitive
users who want AI analysis without surrendering control of biometric data.

## 2. Key technical decision

**Frontend is built with plain HTML, CSS, and JavaScript — no React, no Vue.**
Any reference to React/Vue in older project documents is superseded by this decision.
Where a chart or barcode-scan library is genuinely useful, load it via a `<script>` CDN
tag (e.g. Chart.js) rather than pulling in a framework.

## 3. System architecture

Cloud-hosted, microservices-based web app (optional React Native mobile client is out of
scope for the initial build).

| Layer | Components | Responsibility |
|---|---|---|
| Client | HTML/CSS/JS web app | Responsive UI, onboarding, camera capture, chat, dashboards |
| Gateway & Auth | API Gateway, OAuth 2.0 / JWT | Routing, rate limiting, authentication, social login |
| Core Services | Image Analysis, Questionnaire/NLP, Recommendation Engine, Conversational AI, Generative Visualizer | Independent, containerized microservices, each owning one AI capability |
| Data Layer | PostgreSQL (in Docker), encrypted object storage | User profiles, Skin Profiles, progress logs, encrypted images, product catalog |
| MLOps Layer | MLflow/Kubeflow, model registry, CI/CD | Experiment tracking, retraining, model versioning |
| Observability | Prometheus/Grafana, TensorBoard | API latency, model drift, prediction accuracy, uptime |

**Data flow (selfie → recommendation):**
1. User captures a selfie + completes the questionnaire.
2. Image Analysis and Questionnaire/NLP services score inputs independently, merged into one Skin Profile object.
3. Recommendation Engine matches the Skin Profile + preferences against the product catalog, applying ingredient-conflict rules.
4. Generative Visualizer optionally renders a projected outcome.
5. Results are persisted (encrypted) and surfaced on the dashboard; Conversational AI can then be queried against this profile.

**Privacy by design:** users choose on-device/in-browser inference (image never leaves
the device) or server-side inference with automatic deletion after processing. All data
at rest encrypted, all traffic HTTPS, training images anonymized.

## 4. Features (build target)

1. **Landing / Marketing Page** — static HTML/CSS, JS for nav toggle + scroll effects. No backend.
2. **Signup / Login** — HTML form → JS `fetch()` → Auth service (JWT). bcrypt hashing. Social login optional.
3. **Selfie Capture** — JS `getUserMedia()` + `<canvas>`, uploads Blob or runs ONNX.js/TensorFlow.js on-device.
4. **Questionnaire** — multi-step HTML form, JS step navigation, posts JSON to `/api/questionnaire`.
5. **Skin Profile generation** — backend orchestration merges Image Analysis + Questionnaire outputs into one object.
6. **Skin Profile Dashboard** — JS fetches profile JSON, renders scores via `<canvas>`/SVG or Chart.js.
7. **Routine Builder** — JS renders AM/PM routine JSON from the Recommendation Engine, flags conflicts.
8. **Product Catalog & Ingredient-Conflict Checker** — searchable grid, JS debounced search, optional barcode scan (quagga.js via CDN).
9. **Generative Visualizer** — before/after image comparison slider (vanilla JS draggable divider). MVP: static pre-generated pairs.
10. **Conversational AI Chat** — chat UI, JS `fetch()` with streaming `ReadableStream`, RAG + LLM backend grounded in the user's Skin Profile.
11. **Progress Tracking** — line chart of scores over time (Chart.js or hand-rolled SVG), `scan_history` table.
12. **Privacy Dashboard** — on-device/server toggle, data export, delete-my-data (cascading delete).
13. **Notifications** — browser push (Notifications API + service worker) or scheduled email reminders.
14. **Subscription / Premium Paywall** — Stripe Elements/Checkout via CDN script, `subscriptions` table + webhook.
15. **Databases** — PostgreSQL (in Docker): `users`, `skin_profiles`, `scan_history`, `products`, `ingredient_conflicts`, `subscriptions`. Encrypted object storage for images.
16. **Backend/MLOps layer** — API Gateway, Auth service, independently deployable microservices (Docker/Kubernetes), MLflow/Kubeflow, Prometheus/Grafana/TensorBoard.

## 5. Sitemap & navigation

**Design principle:** a persistent nav bar on every authenticated page means any core
page is 1 click from any other — this alone satisfies a 3-click rule for the whole
logged-in app. Deepest page (Checkout) is 3 clicks from Dashboard.

### Tier 0 — Public (no login)
- `/` Landing Page → links to Free Scan, About, Pricing, Login
- `/about` About/How It Works
- `/pricing` Pricing → links to Free Scan, Signup/Checkout

### Onboarding funnel (linear, pre-account)
- `/scan` Selfie Capture → auto-advances to Questionnaire
- `/scan/questionnaire` Questionnaire → auto-advances to Skin Report
- `/scan/report` Skin Report (pre-signup) → CTA to Signup
- `/auth` Signup/Login → on success, redirects to Dashboard

### Tier 1 — Authenticated core (persistent nav, 1 click apart)
- `/app` Dashboard (hub)
- `/app/profile` Skin Profile
- `/app/routine` Routine
- `/app/catalog` Product Catalog
- `/app/chat` Conversational AI
- `/app/progress` Progress
- `/app/settings` Settings (hub for Privacy / Subscription / Account)

### Tier 2 — Detail pages (2 clicks from Dashboard)
- `/app/catalog/:id` Product Detail
- `/app/progress/:scanId` Scan Detail
- `/app/routine/preview` Visual Efficacy Preview
- `/app/settings/privacy` Privacy Dashboard
- `/app/settings/subscription` Subscription
- `/app/settings/account` Account Settings

### Tier 3 — Deepest page (3 clicks from Dashboard)
- `/app/settings/subscription/checkout` Checkout

## 6. Non-functional requirements

- **Performance:** analysis inference returns in 3–5s on standard mobile connection; chat streams within 1–2s of first token.
- **Scalability:** each microservice scales independently via containers/Kubernetes.
- **Availability:** 99.5% uptime target for core analysis/recommendation, graceful degradation (cached last-known routine).
- **Security:** TLS everywhere, encryption at rest, OAuth 2.0/JWT, regular audits.
- **Privacy/Compliance:** GDPR/HIPAA-aligned handling, opt-in-only training data, on-device inference option, export/delete on request.
- **Usability/Accessibility:** mobile-first responsive, WCAG-aligned, guided onboarding.
- **AI reliability:** >85% agreement with dermatologist-labeled data on core attributes before release.
- **Bias & fairness:** training data spans diverse skin tones; validated per-subgroup before rollout.
- **Auditability:** predictions/recommendations logged (de-identified).

## 7. Technology stack

| Layer | Choice |
|---|---|
| Frontend (Web) | HTML, CSS, vanilla JavaScript — mobile-first |
| Backend Services | Python, **FastAPI** — one microservice per AI capability |
| Computer Vision | EfficientNet / Vision Transformer, fine-tuned (ISIC, Fitzpatrick17k) |
| Generative AI | Conditional GAN or diffusion image-to-image model |
| NLP / Conversational AI | LLM + retrieval-augmented generation over a skincare knowledge base |
| Database | **PostgreSQL**, run locally in **Docker**; encrypted object storage for images |
| Auth | OAuth 2.0 / JWT, social login |
| MLOps | MLflow or Kubeflow; DVC/ClearML for data/model versioning |
| Deployment | Docker + Kubernetes; AWS/GCP/Azure |
| CI/CD & IaC | GitHub Actions or Jenkins; Terraform/CloudFormation |
| Monitoring | Prometheus/Grafana; TensorBoard |

**Implementation notes:** start from pre-trained CV backbones rather than training from
scratch given limited labeled dermatology data. Treat the Generative Visualizer as a
stretch goal — mock with static before/after pairs first. Use RAG for the chatbot from
day one to reduce hallucination risk. Automate retraining quarterly, gated by
drift-monitoring alerts.

## 8. Build roadmap (recommended order for Claude Code)

1. **Scaffold the project** — folder structure (`frontend/`, `backend/`), package/requirements files, `.env.example`, README. No feature code yet.
2. **Design and migrate the database schema** — `users`, `skin_profiles`, `scan_history`, `products`, `ingredient_conflicts`, `subscriptions`, via a migration tool.
3. **Build auth end-to-end** — JWT signup/login API + real HTML/CSS/JS pages, protected routes.
4. **Build the static frontend shell** — persistent nav + empty page shells for all Tier-1 pages, routing in place, no real data yet.
5. **Wire the onboarding funnel with mocked scoring** — Selfie Capture, Questionnaire, Skin Report calling a mocked endpoint returning fake Skin Profile JSON.
6. **Connect core pages to real, rule-based data** — Dashboard, Skin Profile, Routine (rules-only), Catalog wired to the real database.
7. **Layer in the AI services one at a time** — Image Analysis → Questionnaire/NLP → ML-ranked Recommendation Engine → Conversational AI (RAG) → Generative Visualizer (static pairs first).
8. **Add secondary features, then test and deploy** — Progress tracking, Privacy Dashboard, notifications, Subscription/Checkout, then a usability + mobile pass, then containerize and deploy.

## 9. Evaluation plan (for the academic report, not the build itself)

- **Model:** >85% agreement with dermatologist labels; subgroup fairness testing; chatbot groundedness rate.
- **Product/User:** usability testing sessions; trust score target >4/5; engagement metrics (WAU, check-in frequency, churn).
- **Business:** free-to-premium conversion, affiliate click-through, NPS at launch and after iterations.
- Reviewed together at each milestone (MVP, pilot, expanded feature set) — an accurate-but-unusable or delightful-but-unreliable model both fail the product's trust-first promise.

---

## Addendum (October 2026, after roadmap steps 7b-i and 7b-ii): deviations from this spec

The sections above are the original specification and are left unchanged. As built:

1. **Image analysis is classical computer vision.** It uses MediaPipe face landmarks plus
   documented, hand-designed measurements (OpenCV, NumPy), not a fine-tuned
   EfficientNet/ViT backbone (§7). The five scores are unvalidated heuristics, so the
   ">85% agreement with dermatologist-labeled data" target (§6, §9) cannot be claimed
   for them.
2. **The EfficientNet-B0 skin-type classifier is gated off.** It was trained on two public
   datasets but scored at chance on a leak-free split (test accuracy 0.309 against 0.25
   chance), so it is not served.
3. **The questionnaire is rule-based:** documented rules and a small lexicon for the
   free-text answers, with no ML classifier.
4. **Skin type and sensitivity come from the questionnaire only.** Sensitivity is its own
   flag (`is_sensitive`) rather than a skin type.
5. **No object storage.** Photos are analysed server-side in memory and discarded.
   Nothing is stored, so the encrypted object storage for images (§3, §4 item 15) is not
   built.
6. **No on-device inference option** (added after 7b-ii). The scan funnel sends the photo
   to the server for analysis (in memory, never stored). The user's choice of
   on-device/in-browser inference (§3, §6) is not built.

Details: `backend/app/services/image_analysis/README.md`,
`backend/app/services/questionnaire/README.md` and
`backend/app/services/skin_profile/README.md`.
