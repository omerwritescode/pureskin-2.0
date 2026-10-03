# Image Analysis service (roadmap step 7a)

Selfie → five skin scores (1–100) + photo-quality feedback, using MediaPipe face
landmarks and classical computer vision (OpenCV + NumPy). Runs locally on CPU; no paid or
cloud APIs.

> **These scores are unvalidated heuristics.** No dermatologist-labelled ground truth
> was used to build or check them. They are consistent, explainable image measurements,
> **not** clinical assessments. The spec's target of ">85% agreement with dermatologist
> labels" (`docs/spec.md` §6, §9) **cannot be claimed** for them. Meeting it would need a
> labelled evaluation set, which this project does not have.

**Status:** All parts done. The five heuristic scores and the quality checks are live
at the standalone endpoint. The skin-type classifier (Part 3) was trained and
evaluated, but it performs at chance on a leak-free split, so it is not served and
`skin_type_prediction` is `null` (see [Part 3](#skin-type-classifier-part-3)). Since
7b-i it also runs inside `POST /api/scan/analyze` (the skin_profile service merges it
with the questionnaire). Since 7b-ii the scan funnel uses both endpoints: the selfie page
checks each photo with this endpoint right after capture or upload, and the
questionnaire calls `/api/scan/analyze` at the end. Every photo is analysed at a
[canonical 720 px](#canonical-resolution-step-7b-ii).

---

## Contents

1. [Quick start](#quick-start)
2. [Interface](#interface)
3. [Pipeline](#pipeline)
4. [Photo-quality checks](#photo-quality-checks)
5. [Normalisation (lighting, distance, skin tone)](#normalisation)
6. [How each score is measured](#how-each-score-is-measured)
7. [Calibration](#calibration)
8. [Lighting consistency](#lighting-consistency)
9. [Skin-type classifier (Part 3)](#skin-type-classifier-part-3)
10. [Performance](#performance)
11. [Privacy](#privacy)
12. [Known limitations](#known-limitations)
13. [Testing](#testing)
14. [Files](#files)

---

## Quick start

From `backend/` with the venv active (Python 3.14):

```bash
pip install -r requirements-dev.txt                       # runtime deps + pytest + httpx2
python -m app.services.image_analysis.download_models     # MediaPipe model -> models/ (3.7 MB, once)
python -m pytest app/services/image_analysis              # tests
uvicorn app.main:app --reload                             # POST /api/services/image/analyze
```

If the model file is missing, the server still starts. It logs an error with the
download command, and the endpoint returns 503 until the file exists (no restart needed).

Developer tools (they read photos you put on disk yourself):

```bash
python -m app.services.image_analysis.visualize_regions             # region/detection overlays -> samples/_debug/
python -m app.services.image_analysis.check_lighting_consistency --synthetic
```

### Dependency notes

- **MediaPipe 1.x** (Python 3.14 wheels available) has only the **Tasks API**
  (`FaceLandmarker` + a downloaded `.task` model). The legacy `mp.solutions.face_mesh`
  no longer exists, so this service uses `FaceLandmarker`.
- MediaPipe depends on `opencv-contrib-python`. Don't also install
  `opencv-python`/`opencv-python-headless`, because two cv2 builds overwrite each other.
- `requirements.txt` stays CPU-only (`torch==2.11.0` from PyPI, for classifier
  inference). The CUDA build is for training only, in `requirements-train.txt`; see
  [Part 3](#skin-type-classifier-part-3).
- `requirements-dev.txt` lists **`httpx2`, not a typo**. Starlette 1.x's `TestClient`
  imports `httpx2` (same author as `httpx`, github.com/pydantic/httpx2) and warns that
  plain `httpx` is deprecated.

---

## Interface

### Python

```python
from app.services.image_analysis import analyze_image, ImageRejected, ModelUnavailable

result = analyze_image(image_b64)  # bare base64 or "data:image/jpeg;base64,..."
```

Returns:

```json
{
  "acne_score": 19, "redness_score": 50, "wrinkle_score": 88,
  "pigmentation_score": 40, "pore_score": 63,
  "skin_type_prediction": null,
  "skin_type_confidence": null,
  "skin_type_labels_supported": [],
  "quality": {"ok": true, "issues": ["Smiling deepens the lines around your eyes; ..."]},
  "model_version": "image-analysis-1.0.0+heuristic-1+skin-type-none"
}
```

- Scores are integers 1–100 (higher = more of that concern), matching the
  `skin_profiles` CHECK constraints.
- `quality.issues` holds **soft warnings only** (e.g. smiling, slight blur, slight head
  turn, some glare): the scores are usable but less reliable. **Dim and uneven lighting
  are not warnings; they are hard rejections** (HTTP 422, see below).
- `skin_type_labels_supported` lists the labels the classifier was trained on (empty
  until Part 3), so a classifier that can't produce e.g. "sensitive" says so.
- Unusable photos raise `ImageRejected` (`.issues` lists why). A missing model raises
  `ModelUnavailable`.

### HTTP: `POST /api/services/image/analyze`

No auth (the funnel runs before signup). Body: `{"image": "<base64 JPEG or data URL>"}`.

| Status | Body | When |
|---|---|---|
| 200 | the dict above | photo analysed |
| 422 | `{"quality": {"ok": false, "issues": ["..."]}}`, no scores | photo unusable, including too dim or unevenly lit (see below) |
| 400 | `{"detail": "..."}` | not JSON / no `image` string |
| 413 | `{"detail": "..."}` | body over 5 MB (oversized bodies up to 20 MB are drained so the client can read the 413; larger ones are cut off) |
| 503 | `{"detail": "..."}` | face model not downloaded |

The endpoint reads and parses the body itself rather than through a Pydantic model.
That way an oversized upload is refused without being buffered, and a malformed request
is never echoed back: FastAPI's default validation error includes the input value, which
here would be the photo. The CPU-bound work runs in a threadpool.

---

## Pipeline

```
base64 ──► decode in memory (header-only size check first) ──► downscale to ≤720 px (canonical)
       ──► whole-image checks (black / white / smeared frame)
       ──► MediaPipe FaceLandmarker: 478 landmarks, head pose, smile blendshape
       ──► framing checks (no face, >1 face, too small, cut off, turned)
       ──► align: rotate eyes level, scale face width to 300 px ("canonical px")
       ──► linear-light maps + skin mask (per face, relative to its own skin)
       ──► face-level checks (exposure, focus, uneven light, visible skin per region)
       ──► five raw features ──► piecewise-linear map ──► 1–100 scores
```

Regions are polygons over MediaPipe mesh indices (`regions.py`): forehead, both
cheeks, nose (bridge below the eyes, tip, upper alae, stopping above the nostrils), chin,
both under-eye bands, and both crow's-feet areas. Eyes, brows and lips are cut out with a
4 px margin. `visualize_regions.py` draws them on your photos.

All thresholds and mappings are in **`scoring_config.py`**, documented there as
heuristic and tunable. No numbers are hard-coded elsewhere.

---

## Photo-quality checks

**Hard** issues → HTTP 422, no scores. **Soft** issues → scores returned, warning listed.
Dim and uneven lighting are **hard rejections**: they distort the scores enough that
the photo should be retaken. (The `skin_profiles` score columns are NOT NULL, so
withholding individual scores isn't an option.)

| Check | Measure | Hard | Soft |
|---|---|---|---|
| Unreadable | not base64 / not JPEG, PNG or WebP | ✔ | |
| Too large | header says > 25 MP (checked before decoding: decompression-bomb guard) | ✔ | |
| Too dark (frame) | 99th-percentile grey < 40/255 | ✔ | |
| Overexposed (frame) | median grey > 245/255 | ✔ | |
| Blurry (frame) | < 12% of gradient energy lost on re-blurring (σ=1.5; re-blur idea after Crété-Roffet et al. 2007) | ✔ | |
| No face | FaceLandmarker finds none | ✔ | |
| More than one face | a second face ≥ 40% the width of the largest | ✔ | |
| Face too small | face width < 150 px | ✔ | < 220 px |
| Face cut off | face-oval landmarks outside the frame | ✔ | |
| Head turned / tilted | yaw or pitch > 30° | ✔ | > 15° yaw / 20° pitch |
| **Too dim** | white-reference L\* < 38 (eye whites or teeth; else the scene's highlights) | ✔ | |
| Overexposed (face) | > 25% of skin pixels saturated | ✔ | > 6% |
| Blurry (face) | contrast-normalised Laplacian variance < 15 | ✔ | < 50 |
| **Uneven lighting** | brighter / darker cheek luminance > 2.0 | ✔ | |
| Skin hidden | a score has no region with ≥ 35% visible skin | ✔ | some regions skipped |
| Smiling | MediaPipe smile blendshape > 0.5 | | ✔ |

The whole-image checks run **before** face detection, so a black or smeared photo gets
"too dark" / "too blurry" rather than a misleading "no face found". The lighting
rejections use polite retake messages, for example: *"The lighting is too dim for an
accurate result. Please retake the photo in brighter, even light, for example facing a
window during the day."*

### The lighting gate and skin tone

**Dim: why it uses a white reference.** The first version judged exposure on the
95th-percentile brightness of the face area, which is mostly skin. That is
skin-tone-dependent. At identical exposure, the darker-skinned development face read 12
to 15 L\* lower than the lighter one (79 vs 91 well exposed, 40 vs 47 at ×0.2), so
darker skin would have been called "dim" under light that passes a lighter face. Exposure
is now measured on a **white reference**: the brightest part of the eye whites, or of the
teeth when smiling, with catchlights excluded. A reference only counts if it is
near-neutral and brighter than the skin, which rejects lips and squinted lashes. These
are about equally bright for everyone, and the same two faces now read 92.7 vs 93.6 well
exposed and 47.4 vs 48.6 at ×0.2. With no usable reference, the brightest 2% of the whole
scene is used instead; that doesn't depend on skin either. (`lighting.py`)

**Dim: how the threshold was set** (`calibrate_dim_threshold.py`, reproducible):
- **Photos.** 40 public dataset photos: 20 lighter- and 20 darker-skinned by the coarse
  tone measure, all well exposed (reference L\* ≥ 80). None of the project's own photos,
  and none of the 199 rated images.
- **Procedure.** Each was darkened in linear light step by step, re-encoded as JPEG and
  re-scored.
- **Drift.** The largest change among the scores, against the same photo at full
  exposure; then the median over each group.
- **Rule.** The threshold is the reference L\* at the dimmest step where **both**
  groups' median drift is still ≤ 10 points, at that step and every brighter one.

| exposure | median reference L\* | lighter: 4 scores | darker: 4 scores | lighter: all 5 | darker: all 5 |
|---|---|---|---|---|---|
| ×0.7 | 75.2 | 6.0 | 6.0 | 9.0 | 14.5 |
| ×0.5 | 65.4 | 7.5 | 7.0 | 8.5 | 16.0 |
| ×0.4 | 59.5 | 6.0 | 6.0 | 9.0 | 10.0 |
| ×0.3 | 52.7 | 6.0 | 6.0 | 10.0 | 11.0 |
| ×0.25 | 49.0 | 7.0 | 7.0 | 13.5 | 13.5 |
| ×0.2 | 44.3 | 6.0 | 8.0 | 13.5 | 11.5 |
| **×0.15** | **38.8** | 6.5 | **9.5** | 18.0 | 19.5 |
| ×0.1 | 31.6 | 8.0 | **10.5** | 23.5 | 15.0 |
| ×0.07 | 27.2 | 8.0 | 16.0 | 31.5 | 23.5 |
| ×0.05 | 22.4 | 8.0 | 16.0 | 40.5 | 28.5 |

("4 scores" = redness, wrinkles, pigmentation, pores; "all 5" adds acne.)

- **The rule was revised after seeing the data, and is stated as such.** It was fixed in
  advance with drift taken over *all five* scores. That version was degenerate: acne
  alone moves by a median of 5–9 points at just ×0.7, so no step below full exposure
  passed, and it would have rejected nearly every photo. Since acne is documented as
  unreliable (see below), it was left out of the rule. With the other four scores, the
  dimmest passing step is ×0.15, giving **`DIM_MIN_EXPOSURE_L = 38`**.
- **The darker group is the limiting one.** Its drift crosses 10 at ×0.1, while the
  lighter group's stays ≤ 8 all the way down. A single, skin-tone-neutral exposure
  threshold therefore protects the group whose measurements degrade first.
- **That is also a residual unfairness the gate can't remove.** Under the same moderate
  dimness, darker skin's scores are noisier (darker pixels sit closer to the 8-bit
  floor). Equal light gets an equal decision, but not equally precise scores.

**Uneven light: threshold.** The ratio of the two cheeks' luminance compares the same
person's skin, so skin tone cancels. The limit is **2:1, one photographic stop**: the
conventional boundary of flat, even portrait lighting. It is a convention, not fitted to
any photos.

**Effect on the 199 rated images** (gate on vs off; tone by the coarse white-reference
measure):

| | Gate off | Gate on |
|---|---|---|
| Rejected | 44 | **59** (all 15 extra for uneven light; none for dimness) |

| Tone (photos scoreable with the gate off) | Photos | Rejected for lighting | Rate |
|---|---|---|---|
| lighter | 42 | 8 | 19% |
| darker | 8 | 1 | 12% |
| unknown | 105 | 6 | 6% |

There is no sign that the gate rejects darker skin more often. With only 8 darker
images, though, that can't be shown either way.

**Blur thresholds** (two public portraits, 720 px, JPEG q85). Blur of σ=1 px already
costs pore and wrinkle signal (pores 64 → 35 on the sharper face), hence the warning.
σ≈1.5–2 px or more is rejected.

| Blur applied | face sharpness (light / dark-skinned dev face) | result |
|---|---|---|
| none | 127 / 490 | OK |
| σ=1 px | 21 / 31 | OK, "slightly out of focus" |
| σ=1.5 px | 11 / 16 | rejected / warning |
| σ=2 px | 8 / 12 | rejected: too blurry |

---

## Normalisation

The aim is for a score to reflect the skin, not the camera, the lamp or the person's
skin tone. Four mechanisms:

1. **Geometry.** Rotate the face so the eyes are level and rescale it to 300 px wide
   (area-averaged when shrinking, so fine texture isn't aliased). All spatial sizes
   (lesion size, line width, filter scales) are in these canonical pixels, so a close-up
   and an arm's-length selfie are measured at the same scale.
2. **Linear light and log ratios.** sRGB is converted to linear light, and every feature
   is a **log ratio** against the same face's own skin: ln(R/G) for redness, −ln R for
   pigment, ln(luminance) for texture. A uniform change in exposure multiplies every
   pixel by a constant, which cancels exactly in a log ratio. Most of a global colour cast
   cancels the same way. So does a uniform difference in skin tone (melanin darkens skin
   multiplicatively), which is the main fairness mechanism.
3. **Illumination layer.** Shading from side light, or shadows from the nose and brow
   ridge, varies slowly across the face. A masked Gaussian blur of the skin
   (σ = 24 canonical px) estimates it, and spots and lines are measured against that
   *local* baseline rather than the face average.
4. **Per-face skin mask.** A pixel counts as skin only if it resembles this face's own
   median skin: not > 3× darker (hair, nostrils, deep shadow), not > 2.2× brighter, not
   specular shine, not saturated. It also needs at least half the face's own "warmth"
   (r − b chromaticity), which removes grey, blue and green objects such as glasses and
   grey hair, plus white glare. The colour test is deliberately **one-sided**: redder or
   browner than average is exactly what is being measured, so it is never masked out. (An
   early two-sided version removed rosy cheeks, i.e. the redness, from the skin mask.)

Thresholds that would otherwise behave differently on noisier photos are set **relative
to the face's own texture** (acne: a blob must be ≥ 8 robust SDs of that face's filter
response). Darker skin in poor light has more colour noise in log units, so a fixed
threshold would find more false lesions there.

**What normalisation can't fix.** Real lighting changes much more than the synthetic
tests suggest:
- **Same face, different rooms.** Four photos of one face moved redness and
  pigmentation by 21–25 points and wrinkles by 44 (see
  [Lighting consistency](#lighting-consistency)).
- **The synthetic tests understate this.** Re-rendering one photo with different
  exposure or white balance moved most scores by ≤ 2.5 points, so those numbers should
  **not** be cited as evidence of stability.
- **Why real light is different.** Its direction changes how visible pores and wrinkles
  are (raking light deepens them), which is physics, not a normalisation error. Camera
  tone curves, HDR and beauty filters alter the skin before we see it.
- **What the gate does.** Rejecting uneven and dim light removes the worst cases, but
  it doesn't make the scores lighting-invariant.

---

## How each score is measured

"Usable regions" means regions with ≥ 35% visible skin. Region weights are renormalised
over the usable ones.

### Redness, `redness_score`

- **Signal:** the erythema index EI = ln(R/G) in linear light. Haemoglobin absorbs green
  strongly and red weakly, so redder skin has higher R/G (Dawson et al. 1980; Diffey et
  al. 1984). The log ratio makes it independent of exposure.
- **Baseline:** the 30th percentile of EI over all of the face's skin, i.e. the person's
  own less-red skin.
- **Raw feature:** mean of max(0, EI − baseline) over the cheeks (weight 1 each) and the
  nose (0.6), after a σ=2 px smoothing so pixel noise doesn't inflate it.
- **Measures:** how much redder the cheeks and nose are than the rest of this face.
- **Can't measure:** uniform whole-face redness, because it raises the baseline too.
  Redness in melanin-rich skin is physically less visible in RGB, and EI only partly
  compensates. It can't tell rosacea from flushing, sunburn, makeup or a warm lamp on one
  side.

### Acne, `acne_score`

> **Unreliable, even on photos that pass the quality gate.** It shows no correlation with
> the human ratings (Spearman ρ 0.11, interval spanning zero). It swings widely with
> lighting (1–58 across four photos of one face). Mild lesions are not detected at this
> resolution. Treat it as a weak hint: it should not drive routine changes unless the
> questionnaire corroborates it.

- **Signal:** local redness contrast (EI minus a σ=10 px local average).
- **Detection:** multi-scale scale-normalised Laplacian-of-Gaussian blob detector
  (σ = 1.5, 2.5, 3.5 px ≈ lesions 2–5 mm across), local maxima in a 9 px window.
- **A blob counts if:** its response is ≥ 0.04 *and* ≥ 8 robust SDs of this face's
  responses, its centre is ≥ 0.06 log units redder than its surroundings, and it is
  **redder than it is dark** in the red channel. Brown spots also look slightly red, and
  JPEG colour subsampling makes small red spots look slightly dark, so the ratio decides
  which effect dominates.
- **Raw feature:** lesions per 10,000 canonical px² of usable skin (cheeks, forehead,
  chin), pooled over regions.
- **Can't measure:** comedones (black/whiteheads), raised-ness (a single 2-D photo gives
  no depth), mild lesions (see injection recall below), acne under makeup or a beard.
  It also can't tell acne from other small red bumps (folliculitis, insect bites,
  vessels).

### Pigmentation, `pigmentation_score`

- **Signal:** "darkness in the red channel", −ln R. Melanin absorbs red light;
  haemoglobin barely does. So brown spots register here and red acne/flushing mostly
  does not.
- **Spots (weight 0.6):** pixels ≥ 0.08 log units darker than skin within ~10 px,
  grouped into blobs of 6–300 px. Blobs elongated beyond 3.5 (folds, lines) or more red
  than dark (lesions) are dropped. The feature is the share of skin covered by spots.
- **Unevenness (weight 0.4):** robust SD (1.4826 × MAD) of red-channel darkness against
  the broader σ=24 px baseline, i.e. blotchiness.
- **Regions:** cheeks, forehead, chin (0.5).
- **Can't measure:** dark circles (the under-eye is excluded, since it's mostly
  shadow). Stubble and freckles count as spots. It can't tell melasma from
  post-inflammatory hyperpigmentation from moles. Very large patches (> 300 px) are
  treated as shadow.

### Pores, `pore_score`

- **Signal:** difference of Gaussians on ln(luminance) (σ 0.8 → 2.0 px), dark side
  only: the average depth of fine dark texture.
- **Regions:** nose (1.0), cheeks (0.7 each).
- **Honest caveat:** at the funnel's 720 px resolution a face is ~300 px wide, about
  0.5 mm per pixel. Individual pores (0.05–0.5 mm) are at or below one pixel, so this
  score really measures **fine skin texture / roughness**, which enlarged pores
  contribute to. It is strongly affected by camera sharpness, noise, JPEG compression
  and beauty filters (smoothing lowers it). Compare a person's scores over time, taken
  with the same phone, rather than across people.

### Wrinkles, `wrinkle_score`

- **Signal:** a bank of 8 elongated Gabor filters (σ 2.2 px, wavelength 6 px, aspect
  0.4) on ln(luminance), tuned to thin dark lines.
- **Oriented contrast:** strength = best orientation − mean over all orientations. A
  line excites one orientation; pores and texture excite all of them about equally.
  (A connected-component "line length" filter was tried first and was non-monotonic:
  raising the threshold *increased* detections, as texture networks broke into
  line-shaped fragments.) On the forehead only near-horizontal orientations (±35°)
  count, which ignores hair strands and frown lines.
- **Raw feature:** share of each region where strength ≥ 0.05, specks under 6 px
  dropped. Weights: forehead 1.0, crow's feet 0.5 each, under-eye 0.4 each. The
  under-eye band starts one landmark ring below the lid, so lashes and the lid margin
  aren't counted.
- **Can't measure:** depth or permanence. Expression lines count: **smiling** deepens
  crow's feet and under-eye lines, hence the soft warning. Strong raking light also
  raises it, as do hair strands on the forehead outside the ±35° band.

---

## Calibration

There is no ground truth, so each raw feature → score mapping is a **piecewise-linear
curve through hand-set anchors** (`SCORE_ANCHORS` in `scoring_config.py`).

**Development images.** Two public MediaPipe test portraits: `business-person.png`
(stock photo, light skin, retouched, slight smile) and `portrait.jpg` (public-domain
official portrait, dark skin, sharp, broad smile). Both were cropped to selfie framing
and re-encoded at ≤ 720 px, JPEG q85, like the funnel's uploads. Neither has visible acne
or rosacea. They were used only locally and are not in the repo. Two faces is a very small
calibration set, and the anchors should be revisited with more photos.

**Anchor rules.** Faces without visible conditions should land in the low-to-moderate
band. Upper anchors are where synthetic lesions injected into those faces push the raw
feature. Acne anchors loosely follow lesion-count severity bands (Hayashi et al., 2008)
scaled to the measured area.

**Synthetic-lesion injection** (`tests/test_with_samples.py` does the same on your
selfies). 15 small lesions (~3.5 mm across) are painted in linear light at fixed cheek,
forehead and chin landmarks. Red papules absorb mostly green/blue; brown spots absorb
across all channels, more at short wavelengths. "Detected" means a detection within 6
canonical px of the site.

| Injected | Strength | Light-skinned face: detected / score | Dark-skinned face: detected / score |
|---|---|---|---|
| none | | acne 17, pigmentation 12 | acne 19, pigmentation 40 |
| red papules | 0.1 (faint) | 0/15, acne 17 | 0/15, acne 19 |
| red papules | 0.2 | 5/15, acne 43 | 0/15, acne 19 |
| red papules | 0.35 (clear) | 13/15, acne 95 | 12/15, acne 54 |
| brown spots | 0.15 | 9/15, pigmentation 21 | 8/15, pigmentation 45 |
| brown spots | 0.3 | 14/15, pigmentation 45 | 11/15, pigmentation 53 |

What this shows, and what it doesn't:

- Faint lesions are invisible to the detector at this resolution. Moderate ones are
  found on smooth skin but **not on the darker, more textured face**: the per-face
  threshold adapts to that face's texture. The trade-off was deliberate: without it,
  that face produced 15–55 false "lesions" with no acne present.
- The same 13–15 lesions raise the score more on the light-skinned face (95 vs 54),
  partly because glare holes reduced its measurable area, so each lesion counts for more
  density.
- Injected lesions are Gaussian blobs, not real acne, so this tests the detector's
  mechanics, not its clinical validity.

---

## Lighting consistency

`check_lighting_consistency.py` scores several photos of **the same face** taken under
different lighting and reports mean / min / max / spread / SD per score. With no ground
truth, this is the main evidence about lighting sensitivity, and it shows the scores are
**not** lighting-invariant.

The script analyses each photo twice. First as the API would, with the lighting gate on,
to show which photos get rejected. Then in an analysis-only mode with the gate off
(`ImageAnalyzer.analyze(..., lighting_gate=False)`), so rejected photos still have scores
to compare. The public `analyze_image()` and the endpoint have no way to switch the gate
off.

### Real photos (4 photos of one face, different lighting)

Four photos of the same person under different lighting (`samples/lighting/`,
gitignored). Run with:

```bash
python -m app.services.image_analysis.check_lighting_consistency --synthetic --markdown
```

Scores are from the analysis-only mode, so the rejected photos still show what they
would have scored. Re-run in 7b-ii at the
[canonical resolution](#canonical-resolution-step-7b-ii) (720 px; these originals are
960×1280):

| photo | API decision | acne | redness | wrinkle | pigmentation | pore | exposure L\* (reference) | cheek ratio |
|---|---|---|---|---|---|---|---|---|
| 1 | **rejected: uneven light** | 11 | 47 | 47 | 49 | 25 | 72 (eye whites) | 3.13 |
| 2 | pass | 1 | 29 | 4 | 40 | 13 | 74 (eye whites) | 1.24 |
| 3 | **rejected: uneven light** | 16 | 37 | 20 | 52 | 20 | 65 (scene highlights) | 3.12 |
| 4 | **rejected: too dim** | 61 | 27 | 21 | 65 | 28 | 35 (scene highlights) | 1.64 |

| score | spread, all 4 photos (gate off) |
|---|---|
| acne | **60** (1–61) |
| redness | 20 (27–47) |
| wrinkle | **43** (4–47) |
| pigmentation | 25 (40–65) |
| pore | 15 (13–28) |

Raw features behind those scores:

| photo | redness (EI excess) | acne (per 10k px) | spot fraction | unevenness | pore darkness | wrinkle line density |
|---|---|---|---|---|---|---|
| 1 | 0.125 | 1.46 | 0.021 | 0.084 | 0.0065 | 0.111 |
| 2 | 0.081 | 0.00 | 0.004 | 0.104 | 0.0032 | 0.005 |
| 3 | 0.101 | 2.10 | 0.012 | 0.116 | 0.0049 | 0.030 |
| 4 | 0.078 | 7.38 | 0.030 | 0.112 | 0.0073 | 0.032 |

What this shows:

- **Real lighting moves the scores a lot, with the gate off.** Redness and pigmentation
  shift 20–25 points across the four photos, and wrinkles 43. That is far more than the
  ≤ 2.5 points the synthetic tests suggested.
- **The gate removes the two side-lit photos** (cheek ratio 3.1, over the 2:1 limit):
  the wrinkle outlier (photo 1: raking light, line density 4–20× the others) and a
  redness/pigmentation high.
- **Photo 4 is now rejected as too dim.** In 7a, at full 960×1280, it passed: its eye
  whites gave a reference L\* of 43. At 720 px, the eye-white reference is no longer
  accepted, so the scene highlights are used instead (L\* 35, below the 38 limit). Its
  7 acne-like spots per 10k px against 0 elsewhere had already looked like low-light
  colour noise. Whether this photo passes depends on which white reference is chosen;
  see [Canonical resolution](#canonical-resolution-step-7b-ii).
- **Only one photo passes the gate, so no "stable under good light" spread can be
  shown.** The 7a figures (two passing photos: redness 2 points apart, wrinkles 16) were
  measured at the old resolution. Either way, the scores are not lighting-invariant.

### Synthetic changes on the same four photos

Mean absolute score change vs. the unmodified photo, gate off, re-run at the canonical
720 px in 7b-ii. The last column counts how many of the 4 the gate would reject; 3 of
the originals are already rejected (2 for uneven light, photo 4 as too dim).

| Change | acne | redness | wrinkle | pigmentation | pore | gate rejects |
|---|---|---|---|---|---|---|
| exposure ×0.5 | 8.8 | 1.5 | 2.0 | 1.2 | 1.0 | 3 of 4 |
| exposure ×0.7 | 9.5 | 1.2 | 0.8 | 0.8 | 1.2 | 3 of 4 |
| warm white balance | 13.5 | 0.8 | 1.8 | 1.2 | 0.2 | 3 of 4 |
| cool white balance | 7.8 | 2.2 | 0.8 | 4.0 | 1.2 | 2 of 4 |
| tone curve γ 0.8 | 12.2 | 7.0 | 8.0 | 10.5 | 2.8 | 2 of 4 |
| tone curve γ 1.25 | 20.8 | 14.2 | 6.2 | 15.2 | 6.5 | 3 of 4 |
| side light (50% → 100%) | 6.5 | 2.0 | 4.0 | 3.2 | 1.5 | 3 of 4 |
| darken every pixel (×0.21 / 0.24 / 0.30) | 14.2 | 2.0 | 1.2 | 3.8 | 1.0 | 4 of 4 |

At 720 px acne moves more under these changes than it did at full resolution (e.g.
warm white balance 13.5 vs 4.2). The other four scores move about as much as before.

- **These synthetic numbers understate real-world variation and should not be cited as
  evidence of stability.** Re-rendering one photo can't reproduce what different real
  light does: shadow direction, shine, the camera's own exposure and processing, noise.
  The real-photo spreads above (21–25 points for redness and pigmentation, up to 44 for
  wrinkles) are the honest measure.
- **"Darken every pixel" was earlier labelled "simulated darker skin tone".** It also
  darkens the eye whites, so it is really an underexposed photo, and the gate correctly
  rejects all four as too dim. It still shows that uniform darkening barely moves
  redness, wrinkles and pores. That is the log-ratio design working, not a fairness
  result.

### Synthetic changes on the two development faces

Each photo is re-rendered with a controlled change in linear light, re-encoded as JPEG
q85, and re-scored. Table: **mean absolute score change** vs. the unmodified photo.

| Change | acne | redness | wrinkle | pigmentation | pore | rejected |
|---|---|---|---|---|---|---|
| exposure ×0.5 | 0.5 | 2.0 | 1.5 | 4.0 | 6.0 | 0 |
| exposure ×0.7 | 7.0 | 2.0 | 2.5 | 2.5 | 4.0 | 0 |
| warm white balance | 16.0 | 0.0 | 2.0 | 1.0 | 1.0 | 1 |
| cool white balance | 9.0 | 2.0 | 1.0 | 2.5 | 1.5 | 0 |
| tone curve γ 0.8 | 3.5 | 6.0 | 5.5 | 3.5 | 1.5 | 0 |
| tone curve γ 1.25 | 5.5 | 10.0 | 5.5 | 4.5 | 2.5 | 0 |
| side light (50% → 100%) | 10.5 | 0.5 | 1.0 | 2.5 | 3.5 | 0 |
| simulated darker skin tone | 6.5 | 1.0 | 1.0 | 3.0 | 9.5 | 0 |

Computed before the lighting gate existed; "rejected" refers to the rules at the time.
The one rejection was "overexposed": the warm cast saturated an already bright photo.

Reading it:

- **This is a controlled test of the normalisation's maths, not evidence of real-world
  stability.** Most scores moved ≤ 2.5 points here, but four real photos of one face
  moved redness and pigmentation by 21–25 points and wrinkles by 44. The synthetic
  numbers understate real variation and should not be cited as evidence of stability.
- **The tone curve is the main residual** (redness ±6–10): gamma rescales log contrasts.
- **"Simulated darker skin tone"** darkens every pixel, eye whites included, so it is
  really an underexposed photo. Redness, wrinkles and pigmentation move ≤ 3 points, which
  is the log-ratio design working. Pores move ~10, because 8-bit quantisation and noise
  are larger in darker pixels.
- **Acne** is the least stable (0.5–16 points), consistent with its being unreliable.
- **Synthetic darkening is not a substitute for testing on real people with different
  skin tones.** Real melanin also reduces how visible redness and spots are, which no
  re-rendering simulates. The spec's per-subgroup validation (§6) still needs a diverse
  labelled set.

---

## Skin-type classifier (Part 3)

A pretrained EfficientNet-B0 (torchvision, ImageNet weights) fine-tuned to predict skin
type from the same aligned face crop the scores use.

**Outcome in brief:**
- **Leak-free split: chance level.** After removing duplicate photos so that no copy
  appears in both training and test data, test accuracy is **0.309** and macro-F1
  **0.287**, against 0.25 chance and a 0.31 majority baseline.
- **Uploaders' own split: 0.763.** The same model scores **0.763** accuracy there,
  because at least 68% of those test images have a copy in the training folders.
- **Implication for published results.** Reported accuracies on these datasets (91–98%)
  were most likely measured on splits with the same leak. They show that the model
  recognises photos it has already seen, not that skin type can be read from a face.
  On a leak-free split, these labels can't be predicted.
- **Per-subgroup (skin-tone) validation was NOT achieved.** Of the 259 test images, 188
  had unknown tone, 54 were lighter and **only 17 were darker**, far too few to validate
  anything per subgroup. Darker skin is about 6% of all usable images.
- **Not served.** `skin_type_prediction` stays `null`, the startup log says why, and skin
  type comes from the questionnaire (7b).

### Data

Two Kaggle datasets, merged. Both are exports from Roboflow (an image-labelling
platform):

| | A: "Oily, Dry and Normal Skin Types Dataset" (Shakya Dissanayake) | B: "Facial Skin Analysis and Type Classification" (Bekhzod Olimov) |
|---|---|---|
| Files | 3,152 (137 MB) | 4,093 (172 MB) |
| Labels | dry, normal, oily | combination, dry, normal, oily |
| Unique source images (by filename) | 1,124 | 1,620 (791 also in A) |
| Stated licence | Apache 2.0 | Apache 2.0 |
| Extra | | 0–5 human ratings for ~200 images |

- **Licence caveat.** The images appear to have been collected from the web by the
  uploaders, and no source is given, so the stated Apache 2.0 licence is doubtful.
  They are used here for non-commercial academic work only. Neither the images nor the
  trained weights are redistributed (both gitignored).
- **Label mapping.** dry, normal, oily and combination map to our labels directly.
  **"Sensitive" has no training data:** no public image dataset labels it, and
  sensitivity (skin reactivity) isn't visible in a photo. It should come from the
  questionnaire (7b). A served classifier would therefore report
  `skin_type_labels_supported: ["combination", "dry", "normal", "oily"]`. While it isn't
  served (see Results), the list is empty.
- **Label quality.** The labelling process is undocumented (no dermatologist or
  instrument measurement), and some copies of the same photo carry different labels.

**Expected folder layout** (gitignored; "Extract here" on each Kaggle zip):

```
datasets/
├── Oily-Dry-Skin-Types/               (A)  train|valid|test / dry|normal|oily / *.jpg
└── skin_type_classification_dataset/  (B)  train|valid|test / combination|dry|normal|oily / *.jpg
                                            + skinalaysis_labeling_train1.xlsx, skinanalysis_valid1.xlsx
```

### Duplicate grouping and a leak-free split

The uploaders made up to 7 augmented copies of each photo, and B's own split puts copies
of 786 of its 1,620 source photos in more than one split. A model evaluated on B's split
would be tested partly on photos it trained on, which probably explains published 91–98%
accuracies on these datasets. So copies are grouped first, and whole groups are split
(`skin_type_data.py`):

1. **pHash under all 8 flips/90° rotations** links exact copies, flips, 90° rotations,
   recompression, recolouring and Roboflow's stretch-to-square (distance ≤ 6 of 64 bits).
2. **pHash alone is not enough.** Measured on synthetic copies, a 20–30% re-crop or a
   10–15° rotation lands 20–27 bits away, the same distance as a *different person*
   (26). So for each image the 8 most similar images by an ImageNet CNN embedding (made
   rotation- and mirror-insensitive) are retrieved. Each candidate pair is then
   **verified geometrically with ORB keypoints + RANSAC**: copies share 100–500+
   consistent keypoints, different photos a handful. The pair is linked at ≥ 50.
   - **Black padding must be ignored.** Many Roboflow copies are rotated onto black
     canvases, and the first full run didn't account for that. The padding dominated
     the low-frequency pHash, and its edges gave ORB matches between unrelated photos.
     Because links are transitive, a few false links **chained 760 different photos
     into one "group"**, and 1,503 images were wrongly dropped as "conflicting".
   - **The fix.** pHash is computed on the content's bounding box, with leftover
     corner triangles filled with the content's median colour. ORB keypoints are only
     taken on content, at least 8 px from any padding. On synthetic tests, two different
     images rotated by the same angle went from 5 bits apart to 27.
   - **The thresholds** (pHash ≤ 6, ORB ≥ 50) were then chosen on the real data. Pairs
     sharing a Roboflow filename id served as known copies: 97.7% of those pass. Different-
     id pairs that pass mostly scored far above the threshold, and when inspected they
     were the same photo re-uploaded under another id. Regression tests cover both
     padding failure modes.
3. **Cross-check.** The image-based groups are compared with the source id Roboflow left
   in the filenames, and both kinds of disagreement are reported: copies the images
   didn't match, and image matches across different ids. The **final grouping links two
   images if either method says they're copies**, erring towards no leakage.
4. **Conflicting labels.** A group whose copies carry different labels is dropped
   entirely.
5. **Split.** One representative per group (the copy with the largest detected face)
   goes into a 70/15/15 split, stratified by label at the group level and seeded. The
   script prints a leakage check: shared groups, shared filename ids and pHash
   near-duplicate pairs between every pair of splits, all of which must be zero, plus an
   ORB check of every cross-split pair within 12 pHash bits. It also saves sample pairs
   to `datasets/_reports/dedup_sample_pairs.jpg` for eyeballing.

**Results on the real data:**

| | Count |
|---|---|
| Images found (A + B) | 7,245 (3,152 + 4,093) |
| Source groups by filename id alone | 1,953 |
| … by pHash alone | 4,089 |
| … by images (pHash + ORB) | 2,016 |
| **Final groups** (images *or* filename say "copy") | **1,847** |
| Links: pHash / ORB-verified (of 36,403 candidate pairs checked) | 4,354 / 11,488 |
| Strongest rejected ORB pair | 49 inliers (threshold 50) |
| Filename groups the images split apart (rejoined by filename) | 159 |
| Image groups spanning several filename ids (copies re-uploaded under new ids) | 92 |
| **Groups with conflicting labels, dropped** | **57 groups (519 images)** |
| Clean groups | 1,790 (combination 174, dry 531, normal 560, oily 525) |
| Largest groups | 35, 23, 22, 21, 20 images |
| Groups with no detectable face in any copy, excluded | 68 |
| **Split** (one image per group) | **train 1,204 / val 259 / test 259** |

- **Largest groups.** Checked by eye, they are genuine. The biggest is one close-up
  uploaded under 6 filename ids. Another is a single eye close-up that the uploaders
  labelled **normal 11 times, oily 9 times and dry 3 times**. Most of the 57 conflicting
  groups are like that: the same photo carrying different labels, which is real label
  noise in the datasets.
- **Sample-pair sheet.** All 10 pairs are genuine copies, including the hardest accepted
  links (exactly 50 inliers): rotated, re-cropped and recoloured versions, plus a
  re-crop labelled "normal" in one copy and "oily" in another.

**Leakage check** (all copies of every usable group):

| | shared groups | shared filename ids | pHash pairs ≤ 6 bits | closest pair |
|---|---|---|---|---|
| train vs val | 0 | 0 | 0 | 7 bits |
| train vs test | 0 | 0 | 0 | 7 bits |
| val vs test | 0 | 0 | 0 | 9 bits |

An extra audit ORB-checked all **692** cross-split pairs within 12 pHash bits. The highest
score was **14 inliers**, against 50 for a copy. The twelve closest were inspected by eye:
all are *different* photos, typically different people framed alike on white
backgrounds. Sheet: `datasets/_reports/cross_split_closest_pairs.jpg`.

**Comparison with the first run.** Before the black-padding fix, the same data gave a
largest "group" of 760 images and 73 conflicting groups (1,503 images). After it, the
largest is 35 and there are 57 conflicting groups (519 images).

### Training

- **Inputs.** The live service's own detector and alignment (`skin_type.classifier_input`,
  letterboxed to 224 px), so training and serving see identical crops. Groups with no
  detectable face in any copy are excluded and counted.
- **Model.** EfficientNet-B0, ImageNet weights, new 4-way head. AdamW (backbone 2e-4,
  head 1e-3), 1-epoch warm-up then cosine decay, up to 30 epochs, bf16 mixed precision on
  the GPU.
- **Class imbalance** (combination is ~3× rarer). Class-weighted cross-entropy (inverse
  frequency) plus 0.1 label smoothing.
- **Augmentation.** Deliberately mild: re-crop 75–100%, flips, ±8°, small brightness,
  contrast and colour changes. Strong colour changes would erase the shine and dullness
  cues that skin type shows up as.
- **Model selection.** Best validation **macro-F1**, early stopping after 8 epochs
  without improvement. The **test split is used exactly once**, after training.
- **Reported.** Accuracy, macro-F1 and balanced accuracy (each with a 95% bootstrap
  interval), per-class precision/recall/F1, the confusion matrix, the majority-class
  baseline, and the subset of test photos the live service would accept.
- **Output.** `weights/skin_type_efficientnet_b0.pt` (loaded with
  `torch.load(weights_only=True)`, which accepts only tensors and plain data, never
  arbitrary pickled objects), plus `skin_type_report.md`/`.json` and the split manifest.

### Results

Model `effnetb0-20261002-60bbf302`, seed 42. Early stopping ended training at epoch 14;
the best validation macro-F1 was at epoch 6. Test split (259 images, used once):

| Metric | Value | 95% bootstrap CI |
|---|---|---|
| Accuracy | **0.309** | 0.255–0.363 |
| Macro-F1 | **0.287** | 0.229–0.342 |
| Balanced accuracy (mean per-class recall) | 0.294 | |
| Majority-class baseline accuracy | 0.313 | |
| Chance (4 classes) | 0.25 | |

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| combination | 0.171 | 0.231 | 0.197 | 26 |
| dry | 0.346 | 0.237 | 0.281 | 76 |
| normal | 0.347 | 0.432 | 0.385 | 81 |
| oily | 0.296 | 0.276 | 0.286 | 76 |

Confusion matrix (rows = true, columns = predicted):

| | combination | dry | normal | oily |
|---|---|---|---|---|
| **combination** | 6 | 6 | 7 | 7 |
| **dry** | 10 | 18 | 27 | 21 |
| **normal** | 8 | 16 | 35 | 22 |
| **oily** | 11 | 12 | 32 | 21 |

Of the 259 test images, 154 would pass the live service's quality checks. On those,
accuracy is 0.305 and macro-F1 0.295.

**The classifier performs at chance.** Training loss fell from 1.42 to 0.55, so the
model learned the training images, but validation macro-F1 stayed at 0.19–0.30
throughout. On a leak-free split, these labels can't be predicted from the face crop.

**Control experiment** (`naive_split_control.py`). Same model, same settings, same
seed, but trained and tested on the uploaders' own train/valid/test folders, keeping
all copies:

| Split | Test n | Accuracy | Macro-F1 |
|---|---|---|---|
| Leak-free (our deduplicated group split) | 259 | **0.309** | **0.287** |
| Uploaders' folders (copies in train *and* test) | 514 | **0.763** | **0.720** |

At least **68%** of the uploaders' test images (368 of 543) have a same-filename-id copy
in their train folders, and image matching finds more. The 0.76 is therefore mostly
recognition of photos the model has already seen. This also probably explains published
91–98% accuracies on these datasets. It confirms the pipeline is able to learn (no bug),
and that the leak-free number is the honest one.

**Why the labels may not be learnable:**
- **Noisy labels.** The same photo is labelled differently across uploads (57
  conflicting groups). The labels were probably assigned per web search or folder, not
  per person.
- **Subtle, condition-dependent cues.** Oiliness shows as shine, which depends on
  lighting and time since washing. Dryness shows as flaking or dullness, hard to see
  at this resolution.
- **Small, varied data.** 1,204 training photos across stock portraits, close-ups and
  selfies.

**Not served.** A classifier at chance would give users random skin types. So
`skin_type.py` only serves a model whose held-out test macro-F1 is credibly above chance
(the lower end of its 95% CI above 1/number-of-labels). This one fails (lower end 0.229
vs 0.25), so the service loads it, logs `skin-type classifier ... NOT served: ...`, and
returns `skin_type_prediction: null`. The checkpoint, report and split manifest stay in
`weights/`. Setting `REQUIRE_ABOVE_CHANCE = False` in `skin_type.py` serves it anyway
(e.g. to demo the plumbing). The questionnaire (7b) remains the source of skin type.

### Skin-tone breakdown

The plan was ITA° (Individual Typology Angle, from L\* and b\*). On these web photos it
is **invalid**: L\* depends on exposure, and halving the exposure moved one face from
65° to −21°. A brightly lit dark-skinned face read as "light".

The breakdown therefore uses **skin luminance relative to a white reference in the same
photo**: the eye whites, or the teeth when smiling. That ratio cancels exposure (stable
within ±0.02 when exposure was cut 4×).
- **Valid reference:** near-neutral (chroma ≤ 0.25), brighter than the skin, and not
  clipped. This rejects lips and squinted eyes.
- **Groups:** lighter if skin/white ≥ 0.55, darker if below. The threshold sits between
  the two development faces (light skin 0.72, dark skin 0.44).
- **No valid reference:** the face is "tone unknown", reported separately, never guessed.

It is a coarse proxy: recoloured variants of one face spread over about ±0.13.
Manually annotating the test set with the Monk Skin Tone scale would be the stronger
method.

**Results** (test split, 259 images):

| Tone bucket | Test images | Accuracy | Macro-F1 |
|---|---|---|---|
| lighter (skin/white ≥ 0.55) | **54** | 0.352 | 0.313 |
| darker (skin/white < 0.55) | **17** | 0.353 | 0.304 |
| tone unknown (no usable eye white or teeth) | **188** | 0.293 | 0.281 |

Across all 1,722 usable images: lighter 374, darker 97, unknown 1,251.

- **Mostly unknown.** 73% of test images have no usable white reference. Many are skin
  close-ups or stock shots with closed eyes or closed mouths.
- **The classifier is at chance in every bucket**, so this breakdown can't show a
  skin-tone gap in performance; there is no performance to compare.
- **Per-subgroup validation was not achieved.** Darker skin is badly under-represented:
  17 of the 259 test images and 97 of the 1,722 usable ones. The spec's fairness NFR
  (§6) requires per-subgroup validation, and these data can't provide it, even for a
  working classifier.

### Heuristic scores vs. the 0–5 human ratings

`evaluate_against_ratings.py` scores dataset B's rated images with the service and
reports **Spearman rank correlation** per attribute, with 95% bootstrap intervals.

**The rated set.**
- **Size and spread.** Two spreadsheets rate 200 entries, 199 distinct images (one ID
  is listed twice), drawn from B's train (150) and valid (50) folders and balanced over
  oily (67), dry (67) and normal (66). No combination images are rated.
- **ID quirk.** The train sheet leaves `.jpg` off most image IDs, so the script falls
  back to adding it. All 199 images were then found.
- **Rejected photos.** With the lighting gate, **59** of the 199 are refused by the
  service's quality checks, against 44 before dim and uneven light became hard
  rejections. So **140 are scored**. (An image can fail several checks.)

| Reason | Images |
|---|---|
| uneven light (new hard check) | 17 |
| overexposed | 12 |
| face too small | 11 |
| face partly out of frame | 10 |
| head turned/tilted | 7 |
| no face | 2 |
| more than one face | 1 |

No rated image was rejected as too dim. The gate's rejections by coarse skin tone are in
[The lighting gate and skin tone](#the-lighting-gate-and-skin-tone).

**Results** (nothing tuned on these images). The main column uses the photos that pass
the gate, as the API would. The comparison column scores the same set with the lighting
gate off, i.e. the previous rules.

| Our score | Rating column | ρ, gate on (n = 140) | 95% CI | ρ, gate off (n = 155) |
|---|---|---|---|---|
| acne | acne severity | **0.11** | −0.07 to 0.28 | 0.10 |
| redness | redness severity | **0.27** | 0.11 to 0.44 | 0.31 |
| pores | open pores | **0.33** | 0.17 to 0.47 | 0.33 |
| wrinkles | mean of "fine line around eyes" + "wrinkes on forehead" (sic) | **0.28** | 0.10 to 0.43 | 0.27 |
| ↳ | fine lines around eyes alone | 0.25 | 0.07 to 0.40 | 0.24 |
| ↳ | forehead wrinkles alone | 0.28 | 0.11 to 0.42 | 0.28 |
| pigmentation | "dark spots" (train sheet) / "pigmentation" (valid sheet), merged* | **0.25** | 0.09 to 0.40 | 0.27 |

\* The two sheets name this column differently and never fill both for one image, so
they are treated as one attribute.

What this shows:
- **Four scores are weakly correlated with the ratings.** Redness, pores, wrinkles and
  pigmentation all have intervals clear of zero.
- **Acne is not.** Its interval spans zero with or without the gate. That matches the
  other findings: mild lesions go undetected, and colour noise is counted as lesions.
- **Correlations of 0.25–0.33 are weak.** They show the heuristics move in the same
  direction as a human's judgement; they don't show the scores are accurate.
- **The lighting gate doesn't change these correlations** (differences of ±0.04, well
  inside the intervals). On these mostly well-lit stock photos, the 15 extra rejected
  images were not what limited agreement.

**Caveats, stated plainly:**
- **Raters unknown.** Who rated these images, with what training and protocol, is
  undocumented.
- **Ordinal scale.** It's a 0–5 ordinal scale, so this is rank correlation, **not
  "agreement"**, and it is not the dermatologist validation the spec asks for.
- **Web photos, not selfies.** Many are stock-style portraits.
- **Nothing tuned on them.** No score mapping or feature was tuned on these images, so
  all 155 are held out. Spearman is unchanged by any monotonic re-mapping, so tuning the
  anchors couldn't change it anyway. If features are ever tuned on these ratings, tune on
  one half and report the other half only.

### Running it

From `backend/`:

```bash
pip install -r requirements-train.txt   # CUDA 12.8 PyTorch (~2.5 GB) + openpyxl
python -m app.services.image_analysis.train_skin_type --dedup-only   # grouping, split, leakage check
python -m app.services.image_analysis.train_skin_type                # full run (--fresh to redo everything)
python -m app.services.image_analysis.evaluate_against_ratings
python -m app.services.image_analysis.naive_split_control            # the leaky-split comparison
```

Training on the RTX 5050 took about 10 s per epoch. The whole run, including the
one-off signature pass over 7,245 images and face cropping, takes roughly 20–30 minutes.
The training script checks the GPU first (CUDA available, compute capability, a matmul compared
against the CPU) and refuses to train if it fails, unless `--allow-cpu` is given. The
whole pipeline is seeded and re-runnable. Cached signatures and face crops live in
`datasets/_cache/` (delete it or pass `--fresh` to recompute).

### Installing PyTorch with CUDA (training only)

The RTX 5050 (Blackwell, sm_120) needs a CUDA 12.8+ build of PyTorch. Those wheels come
from PyTorch's own index (~2.5 GB), so they live in **`requirements-train.txt`**, not
`requirements.txt`. It pins `torch==2.11.0+cu128` and `torchvision==0.26.0+cu128`, the
newest cu128 builds published for Python 3.14 on Windows. The `+cu128` versions exist
only on PyTorch's index, so pip can't silently fall back to a CPU wheel. Verified on this
machine: CUDA available, sm_120 kernels present, GPU matmul matches the CPU, and
EfficientNet-B0 runs on the GPU.

`requirements.txt` pins the same versions without the CUDA suffix, so a normal install
gets the CPU wheel from PyPI (Windows/macOS), and inference falls back to the CPU
automatically. On Linux, PyPI's torch wheel bundles CUDA libraries; for a slim CPU-only
Docker image, install torch from `https://download.pytorch.org/whl/cpu`.

---

## Canonical resolution (step 7b-ii)

**Every photo is analysed at a longest side of at most 720 px.** Before any quality
check or measurement, `ImageAnalyzer.analyze()` shrinks the decoded image in memory
(`decode.to_canonical_resolution`: `cv2.INTER_AREA`, exact target size, never
enlarges). Every caller goes through it, including the API, the dev scripts and the
evaluation scripts. The setting is `CANONICAL_MAX_SIDE` in `scoring_config.py`, and the
service version went from 1.0.0 to 1.1.0.

**Why.** Every threshold here was calibrated on 720 px photos, but the service used to
analyse up to 1600 px. That made the client's resize part of the model: in 7b-i the
same photo (`lighting/4.jpeg`) passed at 720 px but was rejected as too dim at 960 and
1080 px.

**Effect.** `check_funnel_resolution.py` compares each photo as uploaded with what the
selfie page sends, plus some candidate settings, all through the public
`analyze_image()` with the gate on. The browser's resize and JPEG encoder are
approximated with Pillow (bilinear, same nominal quality). On the project's 6 photos
(960×1280 originals), each cell is the largest |difference| from the full-size photo:

```bash
python -m app.services.image_analysis.check_funnel_resolution
```

| Variant | Base64 payload | Decision changed | acne | redness | wrinkle | pigment | pore |
|---|---|---|---|---|---|---|---|
| 720 px, q85 (the selfie page until 7b-ii) | 41-80 KB | 1 of 6 | 6 | 1 | 3 | 2 | 1 |
| **720 px, q92 (the selfie page from 7b-ii)** | 60-111 KB | 1 of 6 | 15 | 1 | 1 | 1 | 1 |
| 960 px, q85 | 68-128 KB | 0 of 6 | 3 | 1 | 1 | 3 | 0 |
| 1080 px, q90 | 114-199 KB | 1 of 6 | 3 | 1 | 2 | 2 | 0 |

The same photo sent at 720, 960 and 1080 px (bilinear, JPEG q92, as a browser would
send it) is checked by `tests/test_canonical_resolution.py`:

| Photo | Decision at 720 / 960 / 1080 px | Largest change from 720 px: redness, wrinkle, pigment, pore | acne |
|---|---|---|---|
| 1.jpeg | pass / pass / pass | 0, 1, 4, 1 | 14 |
| 2.jpeg | pass / pass / pass | 0, 1, 2, 2 | 0 |
| lighting/1.jpeg, lighting/3.jpeg | uneven light (all three) | — | — |
| lighting/2.jpeg | pass / pass / pass | 1, 1, 1, 0 | 0 |
| **lighting/4.jpeg** | **pass / too dim / pass** | 0, 0, 3, 1 (1080 vs 720) | 4 |

- **The four image-primary scores now agree within 4 points** across sizes, and every
  decision but one is the same. The test asserts ≤ 4 for those scores and ≤ 20 for acne,
  which is documented as unstable. An exact 2× upscale gives an identical result.
- **The one remaining flip is not about resolution.** Every variant of
  `lighting/4.jpeg` is now analysed at 720 px. On this dim, noisy photo, the dim check's
  white reference switches between two sources:

  | Variant | Reference used | L\* |
  |---|---|---|
  | 720 px, q92 | eye whites | 41.4 |
  | 1080 px, q92 | eye whites | 42.5 |
  | 960 px, q92 | scene highlights | 35.3 |
  | full size | scene highlights | 35.3 |

  Which one wins depends on resampling and JPEG noise. That's a robustness issue in
  the 7a lighting gate's reference selection, and it is **not fixed here**: fixing it
  would mean re-validating the gate, not changing the resolution. The test marks this
  photo `xfail`, with the measured references in the reason.
- **Well-lit photos are stable:** their reference L\* varies by at most 2.6 across all
  the variants.
- **Not affected:** the 199 rated dataset images used for the Spearman correlations are
  640 px, and the dim-threshold calibration used 720 px photos. The canonical step
  doesn't change either of them.
- **Selfie page (7b-ii):** still at most 720 px, with the JPEG quality raised to 0.92.

---

## Performance

Measured on the development machine (Intel i7-13620H, CPU only; MediaPipe runs on CPU
via XNNPACK), on 720 px funnel-style JPEGs:

| | Time |
|---|---|
| Model load (once, at startup) | ~40 ms (plus ~0.5 s to import MediaPipe/OpenCV) |
| `analyze_image`, median of 20 runs | 96–174 ms |
| `analyze_image`, worst of 20 | 107–233 ms |
| Through HTTP (uvicorn, localhost) | 110–320 ms |
| OpenCV limited to 1 thread | 98–179 ms median |

Stage split for a typical call: face landmarks ~15 ms, alignment + checks ~25–35 ms,
scoring ~60–130 ms (the Gabor bank dominates). That is well inside the spec's 3–5 s
target, with plenty of headroom for slower machines.

The skin-type classifier is currently not served (it performs at chance). If served, it
would add about 110 ms to startup and **~20 ms per request on the CPU** (18 ms on the
GPU). The service falls back to the CPU automatically when no GPU is present.

---

## Privacy

- **In memory only.** base64 → bytes → NumPy array → MediaPipe image. No temp files,
  nothing written to disk or the database. The only code that writes images is the dev
  tool `visualize_regions.py`, which reads photos you placed on disk and writes overlays
  into the gitignored `samples/_debug/`.
- **Never logged or echoed.** The service logs nothing about requests. Uvicorn's access
  log records only method, path and status (checked with a live server at debug log
  level). The endpoint parses the body itself so validation errors can't echo the image.
- **Tests guard this.** One test runs the analysis with `open(..., "w")`,
  `cv2.imwrite`, `PIL.Image.save` and every `tempfile` constructor patched to fail, and
  another checks that logs and every error response are free of the image data. (Native
  MediaPipe code can't be intercepted from Python; it is only handed an in-memory array.)
- **Decompression-bomb guard.** Image dimensions are read from the header and refused
  above 25 MP before any pixel memory is allocated.

---

## Known limitations

1. **No ground truth.** Every threshold and anchor is a judgement call checked on two
   public faces, synthetic perturbations, and four same-face photos under different
   lighting. Against dataset B's human ratings (raters unknown), four scores have weak
   positive rank correlations (ρ 0.25–0.33 on photos that pass the gate) and acne has
   none. The scores are
   consistent measurements of image properties that *relate* to these skin concerns. They
   are not diagnoses and not validated against dermatologists.
2. **Skin-tone fairness is argued and partly tested, not validated.** The log-ratio design
   removes uniform tone differences by construction, and the synthetic test confirms
   that except for pores. But real melanin also changes how visible redness and spots are,
   and only a labelled, skin-tone-diverse evaluation set could measure that. The dev set
   was one light-skinned and one dark-skinned face.
3. **Resolution.** At 720 px, pores are about one pixel and faint lesions are below
   detection. Higher-resolution uploads would help pores and acne most.
4. **Camera processing.** Tone curves, HDR, noise reduction and beauty filters change the
   skin texture before analysis. Scores are most meaningful when compared over time on
   the same phone.
5. **Expression and pose.** Smiling raises wrinkle scores (warned). Strong head turns are
   rejected; mild ones warned.
6. **Confounders the heuristics can't separate:** makeup (lowers almost everything),
   facial hair (raises pigmentation and acne), glasses (hide the under-eye/crow's-feet),
   tattoos, scars, moles, coloured lighting.
7. **Single photo, single moment.** Redness in particular varies with temperature,
   exercise and time of day.
8. **The acne score is unreliable, even on photos that pass the gate.** It shows no
   correlation with the human ratings (ρ ≈ 0.1, interval spanning zero) and swings
   widely with lighting (1–58 across four photos of one face, one of which passes the
   gate). Don't let it trigger routine changes unless the questionnaire corroborates it.
9. **Scores are not lighting-invariant.** Across four real photos of one face, redness
   and pigmentation moved 20–25 points and wrinkles 43 (synthetic re-renderings
   suggested ≤ 2.5 and understate this). The gate rejects dim and uneven light, which
   removes the worst cases. At the canonical 720 px, only one of those four photos
   passes, so how stable the scores are under good light can't be measured from them.
10. **Pigmentation mappings were calibrated on studio portraits; phone selfies read
    high.** The anchors were set on studio-lit portraits. On the project's selfies,
    pigmentation reads 41–66, with raw unevenness about 1.5× the studio portraits',
    probably phone noise and processing. **Recalibration is deferred**, so don't rely
    on absolute pigmentation levels from phone photos.
11. **Equal light, unequal precision.** The dim gate treats every skin tone the same
    under the same light (it measures the eye whites or teeth, not the skin). But in the
    calibration photos, darker skin's scores drifted more under moderate dimness (median
    up to 9.5 points vs 6.5 at the threshold), because darker pixels sit nearer the 8-bit
    floor. The gate limits this; it can't remove it.
12. **No working skin-type classifier, and no per-subgroup validation.** On a leak-free
    split, the public datasets' labels are not learnable (chance-level). Darker skin is
    about 6% of those images, and only 17 of the 259 test images, so per-tone validation
    was not achieved. A useful classifier would need better-labelled, more diverse data.
    Until then, skin type comes from the questionnaire.
13. **The dim decision can flip on a borderline photo.** On a dim, noisy photo, the dim
    check's white reference can switch between the eye whites and the scene highlights
    because of resampling or JPEG noise alone. Example: `lighting/4.jpeg` reads L\*
    41.4 (eye whites, 720 px) and 42.5 (eye whites, 1080 px) but 35.3 (scene highlights,
    960 px and full size), either side of the 38 limit (see
    [Canonical resolution](#canonical-resolution-step-7b-ii)). Not fixed: it needs the
    gate re-validated.
14. **The lighting-consistency result now rests on a single accepted photo.** At the
    canonical 720 px, only `lighting/2.jpeg` of the four same-face photos passes the gate:
    photos 1 and 3 are rejected for uneven light, and photo 4 as too dim (limitation 13).
    So the real-photo evidence shows how much lighting moves the scores with the gate off
    (redness and pigmentation 20-25 points, wrinkles 43). It can't show how stable they
    are across photos that pass. That needs more photos of one face in good, varied light.

---

## Testing

```bash
python -m pytest app/services/image_analysis        # from backend/
```

- **Always runs** (synthetic images generated in code): no face / too dark /
  overexposed / blurry / unreadable / decompression bomb rejected; every raw feature maps
  into 1–100 (including ±∞), NaN raises instead of inventing a score; output shape
  matches the contract and the endpoint's schema; 422 / 400 / 413 (including chunked) /
  503 responses; no disk writes; no image data in logs or error bodies.
- **Lighting gate** (synthetic values): the dim and uneven-light decisions at and either
  side of both thresholds (a hidden cheek can't count as uneven); both messages ask
  politely for a retake; the public `analyze_image()` takes only the image, so there is
  no way to switch the gate off through it.
- **Skin-type plumbing** (`tests/test_skin_type.py`, also synthetic): pHash ignores
  flips, 90° rotations, recolouring and stretch but keeps different images apart; ORB
  confirms a rotated, re-cropped, mirrored copy and rejects a different image;
  Roboflow filename ids parse correctly; the split is stratified 70/15/15, reproducible
  and shares no group; classifier preprocessing; a checkpoint round-trip on CPU; missing
  weights give `null` with a reason; the contract validates with a prediction.
- **Needs your selfies** (skipped while `samples/` is empty): real photos score within
  1–100 with the right shape, results are deterministic, a darkened copy is rejected as too
  dark and a blurred copy as too blurry, and synthetic red papules / brown spots raise
  the acne / pigmentation scores. A synthetic half-face shadow is rejected as uneven
  light; the analysis-only mode still scores it (with the issue as a warning); and the
  endpoint still rejects it even when the request asks for `"lighting_gate": false`.
  **All 9 pass on the project's two selfies**, so both are accepted by the new gate.
- **Canonical resolution** (`tests/test_canonical_resolution.py`):
  - **Always runs:** large images shrink to a 720 px longest side with the aspect ratio
    kept; small ones are never enlarged; the step is deterministic and idempotent; decode
    returns 720 px.
  - **With photos:** an exact 2× upscale gives an identical result. Each photo at 720 /
    960 / 1080 px (JPEG q92) gets the same decision, with the image-primary scores within
    4 and acne within 20. A photo whose white reference switches is reported as `xfail`.

**Adding your photos** (gitignored, never committed):

```
samples/
  selfie_1.jpg   ← 2-3 ordinary selfies: face the camera, neutral expression,
  selfie_2.jpg     reasonable light, face filling about half the frame
  lighting/
    window.jpg   ← 4-6 photos of the SAME face under different lighting
    lamp_side.jpg  (for check_lighting_consistency.py)
    ...
```

---

## Files

| File | Purpose |
|---|---|
| `__init__.py` | public interface: `analyze_image`, `load_models`, exceptions |
| `analyzer.py` | orchestration, model loading, result contract, timings |
| `decode.py` | in-memory base64/JPEG decoding with a header-only size check |
| `face.py` | MediaPipe FaceLandmarker wrapper, head pose, alignment |
| `regions.py` | facial region polygons (mesh indices) and masks |
| `quality.py` | all hard/soft photo-quality checks and their messages |
| `lighting.py` | skin-tone-independent exposure (white reference) and evenness measures |
| `scoring.py` | linear-light maps, skin mask, the five features, score mapping |
| `scoring_config.py` | **every threshold and anchor**, documented |
| `errors.py` | `ImageRejected`, `ModelUnavailable` |
| `download_models.py` | fetches the pinned, checksum-verified MediaPipe model |
| `visualize_regions.py` | dev tool: region and detection overlays |
| `check_lighting_consistency.py` | lighting-sensitivity report (real + synthetic) |
| `check_funnel_resolution.py` | full-size vs the selfie page's downsizing, plus candidate settings (7b-i, 7b-ii) |
| `skin_type.py` | skin-type classifier inference + the preprocessing shared with training |
| `skin_type_data.py` | dataset discovery, duplicate grouping (pHash + ORB), leak-free split |
| `train_skin_type.py` | training/evaluation pipeline for the classifier (GPU) |
| `evaluate_against_ratings.py` | Spearman of the heuristic scores vs. dataset B's 0–5 ratings |
| `naive_split_control.py` | control: the same training on the uploaders' leaky split |
| `calibrate_dim_threshold.py` | reproduces `DIM_MIN_EXPOSURE_L` from 40 public photos |
| `tests/` | pytest suite |
| `models/`, `weights/`, `datasets/`, `samples/` | **gitignored**: downloaded model, trained weights, training data, your photos |

The HTTP endpoint is in `backend/app/api/image_analysis.py`.

### References

- Dawson, J.B. et al. (1980). A theoretical and experimental study of light absorption
  and scattering by in vivo skin. *Phys. Med. Biol.* 25(4), 695–709.
- Diffey, B.L., Oliver, R.J., Farr, P.M. (1984). A portable instrument for quantifying
  erythema induced by ultraviolet radiation. *Br. J. Dermatol.* 111(6), 663–672.
- Hayashi, N. et al. (2008). Establishment of grading criteria for acne severity.
  *J. Dermatol.* 35(5), 255–260.
- Crété-Roffet, F. et al. (2007). The blur effect: perception and estimation with a new
  no-reference perceptual blur metric. *Proc. SPIE* 6492.
- Kartynnik, Y. et al. (2019). Real-time facial surface geometry from monocular video on
  mobile GPUs. *CVPR Workshops* (MediaPipe Face Mesh).
- Tan, M., Le, Q. (2019). EfficientNet: Rethinking model scaling for convolutional neural
  networks. *ICML*.
- Rublee, E. et al. (2011). ORB: An efficient alternative to SIFT or SURF. *ICCV*.
- Fischler, M.A., Bolles, R.C. (1981). Random sample consensus: a paradigm for model
  fitting with applications to image analysis and automated cartography. *Commun. ACM*
  24(6), 381–395.
- Chardon, A., Cretois, I., Hourseau, C. (1991). Skin colour typology and suntanning
  pathways. *Int. J. Cosmet. Sci.* 13(4), 191–208 (ITA°).
