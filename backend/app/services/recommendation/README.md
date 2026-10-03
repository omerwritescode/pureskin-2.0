# Recommendation Engine (roadmap step 7c)

Builds the AM/PM routine shown on `/app/routine/` from the user's latest Skin Profile,
the product catalog and the ingredient-conflict table. **Rules first:** documented,
hand-set rules decide which products are eligible for each step. (A content-based
ranker that only orders eligible products is 7c-ii; it is not built yet.)

> **Not medical advice, and not validated.** Every rule here is a hand-set judgement in
> `routine_config.py`. There is no outcome data (no feedback, no purchases, no follow-up)
> to fit or check them against. **The 24 products in the catalog are synthetic
> placeholders** (invented brands and short invented ingredient lists), so a routine
> shows how the rules behave, not what to buy.

**Status:** live since 7c-i (b), rule set `routine-2.0.0`. Pure functions: no database,
no FastAPI (`app/api/routine.py` loads the rows and shapes the response).

| File | What it holds |
|---|---|
| `routine_config.py` | every rule, keyword matcher and fixed text (versioned) |
| `rules.py` | Skin Profile → requirements (category + keywords), in priority order |
| `matching.py` | does a product meet a keyword (ingredients, classes, format fields) |
| `engine.py` | requirements + catalog + conflicts → routine, with every left-out product and why |

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
     oil);
   - it would go in the morning but contains a **retinoid** (any product) or an **AHA**
     (any leave-on product; a cleanser is rinsed off). The reason says "Not used in the
     morning routine because it contains lactic acid (an AHA); AHAs are evening-only"
     when the product is in the evening routine, and "Left out because…" when it isn't
     in the routine at all.
3. **Rule order.** Each step takes the first eligible product meeting its keywords:
   keyword order, then product id.
4. **Core steps never go missing for a keyword.** Cleanser, moisturiser and sunscreen
   fall back from a score step to the base step, then to any eligible product in the
   category. Every hard rule applies at every level, so a core step stays empty (with a
   warning) only when no product in its category is eligible.
5. **Sensitive substitutions** (`SENSITIVE_SUBSTITUTIONS`), each with a warning:
   - always: the morning base serum ("vitamin c" for combination skin, "antioxidant"
     for normal skin) → a centella serum;
   - when every product for the step is left out by a sensitive-skin hard rule: acne →
     azelaic acid instead of benzoyl peroxide; the morning dark-spot step, the evening
     retinol step and the pore step → none.
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
| niacinamide, hyaluronic acid, salicylic acid, benzoyl peroxide, azelaic acid, alpha arbutin, tranexamic acid, retinol | that canonical ingredient is listed |
| vitamin c, antioxidant, peptide, bha | an ingredient of that class counts (preservative cutoff) |

`texture`, `foaming` and `spf` are product columns (migration `99aa1b05ae54`), filled
when the catalog is seeded; an ingredient list can't give them reliably. The catalog
loader refuses a sunscreen without a labelled SPF of at least 30.

## Known limitations

1. **Hand-set rules, no outcome data.** Nothing here was fitted or validated.
2. **Synthetic placeholder catalog** (24 products, 1-2 candidates for most steps). Gaps
   it causes today (catalog characteristics to fill in 7c-iii):
   - **a morning pigmentation product without AHAs**: the only alpha-arbutin serum lists
     lactic acid, so the **morning dark-spot step is empty for everyone**;
   - **a non-retinoid wrinkle option for sensitive skin**: the evening retinol step is
     dropped for them;
   - **gentle (non-foaming) cleansers**: only 4 cleansers exist;
   - sensitive users with High acne or pores get a substitution or no step, because the
     placeholder products for those steps contain strong actives.
3. **The conflict table doesn't distinguish rinse-off from leave-on.** A salicylic-acid
   cleanser and a leave-on BHA count the same. (Only the evening-only AHA rule treats
   cleansers as rinse-off.)
4. **Conflicts are per session, not per day.** A pair split between morning and evening
   is not flagged.
5. **The retinoid + benzoyl peroxide row is deliberately conservative for adapalene**,
   which is stable with benzoyl peroxide (they are sold combined). The class row still
   keeps them apart.
6. **Strong-active suppression uses the preservative cutoff**, which is less
   conservative than strict membership: a product listing lactic acid after its
   preservative is taken to use it as a pH adjuster, and can be recommended to sensitive
   skin. The avoid list (7c-i c) will use strict membership.
7. **"Fragrance-free" means "no declared fragrance"**: an undeclared fragrance component
   can't be seen in an ingredient list. The declared allergens are the EU 26.
8. **The user's current products are not considered yet** (7c-i c stores the
   questionnaire's tags).

## Testing

```bash
python -m pytest app/services/recommendation   # from backend/
```

- `test_matching.py`: every keyword's matcher; format fields; facial oil needs both
  conditions; whole-token ingredients; classes with the cutoff.
- `test_engine.py`: each rule on small synthetic catalogs (sensitivity as a modifier,
  fragrance as a hard rule, substitutions, band triggers, concern priority, evening-only
  actives, fallbacks keeping the hard rules, fail-closed unknowns, class conflicts,
  cautions, determinism), and the invariants over 2,430 profiles on the seeded catalog:
  no conflicting pair in any session, no strong active or fragrance for sensitive skin,
  no retinoid or leave-on AHA in the morning, every core step filled, every left-out
  product with a reason.
- App-level: `app/tests/test_routine_behaviour.py` (recorded snapshots),
  `test_scan_to_routine.py`, `test_seed.py`, `test_migration_7c.py`.
