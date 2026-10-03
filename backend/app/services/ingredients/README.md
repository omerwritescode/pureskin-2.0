# Ingredient normaliser and vocabulary (roadmap step 7c)

One normaliser for every ingredient decision in PureSkin: the routine rules, the
conflict checks, the ranker (7c-ii) and the catalog loader (7c-iii). It turns an
ingredient list into **one canonical token per ingredient** and decides which **classes**
each ingredient belongs to. Pure Python, no dependencies, no I/O.

> **A vocabulary, not a model.** Every synonym, class member and list below is a
> reviewed judgement written into `ingredient_config.py`. Nothing was learned from data.
> The vocabulary covers the seeded catalog completely; anything outside it is reported
> for review instead of guessed.

**Status:** live since 7c-i (a). The routine matches its ingredient keywords through it.
Conflicts, strong-active suppression and session rules use it from 7c-i (b), and the
avoid list from 7c-i (c).

---

## Interface

```python
from app.services.ingredients import (
    split_inci, canonical, normalise_ingredients, memberships, in_class,
    fragrance_free, mineral_only, anhydrous_oil,
)

split_inci("Water (Aqua, Eau), 1,2-Hexanediol, Niacinamide")
# ['Water (Aqua, Eau)', '1,2-Hexanediol', 'Niacinamide']
canonical("CI 77891 (Titanium Dioxide)")   # 'titanium dioxide'
items = normalise_ingredients(["Aqua", "Lactic Acid", "Phenoxyethanol"])
items.tokens                                # ('water', 'lactic acid', 'phenoxyethanol')
items.unknown, items.invalid                # (), ()  -> fully known
in_class(items, "aha", strict=False)        # True: lactic acid is before the cutoff
```

| Function | Returns |
|---|---|
| `split_inci(text)` | ingredient names; splits on commas, never inside brackets or between digits, never on whitespace |
| `canonical(name)` | the canonical token (possibly unknown); raises `InvalidIngredientName` if the name can't be cleaned safely |
| `normalise_ingredients(names)` | `NormalisedIngredients`: tokens with their list positions, plus `unknown` and `invalid` |
| `memberships(items, strict=...)` | the classes each ingredient counts toward, and the ambiguous ones the cutoff dismissed |
| `fragrance_free`, `mineral_only`, `anhydrous_oil` | the three product properties an ingredient list gives reliably |

## Normalisation

Applied to each ingredient name, in this order (rules in `ingredient_config.py`):

1. Footnote marks removed (`* † ‡ ° ® ™` and superscript digits), before Unicode
   normalisation could turn `¹` into a `1`.
2. Unicode NFKC, lowercase; dashes and apostrophes unified.
3. Percentages removed (`Niacinamide 10%` → `niacinamide`).
4. Bracketed text removed, `(…)` and `[…]` (`Salicylic Acid (BHA)`, `Titanium Dioxide [nano]`).
   The bracket's content is kept only as a fallback: it is used when the outer name is
   unknown (`Trade Name (Niacinamide)` → `niacinamide`).
5. Spaces collapsed; trailing `. , ;` removed.
6. **Fail closed:** what is left may contain only lowercase ASCII letters, digits and
   ` ,'./+-`. Anything else, including `:` and any non-ASCII letter, raises
   `InvalidIngredientName`. A pasted `Ingredients:` prefix fails here rather than
   becoming part of a name.
7. Synonyms: another name for the same substance (or its salt) maps to one token
   (`aqua` → `water`, `nicotinamide` → `niacinamide`, `sodium hyaluronate` →
   `hyaluronic acid`, `avobenzone` → `butyl methoxydibenzoylmethane`).

A token is **one whole ingredient**. `salicylic acid`, `glycolic acid` and `hyaluronic acid`
are three unrelated tokens; `acid` on its own is unknown. `homosalate` (a UV filter) is
not salicylic acid, and `palmitoyl pentapeptide-4` is a peptide because the peptide class
lists it, not because its name contains "peptide".

### Reuse of the questionnaire lexicon

The lexicon's actives (`ACTIVE_TERMS` keys) are canonical tokens here, so a tag such as
`"salicylic acid"` from the questionnaire means the same ingredient (a test checks every
key). Only the lexicon aliases that are real ingredient-list names are reused
(nicotinamide, L-ascorbic acid, sodium hyaluronate). Its free-text shorthands (`bha`,
`aha`, `bpo`, `vit c`, `txa`, `arbutin`) are never applied to ingredient lists.

## Classes

A token can be in several classes (ascorbic acid is `vitamin_c` and `antioxidant`).

| Class | Members (canonical tokens) |
|---|---|
| `retinoid` | retinol, retinal, retinyl palmitate / acetate / propionate / linoleate, retinyl retinoate, hydroxypinacolone retinoate, vitamin a; prescription: adapalene, tretinoin, tazarotene, trifarotene, isotretinoin |
| `benzoyl_peroxide` | benzoyl peroxide |
| `aha` | glycolic acid, ammonium glycolate, sodium glycolate, lactic acid, ammonium lactate, mandelic acid, malic acid, tartaric acid |
| `bha` | salicylic acid, betaine salicylate, capryloyl salicylic acid, sodium salicylate |
| `pha` | gluconolactone, lactobionic acid, maltobionic acid |
| `vitamin_c` | ascorbic acid and five stable derivatives |
| `antioxidant` | the `vitamin_c` members, ferulic acid, resveratrol, camellia sinensis leaf extract |
| `peptide`, `centella`, `ceramide` | named members only |
| `fragrance` | fragrance (parfum, perfume), aroma |
| `fragrance_allergen` | the 26 EU-declared fragrance allergens |
| `essential_oil` | 16 named essential oils |
| `uv_mineral` / `uv_organic` | zinc oxide, titanium dioxide / 22 organic filters |
| `water_phase` | water, aloe barbadensis leaf juice, two floral/plant waters |
| `oil` | oils, butters and ester emollients (not silicones) |

Deliberate exclusions (each one tested):
- **Not BHAs:** salicylate esters (ethylhexyl salicylate and homosalate are UV filters;
  butyloctyl and tridecyl salicylate are emollients; benzyl salicylate is a fragrance
  allergen) and **willow bark extract** (it contains salicin, not salicylic acid).
- **Not AHAs:** citric acid, sodium citrate and sodium lactate, usually pH adjusters or
  buffers.
- **Not PHAs:** sodium and calcium gluconate (chelators).
- **Not antioxidants:** tocopherol (and ascorbyl palmitate, which isn't in the vocabulary
  yet). Most formulas carry them in trace amounts to protect the formula itself.
- **Not essential oils:** carrier oils such as `rosa canina seed oil`. There is no
  pattern rule ("… oil"), because a carrier oil and an essential oil can look alike.

## The ambiguous-member rule (a proxy for the ~1% line)

Some class members are often present only in trace amounts, as pH adjusters or
antioxidants: lactic, malic and tartaric acid (AHA), sodium salicylate (BHA), and the
retinyl esters (palmitate, acetate, propionate, linoleate). In a real ingredient list,
"lactic acid" near the end is usually a pH adjuster, not an exfoliant.

INCI lists are in descending order of concentration down to 1%, and preservatives are
used at about 1% or less. So everything listed after a preservative is probably below
1%. The rule uses that:

- an **ambiguous member** counts toward its class only if it appears **at or before the
  first recognised preservative** (the cutoff); with no recognised preservative, it counts;
- a **non-ambiguous member** always counts (glycolic acid is an AHA wherever it is listed);
- an ambiguous member is **never the cutoff** itself, even if it is also a preservative
  (sodium salicylate);
- only preservatives whose usual maximum use level is about 1% or less are cutoffs
  (`PRESERVATIVES`: phenoxyethanol, parabens, benzoates, sorbates, …). Multifunctional
  glycols and boosters (1,2-hexanediol, caprylyl glycol, ethylhexylglycerin, pentylene
  glycol, …) are often used above 1%, so they are `NEUTRAL`: known, class-less, never a cutoff.

**Strict vs cutoff.** `memberships()` takes a required `strict` flag:
- `strict=True` counts every member. The **avoid list** uses it: it is the user's own
  stated preference, so a trace of an ingredient they avoid still counts. The
  fragrance-free property is strict too.
- `strict=False` applies the cutoff. **Conflicts, strong-active suppression and the
  session rules** use it. This is **less conservative than strict**: a sensitive user can
  be recommended a product that lists lactic acid after its preservative, because that
  lactic acid is taken to be a pH adjuster.

The rule is a proxy. A brand can list a preservative early, or an ambiguous member can
be an active below 1% (retinyl palmitate is used that way). The review command lists
every membership the cutoff dismissed, product by product, so it can be checked by eye
against real products.

## Derived properties

Only what an ingredient list gives reliably:

| Property | True when |
|---|---|
| `fragrance_free` | no ingredient in `fragrance`, `fragrance_allergen` or `essential_oil` (strict) |
| `mineral_only` | at least one `uv_mineral` filter and no `uv_organic` one |
| `anhydrous_oil` | no `water_phase` ingredient anywhere, and the first ingredient is an `oil` |

Texture, foaming, "oil-free" and "rich" are **not** derived: they can't be read reliably
off a real INCI list (a foaming cleanser and a cream cleanser can share surfactants).
From 7c-i (b) they are product fields filled when the catalog is seeded.

## Class references in the conflict table

From 7c-i (b), a conflict row may name a whole class as `class:<name>`
(`class:retinoid`). Collisions with ingredient names are impossible by construction:
no ingredient name may contain `:` (the normaliser rejects it), and class names are
`[a-z][a-z0-9_]*`.

## Review command

```bash
python -m app.services.ingredients.review     # from backend/: the seeded catalog
```

It prints a markdown report with:
1. **unknown ingredients**, with how many products use each. Any token containing oil,
   peel, flower, leaf, extract, water or juice is flagged for a **second look** before
   it may join `NEUTRAL`: it may be an essential oil, a fragranced botanical or a
   water phase;
2. names that can't be normalised (`:` or non-ASCII);
3. products that are not fragrance-free **only because of benzyl alcohol** (it is also a
   common preservative);
4. per product, every ambiguous membership the cutoff dismissed (ingredient, class,
   position, cutoff preservative).

**Fail closed:** an unknown or invalid ingredient name is never guessed. A product with
one is not loaded (7c-iii) and never recommended until a person has reviewed the token
and added it to the vocabulary. On the seeded catalog, every section is empty.

## Testing

```bash
python -m pytest app/services/ingredients     # from backend/
```

- `test_normalise.py`: splitting (brackets, `1,2-hexanediol`, `[nano]`), canonical
  forms, names that fail closed, whole-token matching (acids sharing the word "acid",
  salicylate esters, retinoid derivatives).
- `test_membership.py`: the ambiguous-member rule on synthetic lists (lactic acid
  before/after phenoxyethanol, retinyl palmitate late in a sunscreen, no preservative,
  sodium salicylate never the cutoff, glycols never the cutoff, strict mode).
- `test_properties.py`: fragrance-free, mineral-only, anhydrous oil.
- `test_vocabulary.py`: the config is consistent (canonical forms, no `:`, synonyms lead
  to known tokens, NEUTRAL is class-less) and the 24 seeded products are fully known.
- `test_review.py`: the review report.

## Known limitations

1. **The vocabulary is hand-written and finite.** It covers the seeded catalog and the
   reviewed families, not the full INCI dictionary. Real catalogs will hit unknown
   tokens; the review command and fail-closed loading are how that is handled.
2. **The fragrance allergens are the EU 26.** The EU extended the list in 2023; those
   additions are to be added from the official text, not from memory.
3. **"Fragrance-free" means "no declared fragrance".** An undeclared fragrance component,
   or one hidden inside a botanical extract, can't be seen in an ingredient list.
4. **Willow bark is not counted as a BHA** (salicin, not salicylic acid), although some
   brands market it as one.
5. **The cutoff is a proxy for the 1% line**, not a measurement: brands don't publish
   concentrations, and ingredients below 1% may be listed in any order.
6. **The 24 seeded products are synthetic placeholders** with short invented ingredient
   lists, so the review being clean on them says nothing about real products.
