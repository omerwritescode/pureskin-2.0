# Questionnaire/NLP service (roadmap step 7b-i)

Questionnaire answers → skin type, sensitivity, an estimate for each of the five skin
scores, and tags pulled from the free-text answers. Pure Python with documented rules:
no model, no LLM, no new dependencies.

> **These are self-reported answers mapped by hand-set rules.** No labelled ground
> truth was used to build or check them, and nothing here is validated. A rule turns
> what the user *says* into a number. It doesn't measure their skin, and it can't
> correct a user who misjudges or misreports their own skin.

**Status:** live at the standalone endpoint and tested on its own. The funnel doesn't
call it yet: until 7b-ii the questionnaire still posts to `/api/scan/mock-analyze`.

---

## Interface

### Python

```python
from app.services.questionnaire import score_questionnaire

result = score_questionnaire(answers)  # dict; raises pydantic.ValidationError if malformed
```

```json
{
  "config_version": "questionnaire-1.0.0",
  "skin_type": "combination",
  "skin_type_basis": "zones",
  "is_sensitive": true,
  "sensitivity_rules": ["S3"],
  "estimates": {"acne_score": 65, "redness_score": null, "wrinkle_score": null,
                "pigmentation_score": null, "pore_score": null},
  "stated_concern": "acne",
  "concern_tags": ["rosacea"],
  "actives_in_use": ["ascorbic acid", "salicylic acid"],
  "avoid": ["fragrance", "lanolin"],
  "products_in_use": ["cleanser", "retinoid"],
  "context_tags": ["short_sleep"]
}
```

| Field | Meaning |
|---|---|
| `skin_type` | always one of oily, dry, combination, normal (never "sensitive") |
| `skin_type_basis` | which rule set it: `zones` (T1), `label` (T2) or `default` (T3) |
| `is_sensitive`, `sensitivity_rules` | sensitivity, independent of skin type, and the rules that fired (S1-S4) |
| `estimates` | int 1-100 per score, or **`null` when the answers carry no evidence** for it |
| `stated_concern` | the user's primary concern, as given. A goal, **never** used in an estimate |
| `concern_tags` | concern words and skin conditions found in the free text |
| `actives_in_use` | actives named in "specific products", by catalog name (+ `prescription_retinoid`) |
| `avoid` | ticked sensitivities, plus allergens and actives named in the sensitivities text |
| `products_in_use` | the ticked product types |
| `context_tags` | lifestyle context (`short_sleep`, `high_stress`). Never used in an estimate |

### HTTP: `POST /api/services/questionnaire/score`

No auth (the funnel runs before signup). The body is the answers object itself.

| Status | Body | When |
|---|---|---|
| 200 | the dict above | answers scored |
| 422 | `{"detail": [{"loc", "msg", "type"}]}` | not a JSON object, unknown key, unknown value, wrong type, text too long |
| 413 | `{"detail": "..."}` | body over 64 KB |

The endpoint reads and parses the body itself (shared helpers in
`app/api/request_body.py`), so **a 422 never echoes the input**. FastAPI's default 422
includes each offending value, which here could be the user's free text. Unknown key
names are cut to 64 characters in `loc`.

---

## Input

Every field is optional. A missing answer, `null`, or `"not_sure"` means **no
evidence**. It is never replaced with a middle value. Unknown keys and values are
rejected.

**The step 5 questionnaire** (what the funnel sends today):

| Field | Values |
|---|---|
| `skin_type` | oily, dry, combination, normal, sensitive, not_sure |
| `primary_concern` | acne, redness, wrinkles, pigmentation, pores, none |
| `sensitivities` | list of fragrance, alcohol, retinoids, acids, essential_oils |
| `sensitivities_other` | free text, ≤ 500 chars |
| `current_products` | list of cleanser, moisturiser, sunscreen, serum, exfoliant, retinoid |
| `current_products_other` | free text, ≤ 500 chars |
| `sleep` / `stress` | under_6, 6_to_8, over_8 / low, medium, high |

**Added for 7b-ii** (accepted now, sent by the funnel once 7b-ii ships):

| Field | Question | Values |
|---|---|---|
| `oil_tzone` | By midday, how does your T-zone (forehead, nose, chin) usually look or feel? | oily, normal, dry, not_sure |
| `oil_cheeks` | By midday, how do your cheeks usually feel? | oily, normal, dry, not_sure |
| `reactivity` | How often do skincare products make your skin sting, burn, itch or turn red? | never, rarely, sometimes, often, not_sure |
| `breakouts` | How often do you get breakouts (pimples or spots)? | rarely_or_never, occasionally, most_weeks, constantly, not_sure |
| `deep_bumps` | Do you get painful, deep bumps under the skin? | no, sometimes, often, not_sure |
| `flushing` | Apart from exercise or heat, how often does your face look red or flushed? | rarely, sometimes, often, almost_always, not_sure |
| `fine_lines` | Do you have fine lines or wrinkles? | none, only_with_expression, some_at_rest, many_at_rest, not_sure |
| `dark_spots` | Do you have dark spots, patches or uneven tone? | none, a_few, several, widespread, not_sure |
| `pores` | How visible are your pores in a normal mirror? | barely, on_nose, nose_and_cheeks, across_face, not_sure |

---

## Rules

Every rule, threshold, weight and lexicon entry is in **`questionnaire_config.py`**,
with `CONFIG_VERSION` (bump it whenever a result could change). The code contains no
numbers of its own.

### Skin type

Skin type and sensitivity are derived **independently**. The first rule that applies
wins.

| # | Rule | Result | `skin_type_basis` |
|---|---|---|---|
| T1 | `oil_tzone` and `oil_cheeks` both answered, and the pair is in the table below | from the table | `zones` |
| T2 | step 5 label is oily, dry, combination or normal | that label | `label` |
| T3 | otherwise | `normal` | `default` |

| T-zone \ cheeks | oily | normal | dry |
|---|---|---|---|
| **oily** | oily | combination | combination |
| **normal** | oily | normal | dry |
| **dry** | *(contradictory: falls through)* | dry | dry |

- **combination = oily T-zone with normal or dry cheeks.**
- **Partial zone answers fall through.** If only one of `oil_tzone` / `oil_cheeks` is
  answered, or either is `not_sure`, or the pair is the contradictory dry T-zone with
  oily cheeks, T1 doesn't apply and T2, then T3, decide. `skin_type_basis` then says
  `label` or `default`.
- **Why the zones win over the label:** they ask about something observable (how the
  skin feels by midday) rather than a category the user has to know, and they are what
  the definition of combination skin needs.
- **Why `normal` and not null for T3:** the step 5 labels `sensitive` and `not_sure`
  say nothing about oil or dryness. A null skin type sends the routine page to its
  "complete your scan" prompt, and the routine already treats unknown types as
  normal. `skin_type_basis: "default"` (and `score_sources.skin_type: "default"`)
  records that it is a default, not a finding.

### Sensitivity

`is_sensitive` is true if any rule fires. False means "no evidence of sensitivity",
not "confirmed not sensitive".

| # | Rule |
|---|---|
| S1 | step 5 label is `sensitive` |
| S2 | `reactivity` = often |
| S3 | `reactivity` = sometimes, and at least 1 sensitivity signal |
| S4 | at least 2 distinct sensitivity signals |

A **signal** is any of:
- a ticked `sensitivities` category;
- a reaction named in `sensitivities_other`, keyed by its category where it has one.
  So a typed "glycolic acid" and a ticked "acids" are **one** signal, and lanolin or
  niacinamide are their own;
- a skin condition named in `sensitivities_other`. Eczema, dermatitis and rosacea
  together count as **one** signal.

**Why 2 signals for S4, not 1:** a single reaction, for example retinoid irritation
when someone starts using one, is common and shouldn't switch the whole routine to the
sensitive set. Two independent reactions are a stronger sign of reactive skin. This is
a judgement call; `S4_MIN_SIGNALS` is the knob.

### Score estimates

Each score has one primary question. Its answer maps to a fixed value inside the band
it describes (Low 1-30, Moderate 31-60, High 61-100):

| Score | Question | Estimates |
|---|---|---|
| acne | `breakouts` | rarely_or_never 10, occasionally 25, most_weeks 45, constantly 75 |
| ↳ modifier | `deep_bumps` | no +0, sometimes +10, often +20 (capped at 100) |
| redness | `flushing` | rarely 10, sometimes 35, often 55, almost_always 75 |
| wrinkle | `fine_lines` | none 10, only_with_expression 25, some_at_rest 50, many_at_rest 75 |
| pigmentation | `dark_spots` | none 10, a_few 30, several 50, widespread 75 |
| pore | `pores` | barely 10, on_nose 30, nose_and_cheeks 50, across_face 75 |

- **No evidence gives `null`, never a default.** A primary question that is missing or
  `not_sure` gives `null`. The merge step then relies on the image (see the
  skin_profile service).
- **Modifiers only adjust.** `deep_bumps` adds points only when `breakouts` was
  answered; on its own it never creates an estimate.
- **Monotonic by construction.** Anchors increase with severity and modifier points
  are non-negative, so a more severe acne answer can never lower the acne estimate
  (tested over every combination).
- **The values are ordinal judgements.** They place each answer in the band its
  wording describes; they were not fitted to anything. Example: "constantly" (75) and
  "most weeks" + "often" deep bumps (65) are both High, and so both corroborate a high
  image acne score in the merge.

**The step 5 questionnaire has no evidence for any score.** Its questions ask about
skin type, a goal, sensitivities, products and lifestyle, not about how much acne,
redness, wrinkling, pigmentation or pore visibility the user has. So with today's
funnel every estimate is `null`. The questions above are what 7b-ii adds to fix that.

**Deliberately not evidence for any score:**

| Answer | Why not |
|---|---|
| `primary_concern` | A goal, not a measurement: wanting fewer wrinkles doesn't mean having many. It comes back as `stated_concern` only (tested: changing only the concern changes nothing else). |
| `sleep`, `stress` | Lifestyle, not observations of the skin. `context_tags` only. |
| products / actives in use | What someone does, not how much of a concern they have now (a treatment may have it under control). Tags only. |
| concern words in free text | Product names ("Acne Control Cleanser") aren't self-assessments. Tags only. |

### Free text ("NLP")

Two fields are free text: `sensitivities_other` ("Anything else?") and
`current_products_other` ("Specific products"). A small lexicon in
`questionnaire_config.py` turns them into tags; **the raw text is never stored,
returned or logged.**

1. **Normalise.** NFKC, lower-case, drop apostrophes ("don't" → "dont"), split into
   clauses at `, ; . ! ? / ( )`, newlines and "but", then into word tokens. A trailing
   "s" is dropped from tokens longer than 3 letters unless they end in "ss" ("acids" →
   "acid"). Lexicon terms are normalised the same way.
2. **Match longest-first**, so "hyaluronic acid" is the active, not the "acids"
   category, and "atopic dermatitis" is eczema, not generic dermatitis.
3. **Negation.** A match is dropped if "no", "not", "never", "without", "non",
   "dont", "doesnt", "isnt" or "cant" appears up to 3 tokens before it in the same
   clause, or "free" follows it ("fragrance-free").

| Lexicon | Maps to | Used in |
|---|---|---|
| actives | the **catalog's ingredient names** (`seed.py`), e.g. "vitamin C" / "L-ascorbic acid" → `ascorbic acid`, "BHA" → `salicylic acid`, "nicotinamide" → `niacinamide` | both fields |
| prescription retinoids | tretinoin, adapalene, tazarotene, trifarotene, isotretinoin, Retin-A → **`prescription_retinoid`**, deliberately not `retinol`: their conflict profiles differ (adapalene + benzoyl peroxide is a marketed combination) | both fields |
| categories | the five checkbox categories, e.g. "parfum" → fragrance, "tea tree" → essential_oils | sensitivities |
| allergens | lanolin, sulfates (SLS/SLES), parabens | sensitivities |
| conditions | eczema, dermatitis, rosacea | sensitivities |
| concerns | acne, redness, pigmentation, wrinkles, pores | both fields |

The products field never yields reactions or conditions: a product named "fragrance
free" or "eczema relief" says nothing about the user's skin.

---

## Limitations

1. **Self-report, no ground truth, not validated.** Every rule and number is a
   documented judgement call. Nothing was fitted to data, and there is no labelled set
   to check them against. People misjudge their own skin type, and severity words
   ("often", "several") mean different things to different people.
2. **The estimates are coarse.** Each score comes from one 4-option question, so there
   are only 4 possible values per score, plus null (acne: 11). They place a user in a band;
   they don't grade within it.
3. **Today's funnel gives no estimates.** Until 7b-ii adds the questions above, every
   estimate is `null`, and the Skin Profile's scores come from the image alone (with the
   acne cap).
4. **"Normal" may be a default.** With no oil/dry answer, the skin type is `normal` by
   default. Check `skin_type_basis` before treating it as a finding.
5. **The lexicon is small and literal.**
   - **No brand knowledge.** "CeraVe Hydrating Cleanser" yields nothing, and "Differin"
     isn't recognised as adapalene.
   - **No spelling correction.**
   - **Approximate synonyms.** Generic "AHA" is mapped to glycolic acid, the most
     common AHA and the catalog's only one with conflict rules.
   - **Word-level negation.** It handles common phrasing only, misses negators more
     than 3 words back, and "alcohol and fragrance free" negates only "fragrance".
   - **Fatty alcohols.** Cetyl and cetearyl alcohol, which are not drying, count as
     "alcohol".
   - **English only.**
6. **Sensitivity is a proxy.** There is no validated sensitivity score here. S1-S4 flag
   users who *report* reactions; a user who has never tried an irritating product will
   read as not sensitive.

---

## Testing

```bash
python -m pytest app/services/questionnaire        # from backend/
```

- **Rules:** every T1 zone pair; T2 labels; T3 default; partial, `not_sure` and
  contradictory zones fall through. S1-S4 at and either side of each boundary;
  ticked + typed reactions in the same category count once; conditions count once;
  negated reactions don't count.
- **Estimates:** every anchor; missing / `not_sure` give `null` (not a default); a
  modifier alone gives `null`. Over every combination of the scored questions (38,880),
  estimates are always `null` or an int in 1-100. Acne is monotonic across all
  breakouts × deep_bumps orderings.
- **Invariance:** changing only `primary_concern` changes nothing but
  `stated_concern`; free text, products, sleep and stress never change an estimate.
- **Input:** today's funnel payload is accepted; unknown keys and values, wrong types,
  over-long text and over-long lists are rejected.
- **Lexicon:** catalog naming (checked against `seed.py`), synonyms, prescription
  retinoids, longest match, negation and clause boundaries, plurals.
- **Endpoint and privacy:** 200, 422 (several malformed shapes), 413. Free text never
  appears in a 422, a 200 or the logs.

## Files

| File | Purpose |
|---|---|
| `__init__.py` | public interface: `score_questionnaire`, `QuestionnaireAnswers`, `CONFIG_VERSION` |
| `questionnaire_config.py` | **every rule, threshold, weight and lexicon entry**, versioned |
| `schemas.py` | Pydantic input (`QuestionnaireAnswers`) and output (`QuestionnaireScore`) |
| `scorer.py` | skin type, sensitivity, estimates, tags |
| `lexicon.py` | free-text normalisation, longest-match, negation |
| `tests/` | pytest suite |

The HTTP endpoint is in `backend/app/api/questionnaire.py`.
