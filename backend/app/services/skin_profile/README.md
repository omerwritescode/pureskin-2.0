# Skin Profile service (roadmap step 7b-i)

Merges the two scoring services into one Skin Profile: the five scores, skin type,
sensitivity, and a record of where each value came from. Pure Python with documented
rules; no model, no new dependencies.

- **Image Analysis** ([../image_analysis/README.md](../image_analysis/README.md)):
  five heuristic 1-100 scores from a selfie.
- **Questionnaire/NLP** ([../questionnaire/README.md](../questionnaire/README.md)):
  skin type, sensitivity, and a 1-100 estimate per score (or null).

> **Both inputs are unvalidated.** The image scores are heuristics with weak (ρ
> 0.25-0.33) or no (acne, ρ 0.11) correlation with human ratings. The questionnaire
> estimates are self-reports mapped by hand-set rules. The merge is a set of documented
> judgement calls on top. Nothing here was validated against dermatologists.

**Status:** live at `POST /api/scan/analyze`, which the scan funnel calls at the end of
the questionnaire (since 7b-ii). The result is shown on the Skin Report and saved at
signup with `POST /api/profile`.

---

## Interface

### Python

```python
from app.services.skin_profile import build_skin_profile, merge_score, reproduce_final, band

profile = build_skin_profile(analyze_image(image_b64), score_questionnaire(answers))
final, entry = merge_score("acne_score", image=95, questionnaire=55)   # 60, {...}
reproduce_final("acne_score", entry) == final                          # always True
band(61)                                                               # "High"
```

### HTTP: `POST /api/scan/analyze`

No auth (the funnel runs before signup). **No database writes:** the photo is decoded,
scored and discarded in memory, and nothing is logged. The visitor saves the result
with `POST /api/profile` after signing up.

Body: `{"image": "<base64 JPEG or data URL>", "answers": {...questionnaire answers...}}`.
Any other key is rejected: there is no lighting-gate bypass or any other switch.

| Status | Body | When |
|---|---|---|
| 200 | see below | merged |
| 422 | `{"detail": [{"loc", "msg", "type"}]}` | malformed body or answers. Checked **before** the photo is analysed; input never echoed |
| 422 | `{"quality": {"ok": false, "issues": [...]}}` | photo unusable: the image endpoint's hard rejections, same shape |
| 413 | `{"detail": "..."}` | body over the image endpoint's 5 MB limit (chunked uploads too) |
| 503 | `{"detail": "..."}` | face model missing. **No fallback scores, ever** |

The 200 body has the profile's keys (five scores and the skin type), plus four more:

```json
{
  "acne_score": 60, "redness_score": 27, "wrinkle_score": 34, "pigmentation_score": 51,
  "pore_score": 32, "skin_type": "combination",
  "is_sensitive": false,
  "score_sources": {
    "version": {"image_model": "image-analysis-1.0.0+heuristic-1+skin-type-none",
                "questionnaire_config": "questionnaire-1.0.0", "merge_config": "merge-1.0.0"},
    "skin_type": "questionnaire",
    "is_sensitive": "questionnaire",
    "scores": {
      "acne_score": {"method": "image", "image": 85, "questionnaire": null, "weight_image": 1.0,
                     "corroborated": false, "capped": true, "floored": false},
      "redness_score": {"method": "image", "image": 27, "questionnaire": null, "weight_image": 1.0},
      "...": "one entry per score"
    }
  },
  "sources": {"skin_type": "questionnaire", "is_sensitive": "questionnaire",
              "acne_score": "image only, capped at 60 (not corroborated)",
              "redness_score": "image only", "...": "..."},
  "quality": {"ok": true, "issues": ["Some areas were hidden or in shadow and were left out: chin."]}
}
```

`quality.issues` holds the image service's **soft** warnings: the photo was scored, but
less reliably. `sources` is a short readable version of `score_sources`. `raw_image_path`
stays empty, because images are not stored.

---

## Score bands

The one definition of the bands, in `skin_profile_config.py`:

| Band | Scores |
|---|---|
| Low | 1-30 |
| Moderate | 31-60 |
| High | 61-100 |

- **The frontend band module, `frontend/static/js/bands.js`, uses the same cutoffs.**
  `app/tests/test_frontend_contract.py` parses it and fails if they drift.
- The step 6 routine adds a score's targeted steps when the score is > 60, which is
  exactly the High band (a test checks this).

## Merge rules

Every number is in **`skin_profile_config.py`** (`MERGE_CONFIG_VERSION = "merge-1.0.0"`).

### Redness, wrinkle, pigmentation, pore: the image is primary

```
final = image + clamp(0.3 × (questionnaire − image), −15, +15)
```

- **No questionnaire evidence:** a null estimate leaves the image score alone (method
  `image`).
- **Why the image leads:** these four scores have weak but real correlation with human
  ratings, and they measure the face in front of the camera. The questionnaire corrects
  them by at most 15 points.
- **Example:** phone selfies read high on pigmentation (image README, limitation 10). An
  image score of 66 next to an answer of "a few spots" (30) gives 55.

### Acne: the questionnaire is primary

```
value = questionnaire + clamp(0.25 × (image − questionnaire), −10, +10)
```

**Why the questionnaire leads.** The image acne score showed **no** correlation with
human ratings (Spearman 0.11, 95% CI −0.07 to 0.28). It also swung from 1 to 58 across
four photos of one face, and from 58 to 20 when one photo was downsized for the funnel
(see below). So the image only nudges the self-report.

**Corroboration means the questionnaire's acne estimate on its own is High (≥ 61).**
With the current anchors, that's breakouts "constantly" (75), or "most weeks" plus
"sometimes" / "often" deep bumps (55 / 65: only the second qualifies).

- **Without corroboration, the final acne score is capped at 60** (the top of Moderate).
  That includes the case with no acne answer at all, where the method is `image` and
  `questionnaire` is null. So **the image alone can never trigger the routine's > 60
  acne step.**
- **With corroboration, the final acne score is never below 61** (the floor). The image
  may nudge it within the High band but can't veto a High self-report. For example,
  "most weeks" + "often" (65) with image acne 1 gives 55 before the floor, so 61.

The acne entry in `score_sources` always has three booleans. Its `weight_image` is the
blend weight **before** the cap and floor; `capped` and `floored` say whether the cap or
the floor **then** changed the number:

| Flag | True when |
|---|---|
| `corroborated` | the questionnaire estimate exists and is ≥ 61 (a property of the inputs) |
| `capped` | the 60 cap actually lowered the final score |
| `floored` | the 61 floor actually raised the final score |

### Skin type and sensitivity: the questionnaire only

`skin_type` and `is_sensitive` come straight from the questionnaire scorer. The image
service's skin-type classifier is not served (chance-level on a leak-free split), and
even a non-null `skin_type_prediction` would be ignored here. `score_sources.skin_type`
is `"default"` when the questionnaire had no oil/dry evidence (its rule T3).

### The primary concern never moves a score

The primary concern is a goal, not a measurement, so it never touches a score. (The
step 5 placeholder pushed the stated concern's score up; that endpoint was removed in
7b-ii, and the real merge never does this. Tested.)

### Representative cases

Generated by calling the real `merge_score()`. Re-run with
`python -m app.services.skin_profile.merge_cases`, and `tests/test_merge.py` checks
the same cases.

| score | image | questionnaire | final | band | method | weight_image | corroborated | capped | floored | case |
|---|---|---|---|---|---|---|---|---|---|---|
| acne | 5 | 75 | **65** | High | blend | 0.143 | yes | no | no | breakouts 'constantly': image can't pull it out of High |
| acne | 49 | 65 | **61** | High | blend | 0.25 | yes | no | no | 'most weeks' + 'often' deep bumps: corroborated, lands at 61 |
| acne | 95 | 45 | **55** | Moderate | blend | 0.2 | no | no | no | high image acne, 'most weeks' only: not corroborated, stays Moderate |
| acne | 1 | 65 | **61** | High | blend | 0.156 | yes | no | yes | corroborated but image says 1: floor raises 55 to 61 |
| acne | 95 | 55 | **60** | Moderate | blend | 0.25 | no | yes | no | 'most weeks' + 'sometimes': 65 capped to 60 |
| acne | 80 | — | **60** | Moderate | image | 1.0 | no | yes | no | no acne answers (or 'Not sure'): image capped at 60 |
| acne | 40 | — | **40** | Moderate | image | 1.0 | no | no | no | no acne answers, image under the cap: unchanged |
| pigmentation | 66 | 30 | **55** | Moderate | blend | 0.7 | — | — | — | phone selfie reads high, 'a few spots': pulled down |
| redness | 20 | 75 | **35** | Moderate | blend | 0.727 | — | — | — | 'almost always' flushed: +15 limit applies |
| pore | 50 | — | **50** | Moderate | image | 1.0 | — | — | — | no pore answer: image only |

## `score_sources`: provenance you can recompute

The contract is in `schemas.py`, stored in `skin_profiles.score_sources` (JSONB):

- **Strict.** Unknown keys are rejected anywhere in it, and the version strings are
  short identifiers. Raw answers, free text or images can't be stored in it.
- **Acne-only flags.** Every score has `method`, `image`, `questionnaire` and
  `weight_image`. Only acne also has `corroborated`, `capped` and `floored`; they are
  required there and rejected on the other scores.
- **Internally consistent.**
  - The method has to match which inputs are present, and an `image` method needs
    weight 1.
  - `corroborated` has to equal "questionnaire ≥ 61".
  - A corroborated score is never capped; an uncorroborated one is never floored.
- **Reproducible.** `weight_image` is the *effective* image weight of the blend, rounded
  to 3 decimals. For acne it is the weight **before** the cap and floor; `capped` /
  `floored` record whether the cap or the floor then changed the number. The blend is
  computed **from the rounded weight**, so `reproduce_final(name, entry)` gives back the
  stored score exactly: `round_half_up(w·image + (1 − w)·questionnaire)`, then 60 if
  `capped` or 61 if `floored`. This is tested over all 100 × 101 image × estimate
  combinations for every score.
- **Checked on save.**
  - `POST /api/profile` rejects (422) a `score_sources` whose entries don't reproduce
    the scores sent with it.
  - The check only applies when `version.merge_config` is the **current**
    `MERGE_CONFIG_VERSION`. `reproduce_final()` applies today's rules, so a scan merged
    under an older config is stored as sent. That way a scan taken before an update and
    saved at signup after it is never rejected.

---

## Known limitations

1. **Pre-signup results pass through the client.** `/api/scan/analyze` runs before
   signup and stores nothing. The browser keeps the result in sessionStorage and posts
   it to `POST /api/profile` after login, so a user could alter it in between.
   - **What the server checks:** the scores are valid, the `score_sources` contract
     holds, and every score reproduces from its entry.
   - **What it can't check:** a user who rewrites the scores and the entries
     *consistently* would get through.

   That's acceptable for this project (users can only mislead their own routine), and
   documented here rather than solved. A fix would need a server-side session or a
   signed result.
2. **"Not sure" leaves a score to the image.** A score whose question was answered "Not
   sure" has no questionnaire evidence, so it is the image score (acne capped at 60).
3. **The weights, limits, cap and floor are judgement calls, not fitted values.** There
   is no ground truth to fit them to. The cap and floor sit on the band edges by
   design; the 0.3 / ±15 and 0.25 / ±10 are chosen, not estimated.
4. **Only scores, skin type and sensitivity are merged.** The questionnaire's tags
   (`avoid`, `actives_in_use`, `concern_tags`) are neither returned by
   `/api/scan/analyze` nor stored, because `skin_profiles` has no column for them. 7c
   (recommendations) will need to decide where they live.
5. **Oily + sensitive.** The step 6 routine still *replaces* the skin type's base steps
   with the sensitive set when `is_sensitive` is true (minimal 7b-i compatibility,
   TODO(7c) in `routine.py`).

## Checks run for 7b-i and 7b-ii

**Resolution.** Since 7b-ii the image service analyses every photo at a canonical
720 px, whatever size the client sends. The selfie page sends 720 px at JPEG quality
0.92. See the image_analysis README, "Canonical resolution", for the results:
- the four image-primary scores agree within 4 points across 720/960/1080 px uploads;
- acne moves more (it is documented as unstable), which the merge already guards
  against: at most 25% image weight, a ±10 limit, and the cap and floor;
- one dim photo can still flip between accepted and "too dim", because the dim check's
  white reference is sensitive to resampling noise.

**Timing (7b-ii).** Measured with `python -m app.services.skin_profile.time_analyze`
on an i7-13620H on AC power, 20 runs per photo, in-process, with 720 px JPEG q92
uploads:

| Part | Time |
|---|---|
| `POST /api/scan/analyze`, whole request | median 0.20-0.22 s, worst 0.28 s |
| Image analysis | almost all of it (median 0.19-0.20 s) |
| Questionnaire scorer | 0.1 ms |
| Merge | 0.1 ms |
| The photo check (`POST /api/services/image/analyze`) | median 0.22 s, worst 0.27 s |

The funnel makes both calls, so a scan spends about 0.45 s on the server: far inside
the spec's 3-5 s target. Network time comes on top. The 7b-i measurement (0.60-0.91 s)
was taken on battery with a throttled CPU, before the canonical resolution.

**The step 6 routine on merged profiles** (`app/tests/test_scan_to_routine.py`):
- **High image acne without corroboration** (image 92, today's answers): acne becomes
  60, so there are no salicylic or benzoyl peroxide steps.
- **Corroborated acne with image acne 1:** floored to 61, so both acne steps are added.
- **Oily + sensitive:** gets the sensitive set (fragrance-free cleanser, mineral SPF),
  plus azelaic acid for redness 70.
- **"A few spots" with image pigmentation 66:** becomes 55, so the pigmentation serums
  are not added.

## Testing

```bash
python -m pytest app/services/skin_profile     # from backend/
python -m pytest app/tests                      # profile / routine / migration (needs Docker)
```

- **Merge** (`tests/test_merge.py`):
  - **Bands:** they cover 1-100, and the routine trigger is exactly High.
  - **Image-primary bounds:** over every image × estimate pair, the score moves toward
    the questionnaire by at most 15 and never past it. A null estimate gives the image
    score.
  - **Acne:** the cap, floor and corroboration rule hold over every input. The image
    alone never exceeds 60; a High self-report never drops below 61. The three worked
    examples, the floor and cap cases, and monotonicity are covered.
  - **Reproduction:** every merged score reproduces from its entry.
- **Contract** (`tests/test_schemas.py`):
  - The acne flags are required on acne and rejected elsewhere.
  - Inconsistent entries are rejected.
  - The final acne score reproduces from the stored JSON.
- **Endpoint** (`tests/test_analyze_endpoint.py`):
  - **Response:** the profile's keys plus the extras; skin type and sensitivity come
    from the questionnaire only (the image's "prediction" is ignored); changing only the
    primary concern changes nothing.
  - **Errors:** the image rejection passes through as a 422 in the image endpoint's
    exact shape. Oversized bodies (plain and chunked) get a 413, and a missing model a
    503 with no scores.
  - **No bypass:** `lighting_gate`, `debug` and any other extra key give a 422 before
    any analysis, and bad answers are rejected before the photo is analysed.
  - **Privacy:** a malformed body's 422, the logs and the 200 contain neither image data
    nor free text.
  - **Real selfies** (skipped if `samples/` is empty): run end to end and are
    deterministic.
- **Through the database** (`app/tests/`):
  - Analyze → save → routine, as above.
  - The stored acne score reproduces from the stored `score_sources`.
  - Tampered scores are rejected.
  - Migration up/down (`test_migration_sensitivity.py`).

## Files

| File | Purpose |
|---|---|
| `__init__.py` | public interface |
| `skin_profile_config.py` | **bands, weights, limits, cap, floor**, versioned |
| `merge.py` | `merge_score`, `blend`, `reproduce_final`, `band` |
| `orchestrator.py` | `build_skin_profile`: the merged response and the `sources` summary |
| `schemas.py` | the strict `score_sources` contract |
| `merge_cases.py` | prints the representative-cases table above |
| `time_analyze.py` | dev tool: endpoint timing on this machine |
| `tests/` | pytest suite |

The HTTP endpoint is in `backend/app/api/scan_analyze.py`.
