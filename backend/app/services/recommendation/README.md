# Recommendation Engine (roadmap step 7c)

Builds the AM/PM routine shown on `/app/routine/` from the user's latest Skin Profile,
the product catalog and the ingredient-conflict table. **Rules first:** documented,
hand-set rules decide which products are eligible for each step. A content-based
ranker (7c-ii) then orders each step's eligible products; it can never add or remove
one.

> **Not medical advice, and not validated.** Every rule here is a hand-set judgement in
> `routine_config.py`. There is no outcome data (no feedback, no purchases, no follow-up)
> to fit or check them against. **The 24 products in the catalog are synthetic
> placeholders** (invented brands and short invented ingredient lists), so a routine
> shows how the rules behave, not what to buy.

**Status:** live since 7c-i (b); rules `routine-2.3.0` (7c-iii: the wrinkle step takes
any retinoid; the sensitive fragrance reason names the kind of ingredient), ranker
`recommendation-1.0.0` (since 7c-ii). The ranker's results are on the 24 placeholder products until 7c-iii
replaces them. Pure functions: no database, no FastAPI (`app/api/routine.py` loads the
rows and shapes the response).

| File | What it holds |
|---|---|
| `routine_config.py` | every rule, keyword matcher and fixed text (versioned) |
| `rules.py` | Skin Profile → requirements (category + keywords), in priority order |
| `matching.py` | does a product meet a keyword (ingredients, classes, format fields) |
| `engine.py` | requirements + catalog + conflicts → routine, with every left-out product and why |
| `recommendation_config.py` | the ranker's target groups, weights and explanation templates (versioned) |
| `tfidf.py` | ingredient-level TF-IDF with a list-position decay |
| `ranker.py` | the profile's targets, and a product's score against them |
| `explain.py` | the "why" of each step and of each alternative (fixed templates) |
| `evaluate.py` | the evaluation report (`python -m app.services.recommendation.evaluate`) |

Ingredient names, classes and the preservative-cutoff rule come from the shared
normaliser, `app/services/ingredients/` (see its README).

---

## How a routine is built

1. **Requirements.** The skin type's base steps (oily, dry, combination, normal; a
   missing or unknown type uses normal), then sensitive-skin preferences, then each
   score's steps when the score is in the **High band** (≥ 61, `HIGH_BAND_MIN` imported
   from `skin_profile_config`).
2. **Eligibility (hard rules).** A product is skipped, with a reason shown to the user,
   when:
   - its ingredient list has a name the vocabulary doesn't know (**fail closed**);
   - the profile is sensitive and it contains a **strong active** (a retinoid, benzoyl
     peroxide, an AHA or a BHA), **L-ascorbic acid** (the canonical token "ascorbic
     acid"; derivatives such as ascorbyl glucoside are separate tokens and stay allowed),
     or any declared **fragrance** (fragrance, a declared fragrance allergen, an essential
     oil). The reason names which (routine-2.3.0): "It lists fragrance (declared
     fragrance).", "It contains benzyl alcohol, a listed fragrance allergen.", "It contains
     mentha piperita oil, an essential oil.", each followed by "Sensitive skin gets
     fragrance-free products only.";
   - it would go in the morning but contains a **retinoid** (any product) or an **AHA**
     (any leave-on product; a cleanser is rinsed off). The reason says "Not used in the
     morning routine because it contains lactic acid (an AHA); AHAs are evening-only"
     when the product is in the evening routine, and "Left out because…" when it isn't
     in the routine at all.
3. **Ordering (7c-ii).** The ranker (below) orders each step's eligible products, and
   the step takes the first. Rule order (keyword order, then product id) is the last
   tie-break, and `RULE_ORDER` reproduces 7c-i's choices exactly (the evaluation's
   baseline; a test checks a digest over 5,502 profiles).
4. **Core steps never go missing for a keyword.** Cleanser, moisturiser and sunscreen
   fall back from a score step to the base step, then to any eligible product in the
   category. Every hard rule applies at every level, so a core step stays empty (with a
   warning) only when no product in its category is eligible.
5. **Sensitive substitutions** (`SENSITIVE_SUBSTITUTIONS`), each with a warning:
   - always: the morning base serum ("vitamin c" for combination skin, "antioxidant"
     for normal skin) → a centella serum;
   - when no product for the step is eligible for sensitive skin (the catalog has
     none, or every one is left out by a sensitive-skin hard rule): acne → azelaic acid
     instead of benzoyl peroxide;
   - when the catalog has products for the step and every one is left out by a
     sensitive-skin hard rule: the morning dark-spot step, the evening retinol step and
     the pore step → none (their warning says every product for the step is left out,
     which is only true when there are some).
6. **Conflicts.** Every pair of products in a session is checked against the conflict
   table. A row names an ingredient or a whole class (`class:retinoid`), so one row
   covers every member. A core product always stays; between two optional products the
   one serving the higher-priority concern stays (acne, redness, pigmentation, wrinkles,
   pores; a score step always outranks a base step), the same way for every skin type.
   Every severity is resolved. The dropped product is listed with what it clashed with.
7. **Reasons.** Every product the rules would have used but didn't is listed under
   "Left out" with its reason; step-level notes are under "Heads up". Every step whose
   product lists a retinoid carries a fixed caution: *"If you're pregnant, trying to get
   pregnant or breastfeeding, ask a doctor before using a retinoid."*

## The user's current products and avoid list (7c-i c)

The questionnaire's fixed-vocabulary tags are saved with the Skin Profile
(`skin_profiles.questionnaire_tags`: actives and product types in use, the avoid list,
the stated goal). **NULL tags mean no information**: none of the rules below apply, the
routine is exactly what it would be without them, and the routine page says "This
routine doesn't take your current products into account". Empty tag lists (the user
answered "none") are information, and show no notice.

- **Actives in use count as present in both sessions** (we don't know when they're
  used). A product with a **high- or medium-severity** conflict with one is a **hard
  exclusion**, core steps included (the core fallback keeps it); the reason names the
  active. A **low-severity** conflict is not: the product stays, with a note ("You already
  use ascorbic acid. Using it alongside … is a low-concern pairing: the reported clash is
  generally overstated, though some people notice flushing.": a per-pair clause in
  `EXISTING_LOW_CONFLICT_CLAUSES`, else the pair's stored reason). Conflicts between two
  products in the routine are unchanged (every severity is resolved).
- **Duplicates are not added.** A step whose own active the user already uses is not
  added, with a note ("No serum with retinol was added because you already use a
  prescription retinoid."). A product containing a member of a family the user already
  uses (retinoids, benzoyl peroxide, AHAs, BHAs: `DUPLICATE_CLASSES`) is left out.
- **A prescription retinoid**, and the ticked "Retinoid" product type, count as the
  retinoid class for duplicates and conflicts, exactly like a retinoid named in the free
  text. So no benzoyl peroxide is added, and a fixed note says the prescriber's
  instructions come first.
- **A ticked "Exfoliant"** means no new exfoliant step.
- **The avoid list** is a hard exclusion, with strict membership (a trace counts):

| Avoid tag | Leaves out a product listing |
|---|---|
| fragrance | declared fragrance, a declared fragrance allergen, or an essential oil |
| alcohol | a drying alcohol only (not fatty alcohols) |
| acids | an AHA or a BHA only (not hyaluronic, tranexamic, azelaic acid…) |
| retinoids, essential_oils, lanolin, sulfates, parabens | a member of that class |
| retinol, prescription_retinoid | any retinoid |
| salicylic acid / glycolic acid / ascorbic acid | any BHA / any AHA / any vitamin C (the lexicon folds "bha", "aha", "vitamin c" into these tags) |
| any other named active | that ingredient |

## Keywords

A keyword is a set of conditions that must all hold (`MATCHERS`). **Descriptions are
never matched** (until 7c-i b they were; the placeholder descriptions had been written to
contain the rules' keywords).

| Keyword | Requires |
|---|---|
| foaming | the cleanser's `foaming` field is "foaming" |
| cream (cleanser) | `texture` is cream, milk or balm |
| lightweight | `texture` is liquid, gel, gel_cream, fluid or lotion |
| rich | `texture` is cream or balm |
| spf 50 / spf 30 | the `spf` field is at least 50 / 30 |
| mineral | every UV filter in the list is mineral (derived) |
| facial oil | `texture` is oil **and** the list has no water and starts with an oil (derived) |
| niacinamide, hyaluronic acid, salicylic acid, benzoyl peroxide, azelaic acid, alpha arbutin, tranexamic acid | that canonical ingredient is listed |
| vitamin c, antioxidant, peptide, bha | an ingredient of that class counts (preservative cutoff) |
| retinol (the wrinkle step) | an ingredient of the retinoid class counts (preservative cutoff): retinal and retinol too, a trace retinyl ester after the preservative not (routine-2.3.0; until then, retinol only) |

`texture`, `foaming` and `spf` are product columns (migration `99aa1b05ae54`), filled
when the catalog is seeded; an ingredient list can't give them reliably. The catalog
loader refuses a sunscreen without a labelled SPF of at least 30.

## The ranker (7c-ii)

A content-based ranker that **only orders the products the rules made eligible** for a
step. Hard exclusions (unknown ingredients, sensitive-skin rules, the evening-only rules,
the avoid list, actives in use, a prescription retinoid) are applied first and are its
input: it can never add, remove or bring back a product (a test checks, over the whole
grid, that every step's ranked set is its eligible set). Config: `recommendation_config.py`
(`recommendation-1.0.0`). **Every weight was set a priori, as a documented domain
judgement, and is never tuned to improve the evaluation below.**

### Score

```
w(r)    = 1 / log2(r + 1)                    r = the ingredient's 1-based list position
idf(t)  = ln((1 + N) / (1 + df(t))) + 1      over the whole catalog (N products)
x_p(t)  = w(r_p(t)) · idf(t)                 first position if listed twice
score(p) = Σ over target groups g of  weight(g) · max over p's ingredients t in g of x_p(t)
```

- **Position decay** is the standard discount from information retrieval (1, 0.63, 0.5,
  … 0.2 at position 31). It is gentle on purpose: below about 1% the INCI order isn't
  regulated, and potent actives work below 1%.
- **A weighted dot product, not cosine.** Cosine divides by the vector's length, so a
  complete 30-ingredient label would lose to a 5-ingredient one with the same actives,
  and it can't express penalties. Appending filler ingredients never changes a score (a
  test checks this over the grid).
- **The maximum within a group:** listing several humectants earns no more than the best
  one.
- Class membership uses the preservative cutoff (`app/services/ingredients/`).

### Target groups and the categories they apply to

| Group | Members | Categories |
|---|---|---|
| niacinamide | niacinamide | all |
| zinc | zinc PCA | all |
| humectant | glycerin, hyaluronic acid | all |
| barrier lipids | ceramides, cholesterol, linoleic acid | leave-on: moisturiser, treatment, serum |
| barrier lipids (sensitive) | the same | all (sensitive skin only) |
| emollient | the oil class (oils, butters, esters) | leave-on: moisturiser, treatment, serum |
| antioxidant | the antioxidant class | all |
| vitamin C | the vitamin C class | all |
| azelaic | azelaic acid | all |
| arbutin | alpha arbutin | all |
| tranexamic | tranexamic acid | all |
| peptide | the peptide class | all |
| centella | the centella class | all |
| soothing | panthenol, allantoin | all |
| drying alcohol (penalty) | the drying-alcohol class | all |
| chemical UV filter (penalty) | organic UV filters | all |

A rinse-off cleanser isn't ranked on barrier lipids or emollients, except barrier lipids
for sensitive skin. **Strong actives (retinoids, benzoyl peroxide, AHAs, BHAs) are never
targets:** they enter a routine only through a rule step that asks for them, with its
safety checks.

### Weights

A group's weight is the sum of its skin-type, concern and sensitivity weights. Only the
order within a step matters, so the absolute scale is irrelevant.

| Skin type | Group | Weight | Reasoning |
|---|---|---|---|
| oily | niacinamide | 1.0 | the standard ingredient formulated for oily skin |
| oily | zinc | 0.5 | commonly paired with niacinamide in oil-control formulas; secondary |
| dry | humectant | 1.0 | dry skin needs ingredients that hold water |
| dry | barrier lipids | 1.0 | lipids that replenish the barrier, the other half of dry-skin care |
| dry | emollient | 0.5 | oils and butters limit water loss; secondary, and texture already has a rule |
| combination | niacinamide | 0.75 | oil control for the T-zone, a little below oily |
| combination | humectant | 0.75 | hydration for drier areas, balanced against oil control |
| normal | antioxidant | 0.75 | maintenance; mirrors the rule's antioxidant step |
| normal | humectant | 0.5 | general hydration, secondary |

Each concern's weights are multiplied by its band's scale: **Low 0, Moderate 0.5, High
1.0** (band names from `SCORE_BANDS`).

| Concern | Group | Weight | Reasoning |
|---|---|---|---|
| acne | niacinamide | 0.75 | a common non-strong ingredient in acne-prone formulas |
| acne | azelaic | 0.75 | used for breakouts, tolerated by more skin types than BHA/BPO |
| acne | zinc | 0.5 | oil-control support, secondary |
| redness | azelaic | 1.0 | the active the redness rule step uses |
| redness | centella | 0.75 | widely used to soothe visible redness |
| redness | soothing | 0.75 | panthenol and allantoin, the same purpose |
| redness | niacinamide | 0.5 | barrier support, secondary |
| pigmentation | arbutin | 1.0 | the morning pigmentation rule's active |
| pigmentation | tranexamic | 1.0 | the evening pigmentation rule's active |
| pigmentation | vitamin C | 0.75 | widely used for uneven tone |
| pigmentation | azelaic | 0.5 | also used for uneven tone, secondary |
| pigmentation | niacinamide | 0.5 | also used for uneven tone, secondary |
| wrinkles | peptide | 1.0 | the non-retinoid ingredient the rule's morning step uses |
| wrinkles | vitamin C | 0.5 | an antioxidant, secondary |
| wrinkles | humectant | 0.25 | hydration softens the look of fine lines; minor |
| pores | niacinamide | 0.75 | commonly used for the look of pores |
| pores | zinc | 0.5 | oil-control support, secondary |

| Sensitive skin (`is_sensitive`) | Weight | Reasoning |
|---|---|---|
| soothing | +1.0 | the main sensitive-skin preference |
| centella | +0.75 | a soothing botanical |
| barrier lipids (sensitive) | +0.75 | barrier support, in every category |
| drying alcohol | −1.0 | drying alcohols commonly sting reactive skin |
| chemical UV filter | −0.5 | organic filters irritate some sensitive skin; mineral is preferred |

L-ascorbic acid, strong actives and fragrance stay hard exclusions for sensitive skin,
not penalties.

**The stated goal** (`questionnaire_tags.stated_concern`) multiplies its concern's
weights by **1.5, after the band scale**. So **a goal whose score is Low has no effect.
This is intended:** a goal never creates a concern the scores don't show, and never adds
a step. The questionnaire says so: "This helps us choose between suitable products. It
doesn't change your scores."

### Order within a step

Each step sorts its eligible products by:

1. **keyword tier:** the keyword alternatives stay a rule (oily skin's SPF 50 before
   SPF 30, whatever the scores);
2. **a strong active the step doesn't ask for ranks last:** a product with a retinoid,
   benzoyl peroxide, an AHA or a BHA (preservative cutoff) ranks after every product
   without one, unless the step itself asks for that active;
3. **conflict-safe first:** a product that clashes with a product already chosen for the
   session ranks after one that doesn't;
4. **score**, compared rounded to 9 decimals;
5. **rule order** (keyword order, then product id).

So **equal scores, including all zeros, keep rule order**: a pick changes only when
another eligible product scores strictly higher, or rule 2 or 3 moves it.

**Choosing order.** Steps choose in concern priority (score steps first, in
`CONCERN_PRIORITY` order, then sensitive, base and fallback steps; ties keep rule order).
Each step sees the picks of the steps that chose before it, which is what rule 3 checks.
The routine is still shown in category order, and the output is deterministic,
whatever the catalog order.

**Alternatives.** Each kept step lists up to 2 alternatives: the next products in its
ranking that aren't already in the session and wouldn't clash with any other kept
product if swapped in.

### Explanations

Every step has a `why`: the rule that created it, what met its keyword (with the
ingredient's position, e.g. "2nd of 4 ingredients", using the name as listed), the
number of eligible products, the rule-order rank, the top 3 ingredients by **positive**
contribution (each with its position, the targets of the groups it matched, and its
contribution; an ingredient in two groups is one entry), and sentences from the fixed
templates in `recommendation_config.TEMPLATES`. Each ingredient is attributed to its own
targets: "it lists panthenol (4th of 4 ingredients), matched for redness (High) and
sensitive skin; glycerin (2nd of 4 ingredients), matched for normal skin". When nothing
matched a target, the
text says "no target ingredients matched; kept rule order". When rule 2 or 3 moved the
rule-order pick down, a sentence says which product and why.

The sentences are factual about ingredients and the rules, never about efficacy: a test
fails if a template, or any sentence generated over the grid (product names blanked),
uses a banned word (treat, cure, heal, fix, reduce, clear, prevent, eliminate, remove,
fight, erase, reverse, repair, guarantee, proven, clinical(ly),
dermatologist-approved/-recommended, medical, medicated, therapy, therapeutic,
effective, miracle, cure-all, and their forms).

## Evaluation

```bash
python -m app.services.recommendation.evaluate                  # full report, a few minutes
python -m app.services.recommendation.evaluate --no-timing      # deterministic part only
python -m app.services.recommendation.evaluate --update-readme  # rewrite the results below
```

Every number comes from the real functions on the seeded catalog; nothing is typed by
hand. The results below are written by `--update-readme` (a test checks they match the
current config versions). The full run also prints the median build time per routine,
which is machine-dependent and so not recorded here.

What it measures:

- **Responsiveness:** per step with a choice, how often the ranker's pick differs from
  the rule-order pick, and why (score, strong-active demotion, conflict-safe).
  Single-candidate steps are counted separately.
- **What each ordering rule changes:** ablations, each switching one rule off, compared
  with the full ranker.
- **Baselines:** rule order (7c-i) and a seeded random pick from the eligible set (100
  seeds, mean ± sd).
- **Face validity**, which is **circular by construction**: targets come from our own
  config, so a high share is expected and is not accuracy.
- **Consistency:** profiles that differ in one score by one band (Jaccard index of the
  picks, slot agreement).
- **Stability:** leave one unchosen product out of the catalog and rebuild. Rule order is
  the control.
- **The stated goal's effect** by band; **coverage**, with the requirements no eligible
  product met broken down by cause on both grids; and **catalog gaps** (slots with fewer
  than 5, and fewer than 3, eligible products, who they fail to serve, and the
  characteristics a product there would need).

What it doesn't measure: benefit to anyone's skin. The measures describe behaviour under
the constraints, not outcomes.

### Results

<!-- evaluation:start -->
> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Config versions: recommendation-1.0.0, routine-2.3.0, ingredients-1.2.0, tags questionnaire-1.0.0.

Catalog: 24 products, 11 conflict rows (seed.py). Base grid: 1,944 profiles (4 skin types × sensitive or not × 3 bands (15, 45, 80) for each of 5 scores; no tags). Tag grid: 3,072 profiles (12 current-product/avoid scenarios × 4 skin types × sensitive or not × 2 bands per score).

The ranker's weights were set before this evaluation and are never tuned to it. Nothing here measures benefit to skin: there is no outcome data.

### 1. Responsiveness: where the ranker changes a pick

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Per kept step, the ranker's pick against the same step's rule-order pick (single-candidate steps counted separately), then whole routines against RULE_ORDER. A pick is attributed to the first sort key that moved it away from the rule-order pick; a key that keeps the rule-order pick first (e.g. demoting a higher-scoring strong active) shows in section 2 instead.

| Base grid | Count |
|---|---|
| Kept steps | 16,026 |
| … with one eligible product (no choice) | 8,655 / 16,026 (54.0%) |
| … with 2 or more eligible products | 7,371 / 16,026 (46.0%) |
|    every candidate scores zero: rule order kept | 972 / 7,371 (13.2%) |
|    scores differ, the rule-order pick still ranks first | 3,216 / 7,371 (43.6%) |
|    pick differs from the step's rule-order pick: higher score | 3,183 / 7,371 (43.2%) |
|    pick differs: strong active outside its step ranked last | 0 / 7,371 (0.0%) |
|    pick differs: conflict-safe first | 0 / 7,371 (0.0%) |
| Profiles whose routine differs from the rule-order routine | 1,382 / 1,944 (71.1%) |

| Tag grid | Count |
|---|---|
| Kept steps | 25,920 |
| … with one eligible product (no choice) | 15,040 / 25,920 (58.0%) |
| … with 2 or more eligible products | 10,880 / 25,920 (42.0%) |
|    every candidate scores zero: rule order kept | 1,536 / 10,880 (14.1%) |
|    scores differ, the rule-order pick still ranks first | 4,776 / 10,880 (43.9%) |
|    pick differs from the step's rule-order pick: higher score | 4,568 / 10,880 (42.0%) |
|    pick differs: strong active outside its step ranked last | 0 / 10,880 (0.0%) |
|    pick differs: conflict-safe first | 0 / 10,880 (0.0%) |
| Profiles whose routine differs from the rule-order routine | 2,140 / 3,072 (69.7%) |

### 2. What each ordering rule changes (base grid)

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Each row switches one rule off and compares the routines with RANKED. "Steps dropped for a conflict": steps conflict resolution removed (a lost step).

| Variant | Profiles with a different routine | Slot picks that differ | Steps dropped for a conflict |
|---|---|---|---|
| RANKED (all rules on) | – | – | 444 |
| without strong-active demotion | 44 / 1,944 (2.3%) | 44 | 444 |
| without conflict-safe first | 0 / 1,944 (0.0%) | 0 | 444 |
| without concern-priority choosing order | 0 / 1,944 (0.0%) | 0 | 444 |
| rule order (7c-i) | 1,382 / 1,944 (71.1%) | 3,183 | 444 |

### 3. Baselines (base grid)

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Face validity: share of picks, in steps with 2 or more eligible products, that list at least one of the profile's target ingredients. **Circular by construction: targets come from our own config. This is not accuracy.** The mean target score is circular for the same reason.

| Ordering | Face validity (circular) | Mean target score (circular) | Steps dropped for a conflict | Products picked | Neighbour Jaccard |
|---|---|---|---|---|---|
| ranked | 6,399 / 7,371 (86.8%) | 1.966 | 444 | 22 / 24 | 0.856 |
| rule order (7c-i) | 6,399 / 7,371 (86.8%) | 1.703 | 444 | 18 / 24 | 0.918 |
| random pick, 100 seeds (mean ± sd) | 86.3 ± 0.3% | 1.630 ± 0.060 | 629.3 ± 183.0 | 20.9 ± 1.0 / 24 | 0.921 ± 0.005 |

### 4. Consistency: neighbouring profiles (base grid)

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Pairs of profiles that differ in one score by one band. S = {(session, category, product)}; Jaccard |S∩S'| / |S∪S'|; slot agreement: same product in the slots both routines have. Steps are added only in the High band, so in rule order a Low↔Moderate change never changes a routine.

| Score | Change | Pairs | Ranked mean J | Ranked J = 1 | Ranked slot agreement | Rule-order mean J | Rule-order J = 1 | Rule-order slot agreement |
|---|---|---|---|---|---|---|---|---|
| acne | Low↔Moderate | 648 | 0.910 | 78.7% | 94.9% | 1.000 | 100.0% | 100.0% |
| acne | Moderate↔High | 648 | 0.678 | 13.9% | 94.7% | 0.739 | 16.7% | 100.0% |
| redness | Low↔Moderate | 648 | 0.843 | 62.5% | 90.1% | 1.000 | 100.0% | 100.0% |
| redness | Moderate↔High | 648 | 0.778 | 13.4% | 95.9% | 0.830 | 16.7% | 100.0% |
| wrinkle | Low↔Moderate | 648 | 0.931 | 85.6% | 95.9% | 1.000 | 100.0% | 100.0% |
| wrinkle | Moderate↔High | 648 | 0.736 | 2.8% | 97.6% | 0.743 | 0.0% | 100.0% |
| pigmentation | Low↔Moderate | 648 | 0.990 | 95.8% | 99.5% | 1.000 | 100.0% | 100.0% |
| pigmentation | Moderate↔High | 648 | 0.886 | 0.0% | 100.0% | 0.886 | 0.0% | 100.0% |
| pore | Low↔Moderate | 648 | 0.914 | 78.7% | 95.0% | 1.000 | 100.0% | 100.0% |
| pore | Moderate↔High | 648 | 0.893 | 64.8% | 94.8% | 0.981 | 85.2% | 100.0% |
| all | Low↔Moderate | 3,240 | 0.918 | 80.3% | 95.1% | 1.000 | 100.0% | 100.0% |
| all | Moderate↔High | 3,240 | 0.794 | 19.0% | 96.6% | 0.836 | 23.7% | 100.0% |
| all | all | 6,480 | 0.856 | 49.6% | 95.8% | 0.918 | 61.9% | 100.0% |

### 5. Stability under catalog perturbation: leave one out (base grid)

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Remove one product the profile's routine did not choose, rebuild, and compare the picks. In ranked mode IDF moves (N and document frequencies change). Rule order is the control: its changes come from the rules themselves (a sensitive-skin substitution applies only when some product meets the step and every one is left out, so removing the only such product turns the substitution off). The last row is what the ranker adds.

| Ordering | (removed product, profile) pairs with changed picks | Profiles changed by at least one removal | Removals that change any routine | Most profiles changed by one removal |
|---|---|---|---|---|
| ranked | 971 / 35,100 (2.8%) | 271 / 1,944 (13.9%) | 23 / 24 | 123 / 1,944 (6.3%) |
| rule order (7c-i) | 0 / 34,938 (0.0%) | 0 / 1,944 (0.0%) | 0 / 24 | 0 / 1,944 (0.0%) |
| ranked only (changes rule order doesn't make) | 971 / 35,100 (2.8%) | 271 / 1,944 (13.9%) | 23 / 24 | 123 / 1,944 (6.3%) |

### 6. The stated goal (base grid)

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Share of profiles whose picks change when the questionnaire goal names a concern. The goal multiplies that concern's weights after the band scale, so a goal whose score is Low has no effect, by design.

| Goal | Band of its score | Profiles whose picks change |
|---|---|---|
| acne (acne score) | Low | 0 / 648 (0.0%) |
| acne (acne score) | Moderate | 75 / 648 (11.6%) |
| acne (acne score) | High | 99 / 648 (15.3%) |
| redness (redness score) | Low | 0 / 648 (0.0%) |
| redness (redness score) | Moderate | 42 / 648 (6.5%) |
| redness (redness score) | High | 171 / 648 (26.4%) |
| wrinkles (wrinkle score) | Low | 0 / 648 (0.0%) |
| wrinkles (wrinkle score) | Moderate | 78 / 648 (12.0%) |
| wrinkles (wrinkle score) | High | 15 / 648 (2.3%) |
| pigmentation (pigmentation score) | Low | 0 / 648 (0.0%) |
| pigmentation (pigmentation score) | Moderate | 0 / 648 (0.0%) |
| pigmentation (pigmentation score) | High | 0 / 648 (0.0%) |
| pores (pore score) | Low | 0 / 648 (0.0%) |
| pores (pore score) | Moderate | 75 / 648 (11.6%) |
| pores (pore score) | High | 99 / 648 (15.3%) |

### 7. Coverage

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

| Grid | Measure | Value |
|---|---|---|
| base | products picked at least once | 22 / 24 (91.7%) |
| base | … also counting alternatives | 23 / 24 (95.8%) |
| base | eligible products per kept step (min / median / max) | 1 / 1 / 5 |
| base | profiles with a kept step under 5 eligible products | 1,944 / 1,944 (100.0%) |
| base | profiles with a kept step under 3 eligible products | 1,944 / 1,944 (100.0%) |
| base | requirements no eligible product met (each with a warning) | 648 |
| tags | products picked at least once | 22 / 24 (91.7%) |
| tags | … also counting alternatives | 23 / 24 (95.8%) |
| tags | eligible products per kept step (min / median / max) | 1 / 1 / 5 |
| tags | profiles with a kept step under 5 eligible products | 3,072 / 3,072 (100.0%) |
| tags | profiles with a kept step under 3 eligible products | 3,072 / 3,072 (100.0%) |
| tags | requirements no eligible product met (each with a warning) | 3,072 |

Requirements no eligible product met, by cause (per session):

base: 648 over 1,944 profiles (0.33 per profile), 0 of them caused by a rule that needs tags; tags: 3,072 over 3,072 profiles (1.00 per profile), 1,984 of them caused by a rule that needs tags. A score is High in 33% of base-grid profiles and 50% of tag-grid profiles (band midpoints per score), so the steps only a High score adds, including those that often have no eligible product, come up more often per profile on the tag grid. Causes that need tags (the avoid list, a duplicate of an active in use, a clash with one) exist only there. Each product counts under its first hard-rule reason (an active in use is checked before the morning rules).

| Requirement | Cause | Then | Base grid | Tag grid | Tag scenarios |
|---|---|---|---|---|---|
| AM cleanser: acne High (salicylic acid) | every product meeting it is left out: a strong active (sensitive skin) | the core step fell back | 324 | 704 | none answered, retinol, prescription retinoid, retinoid checkbox, benzoyl peroxide, vitamin C, niacinamide, exfoliant checkbox, avoid fragrance, avoid acids, avoid alcohol, sulfates, parabens, lanolin |
| AM serum: pigmentation High (alpha arbutin) | every product meeting it is left out: an evening-only active (morning) | no step | 324 | 384 | none answered, vitamin C, niacinamide, exfoliant checkbox, avoid fragrance, avoid alcohol, sulfates, parabens, lanolin |
| AM serum: pigmentation High (alpha arbutin) | every product meeting it is left out: clashes with an active in use | no step | 0 | 320 | retinol, prescription retinoid, retinoid checkbox, salicylic acid, benzoyl peroxide |
| PM treatment: acne High (benzoyl peroxide) | every product meeting it is left out: clashes with an active in use | no step | 0 | 320 | retinol, prescription retinoid, retinoid checkbox, salicylic acid, vitamin C |
| AM cleanser: acne High (salicylic acid) | every product meeting it is left out: clashes with an active in use | the core step fell back | 0 | 256 | retinol, prescription retinoid, retinoid checkbox, benzoyl peroxide |
| PM exfoliant: pore High (bha) | every product meeting it is left out: clashes with an active in use | no step | 0 | 256 | retinol, prescription retinoid, retinoid checkbox, benzoyl peroxide |
| PM serum: wrinkle High (retinol) | every product meeting it is left out: clashes with an active in use | no step | 0 | 192 | salicylic acid, benzoyl peroxide, vitamin C |
| AM serum: base (vitamin c) | every product meeting it is left out: clashes with an active in use | no step | 0 | 128 | retinol, prescription retinoid, retinoid checkbox, benzoyl peroxide |
| AM serum: redness High (azelaic acid) | every product meeting it is left out: clashes with an active in use | no step | 0 | 128 | salicylic acid |
| PM serum: redness High (azelaic acid) | every product meeting it is left out: clashes with an active in use | no step | 0 | 128 | salicylic acid |
| AM cleanser: acne High (salicylic acid) | every product meeting it is left out: the avoid list | the core step fell back | 0 | 64 | avoid acids |
| AM serum: pigmentation High (alpha arbutin) | every product meeting it is left out: the avoid list | no step | 0 | 64 | avoid acids |
| PM exfoliant: pore High (bha) | every product meeting it is left out: the avoid list | no step | 0 | 64 | avoid acids |
| AM serum: acne High (azelaic acid) | every product meeting it is left out: clashes with an active in use | no step | 0 | 32 | salicylic acid |
| PM serum: acne High (azelaic acid) | every product meeting it is left out: clashes with an active in use | no step | 0 | 32 | salicylic acid |
| Total |  |  | 648 | 3,072 |  |

### 8. Catalog gaps: slots with fewer than 5 eligible products (base grid)

> **Catalog: 24 synthetic placeholders (development only). These numbers are not report results.**

Who a slot fails to serve is the profiles for which it had fewer than 5 eligible products, none, or lost its product to conflict resolution; the under-3 column counts the same with fewer than 3. Eligible: min / median / max over the steps it filled.

| Slot | Fails to serve | Under 5 / requiring it | Under 3 / requiring it | Eligible | Removed for a conflict | Empty: hard rule | Empty: none in catalog | Dropped for sensitive skin |
|---|---|---|---|---|---|---|---|---|
| AM/PM cleanser: base (any) | combination, normal; sensitive or not | 972 / 972 (100.0%) | 0 / 972 (0.0%) | 3 / 3 / 4 | 0 | 0 | 0 | 0 |
| AM/PM cleanser: base (cream) | dry; sensitive or not | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 2 / 2 / 2 | 0 | 0 | 0 | 0 |
| AM/PM cleanser: base (foaming) | oily; sensitive or not | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM cleanser: acne High (salicylic acid) | oily, dry, combination, normal; sensitive or not; acne High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | 1 / 1 / 1 | 0 | 324 | 0 | 0 |
| PM exfoliant: pore High (bha) | oily, dry, combination, normal; sensitive or not; pore High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | 1 / 1 / 1 | 228 | 0 | 0 | 324 |
| AM serum: base (antioxidant) | normal; not sensitive | 243 / 243 (100.0%) | 243 / 243 (100.0%) | 2 / 2 / 2 | 0 | 0 | 0 | 0 |
| AM serum: base (centella) | combination, normal; sensitive only | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM/PM serum: base (hyaluronic acid) | dry; sensitive or not | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 1 / 1 / 2 | 0 | 0 | 0 | 0 |
| AM/PM serum: base (niacinamide) | oily; sensitive or not | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM serum: base (vitamin c) | combination; not sensitive | 243 / 243 (100.0%) | 243 / 243 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM/PM serum: acne High (azelaic acid) | oily, dry, combination, normal; sensitive only; acne High | 216 / 216 (100.0%) | 216 / 216 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM serum: pigmentation High (alpha arbutin) | oily, dry, combination, normal; sensitive or not; pigmentation High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | none filled | 0 | 324 | 0 | 324 |
| PM serum: pigmentation High (tranexamic acid) | oily, dry, combination, normal; sensitive or not; pigmentation High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM/PM serum: redness High (azelaic acid) | oily, dry, combination, normal; sensitive or not; redness High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | 1 / 1 / 1 | 108 | 0 | 0 | 0 |
| PM serum: wrinkle High (retinol) | oily, dry, combination, normal; sensitive or not; wrinkle High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | 1 / 1 / 1 | 108 | 0 | 0 | 324 |
| PM treatment: base (facial oil) | dry; sensitive or not | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| PM treatment: acne High (benzoyl peroxide) | oily, dry, combination, normal; not sensitive; acne High | 324 / 324 (100.0%) | 324 / 324 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM/PM moisturiser: base (lightweight) | oily, combination; sensitive or not | 972 / 972 (100.0%) | 972 / 972 (100.0%) | 2 / 2 / 2 | 0 | 0 | 0 | 0 |
| AM/PM moisturiser: base (rich) | dry; sensitive or not | 486 / 486 (100.0%) | 486 / 486 (100.0%) | 2 / 2 / 2 | 0 | 0 | 0 | 0 |
| AM moisturiser: wrinkle High (peptide) | oily, dry, combination, normal; sensitive or not; wrinkle High | 648 / 648 (100.0%) | 648 / 648 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |
| AM sunscreen: base (any) | dry, combination, normal; not sensitive | 729 / 729 (100.0%) | 729 / 729 (100.0%) | 2 / 2 / 2 | 0 | 0 | 0 | 0 |
| AM sunscreen: base (spf 50 or spf 30) | oily; not sensitive | 243 / 243 (100.0%) | 243 / 243 (100.0%) | 2 / 2 / 2 | 0 | 0 | 0 | 0 |
| AM sunscreen: sensitive (mineral) | oily, dry, combination, normal; sensitive only | 972 / 972 (100.0%) | 972 / 972 (100.0%) | 1 / 1 / 1 | 0 | 0 | 0 | 0 |

What a product in each thin slot would need (characteristics only):

- **AM/PM cleanser: base (any)**
  - category cleanser; any cleanser
  - targets it would rank on: combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, AHAs, retinoids, benzoyl peroxide, niacinamide, ascorbic acid, azelaic acid
- **AM/PM cleanser: base (cream)**
  - category cleanser; texture cream, milk, balm
  - targets it would rank on: dry skin: humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, AHAs, ascorbic acid, retinoids, benzoyl peroxide, azelaic acid
- **AM/PM cleanser: base (foaming)**
  - category cleanser; foaming: foaming
  - targets it would rank on: oily skin: niacinamide, zinc; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): ascorbic acid, BHAs, AHAs, retinoids, benzoyl peroxide, azelaic acid
- **AM cleanser: acne High (salicylic acid)**
  - category cleanser; lists salicylic acid
  - targets it would rank on: breakouts: niacinamide, azelaic, zinc; oily skin: niacinamide, zinc; dry skin: humectant; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid; nothing that clashes with a product these routines hold (in at least one profile): benzoyl peroxide, AHAs, retinoids, niacinamide, ascorbic acid
- **PM exfoliant: pore High (bha)**
  - category exfoliant; lists an ingredient of the bha class
  - targets it would rank on: visible pores: niacinamide, zinc; oily skin: niacinamide, zinc; dry skin: humectant; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); nothing that clashes with a product these routines hold (in at least one profile): BHAs, ascorbic acid, AHAs, retinoids, benzoyl peroxide
- **AM serum: base (antioxidant)**
  - category serum; lists an ingredient of the antioxidant class
  - targets it would rank on: normal skin: antioxidant, humectant
  - exclusions: in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): azelaic acid, benzoyl peroxide, AHAs, retinoids, BHAs
- **AM serum: base (centella)**
  - category serum; lists an ingredient of the centella class
  - targets it would rank on: combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs
- **AM/PM serum: base (hyaluronic acid)**
  - category serum; lists hyaluronic acid
  - targets it would rank on: dry skin: humectant, barrier lipids, emollient; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, AHAs, retinoids, benzoyl peroxide, ascorbic acid, azelaic acid
- **AM/PM serum: base (niacinamide)**
  - category serum; lists niacinamide
  - targets it would rank on: oily skin: niacinamide, zinc; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, AHAs, retinoids, benzoyl peroxide, ascorbic acid, azelaic acid
- **AM serum: base (vitamin c)**
  - category serum; lists an ingredient of the vitamin c class
  - targets it would rank on: combination skin: niacinamide, humectant
  - exclusions: in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): azelaic acid, benzoyl peroxide, AHAs, retinoids, BHAs
- **AM/PM serum: acne High (azelaic acid)**
  - category serum; lists azelaic acid
  - targets it would rank on: breakouts: niacinamide, azelaic, zinc; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): ascorbic acid
- **AM serum: pigmentation High (alpha arbutin)**
  - category serum; lists alpha arbutin
  - targets it would rank on: pigmentation: arbutin, tranexamic, vitamin C, azelaic, niacinamide; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step)
- **PM serum: pigmentation High (tranexamic acid)**
  - category serum; lists tranexamic acid
  - targets it would rank on: pigmentation: arbutin, tranexamic, vitamin C, azelaic, niacinamide; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, ascorbic acid, AHAs, retinoids, benzoyl peroxide, azelaic acid
- **AM/PM serum: redness High (azelaic acid)**
  - category serum; lists azelaic acid
  - targets it would rank on: redness: azelaic, centella, soothing, niacinamide; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): ascorbic acid, AHAs, retinoids, benzoyl peroxide, BHAs, niacinamide, azelaic acid
- **PM serum: wrinkle High (retinol)**
  - category serum; lists an ingredient of the retinoid class
  - targets it would rank on: fine lines: peptide, vitamin C, humectant; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); nothing that clashes with a product these routines hold (in at least one profile): BHAs, ascorbic acid, AHAs, retinoids
- **PM treatment: base (facial oil)**
  - category treatment; texture oil and an oil with no water
  - targets it would rank on: dry skin: humectant, barrier lipids, emollient; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, AHAs, ascorbic acid, retinoids, benzoyl peroxide, azelaic acid
- **PM treatment: acne High (benzoyl peroxide)**
  - category treatment; lists benzoyl peroxide
  - targets it would rank on: breakouts: niacinamide, azelaic, zinc; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant
  - exclusions: nothing that clashes with a product these routines hold (in at least one profile): BHAs, ascorbic acid
- **AM/PM moisturiser: base (lightweight)**
  - category moisturiser; texture liquid, gel, gel-cream, fluid, lotion
  - targets it would rank on: oily skin: niacinamide, zinc; combination skin: niacinamide, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): ascorbic acid, BHAs, AHAs, retinoids, benzoyl peroxide, niacinamide, azelaic acid
- **AM/PM moisturiser: base (rich)**
  - category moisturiser; texture cream, balm
  - targets it would rank on: dry skin: humectant, barrier lipids, emollient; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, AHAs, retinoids, ascorbic acid, benzoyl peroxide, azelaic acid
- **AM moisturiser: wrinkle High (peptide)**
  - category moisturiser; lists an ingredient of the peptide class
  - targets it would rank on: fine lines: peptide, vitamin C, humectant; oily skin: niacinamide, zinc; dry skin: humectant, barrier lipids, emollient; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): benzoyl peroxide, AHAs, retinoids, BHAs, ascorbic acid, niacinamide, azelaic acid
- **AM sunscreen: base (any)**
  - category sunscreen; any sunscreen
  - targets it would rank on: dry skin: humectant; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant
  - exclusions: in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): benzoyl peroxide, AHAs, retinoids, niacinamide, azelaic acid, BHAs
- **AM sunscreen: base (spf 50 or spf 30)**
  - category sunscreen; SPF 50 or higher or SPF 30 or higher
  - targets it would rank on: oily skin: niacinamide, zinc
  - exclusions: in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): ascorbic acid, azelaic acid, benzoyl peroxide, AHAs, retinoids, BHAs
- **AM sunscreen: sensitive (mineral)**
  - category sunscreen; mineral UV filters only
  - targets it would rank on: oily skin: niacinamide, zinc; dry skin: humectant; combination skin: niacinamide, humectant; normal skin: antioxidant, humectant; sensitive skin: soothing, centella, barrier lipids (sensitive)
  - exclusions: for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; fragrance-free; ideally no drying alcohol or chemical UV filter (it lowers the rank); in the morning: no retinoid or AHA; ideally no strong active (it would rank last in this step); nothing that clashes with a product these routines hold (in at least one profile): BHAs, ascorbic acid

Known gaps:

Each status counts only the profiles the gap concerns (events are per session).

| Gap | Slot | Profiles concerned | On this grid |
|---|---|---|---|
| Morning pigmentation product without AHAs | AM serum: pigmentation High (alpha arbutin) | pigmentation High: 648 | required by 648 / 648 (100.0%); never filled; empty 324 times (324 every product left out by a hard rule, 0 none in the catalog); dropped for sensitive skin 324 times |
| A non-retinoid wrinkle option for sensitive skin | PM serum: wrinkle High (retinol) | sensitive, wrinkle High: 324 | required by 324 / 324 (100.0%); never filled; empty 0 times (0 every product left out by a hard rule, 0 none in the catalog); dropped for sensitive skin 324 times |
| A non-retinoid wrinkle option for sensitive skin | AM moisturiser: wrinkle High (peptide) | sensitive, wrinkle High: 324 | required by 324 / 324 (100.0%); filled 324 times (eligible min 1, max 1), 0 of them removed for a conflict; empty 0 times (0 every product left out by a hard rule, 0 none in the catalog); dropped for sensitive skin 0 times |
| Gentle non-foaming cleansers | AM/PM cleanser: base (cream) | all: 1,944 | required by 486 / 1,944 (25.0%); filled 891 times (eligible min 2, max 2), 0 of them removed for a conflict; empty 0 times (0 every product left out by a hard rule, 0 none in the catalog); dropped for sensitive skin 0 times |
| The empty morning dark-spot step | AM serum: pigmentation High (alpha arbutin) | pigmentation High: 648 | required by 648 / 648 (100.0%); never filled; empty 324 times (324 every product left out by a hard rule, 0 none in the catalog); dropped for sensitive skin 324 times |
<!-- evaluation:end -->

## Known limitations

1. **Hand-set rules and targets, no outcome data.** Nothing here was fitted or
   validated. The ranker's weights are domain judgements set before the evaluation, and
   the evaluation can't say whether a ranked routine is better for anyone.
2. **Synthetic placeholder catalog** (24 products, 1-2 candidates for most steps). The
   evaluation's catalog-gap section lists every thin slot. Gaps it causes today
   (catalog characteristics to fill in 7c-iii):
   - **a morning pigmentation product without AHAs**: the only alpha-arbutin serum lists
     lactic acid, so the **morning dark-spot step is empty for everyone**;
   - **a non-retinoid wrinkle option for sensitive skin**: the evening retinol step is
     dropped for them;
   - **gentle (non-foaming) cleansers**: only 4 cleansers exist;
   - sensitive users with High acne or pores get a substitution or no step, because the
     placeholder products for those steps contain strong actives.
3. **IDF over 3–5-ingredient lists is not meaningful.** The placeholder lists are 3 to 5
   ingredients long, and 33 of the 46 distinct ingredients appear in exactly one product,
   so IDF mostly reflects which invented product happened to list what. The formula is
   kept so that real, full-length labels (7c-iii) need no code change; the results must
   be re-run then.
4. **Ingredient presence and position, not concentration.** The ranker can't see
   percentages, formulation or pH; list position is a weak proxy for concentration, and
   none below about 1%.
5. **Face validity is circular**, and the other measures describe behaviour under the
   rules, not user benefit.
6. **A stated goal whose score is Low has no effect** (intended; see "Weights").
7. **The conflict table doesn't distinguish rinse-off from leave-on.** A salicylic-acid
   cleanser and a leave-on BHA count the same. (Only the evening-only AHA rule treats
   cleansers as rinse-off.)
8. **Conflicts are per session, not per day.** A pair split between morning and evening
   is not flagged.
9. **The retinoid + benzoyl peroxide row is deliberately conservative for adapalene**,
   which is stable with benzoyl peroxide (they are sold combined). The class row still
   keeps them apart.
10. **Strong-active suppression uses the preservative cutoff**, which is less
    conservative than strict membership: a product listing lactic acid after its
    preservative is taken to use it as a pH adjuster, and can be recommended to sensitive
    skin. The avoid list (7c-i c) uses strict membership.
11. **"Fragrance-free" means "no declared fragrance"**: an undeclared fragrance component
    can't be seen in an ingredient list. The declared allergens are the EU 26.
12. **Current products come from the questionnaire's tags only**: a product named by
    brand ("CeraVe Hydrating Cleanser") gives no actives unless its active is named too.
    Profiles saved before 7c-i (c), or whose tags were dropped at signup, have none.
13. **Not medical advice.**

## Testing

```bash
python -m pytest app/services/recommendation   # from backend/
```

- `test_matching.py`: every keyword's matcher; format fields; facial oil needs both
  conditions; whole-token ingredients; classes with the cutoff.
- `test_engine.py`: each rule on small synthetic catalogs (sensitivity as a modifier,
  fragrance as a hard rule, substitutions, band triggers, concern priority, evening-only
  actives, fallbacks keeping the hard rules, fail-closed unknowns, class conflicts,
  cautions, determinism), and the invariants over 2,430 profiles on the fixture catalog:
  no conflicting pair in any session, no strong active or fragrance for sensitive skin,
  no retinoid or leave-on AHA in the morning, every core step filled, every left-out
  product with a reason.
- `test_current_products.py`: the questionnaire tags, and the invariants over 3,072
  profiles × tag scenarios.
- `test_ranker.py`: TF-IDF checked by hand, targets, the band scale and the stated goal,
  category scopes, penalties, filler invariance, and each sort key on synthetic catalogs.
- `test_ranked_grid.py`: over both grids (5,502 profiles), the ranked set is the eligible
  set, the sort keys hold for every pick, alternatives are safe swaps, no avoided
  ingredient or active-in-use conflict is ranked, determinism with a shuffled catalog,
  the rule-order digest and the ranked-grid digest (both on the fixture catalog).
- `test_find_conflict_equivalence.py` (7c-iii 2a): keeps the old pair-by-pair `find_conflict`
  as the reference; the row-by-row one returns the same conflict and reason on every
  ordered pair of the real and fixture catalogs, under random tables with ties, and on
  random sessions.
- `test_real_catalog.py` (7c-iii): on the real catalog (`backend/catalog/products.json`),
  over both grids: the ranked set is the eligible set, no two products in a session
  clash (core pairs included), no strong active, L-ascorbic acid or fragrance for
  sensitive skin, no avoided ingredient, duplicate or clash with an active in use, no
  retinoid or leave-on AHA in the morning, determinism; and a recorded snapshot of
  eleven routines (`app/tests/snapshots/routine_real_catalog.json`). Slow (a few minutes).
- `test_explain.py`: banned words in the templates and in every generated sentence, the
  rule text matching the rule that created the step, the ranking sentence, examples.
- `test_evaluate.py`: the report is deterministic, carries the banner in every section,
  names no product in the gap report, and the README's results match the config.
- App-level: `app/tests/test_routine_behaviour.py` (recorded snapshots, and the why and
  alternatives in the API), `test_scan_to_routine.py`, `test_seed.py`,
  `test_migration_7c.py`, `test_migration_7c_iii.py`. The test database holds the fixture
  catalog (`app/tests/catalog_fixture.py`), never the real one.
