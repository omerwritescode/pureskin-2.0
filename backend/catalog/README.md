# Product catalog (roadmap step 7c-iii)

`products.json` is the product catalog: real products, one row each, and the only source
of products for the database (`seed.py`) and the recommendation evaluation.

> **Ingredient lists: sourced from the cited pages; spot-checked by a person: not yet.**
> Each list was copied from the page cited in its row (`source_url`) and checked by
> script as exact text against the staging copy (`python -m app.services.catalog.promote
> --staging ../catalog_staging`). No person has yet compared it with the live page
> (CLAUDE.md, "Deferred verification"). Brands change formulas; a list can be out of date.

**Version:** `products-1.0.0` (37 products, lists copied 2026-10-06). The rows change only
with a version bump: `app/services/catalog/tests/test_loader.py` fingerprints them.

## What a row holds

| Field | Meaning |
|---|---|
| `catalog_id`, `sheet_row` | the row's id in the staging lists (B = catalog list, A = brand-to-active list) and its sheet row |
| `name`, `brand`, `original_name` | display name and brand (reviewed); `original_name` is the sheet's name, unchanged |
| `category`, `texture`, `foaming`, `spf`, `spf_verbatim` | reviewed format fields (texture and foaming from the page's own words; see `review_notes`), and the labelled SPF as printed |
| `market` | `india` (the list is from the brand's Indian page) or `global` (from a non-India page; the version sold in India may differ). The catalog and routine pages are to label it "Global ingredient list" (step 7c-iii, unit 3) |
| `fetch_status`, `list_kind`, `copied_from` | `ok` or `ok_global_market`; `full_inci` (a full ingredient list); `page_text` |
| `source_url`, `retailer_url`, `date_checked` | the page the list was copied from; the retailer link in the sheet (often blocked, kept for tracing); the date |
| `ingredients_verbatim`, `verbatim_sha256` | the list exactly as copied, and its hash. **Never edited.** |
| `cleaning` | reviewed per-row cleaning directives (below) |
| `expected_constraints`, `preferred`, `known_mismatches` | what the row's slot expects of the list; a constraint the list fails is recorded with the reason and reported, never fixed or weakened |
| `notes`, `review_notes` | the staging notes, unchanged; the decisions made when the row was promoted |

Beside `products`, the file holds `version`, `about` and `not_promoted` (below).

## From page text to ingredients

The loader (`app/services/catalog/loader.py`) never changes `ingredients_verbatim`. It:

1. cleans a copy of it (`app/services/ingredients/clean.py`, rules in
   `ingredient_config.py`): a mojibake non-breaking space, line breaks and bullets as
   separators, words broken by a line-end hyphen, the spaces around a slash between
   alternative names, and the INCI blend notation `(and)`. A row's own directives add:
   `format: "drug_facts"` (B17), `strip_bracket_notes` (B21, B35: bracketed function
   notes), `split_on` `" & "` or `" and "` (B15, B16, B28), and exact-text
   `corrections` that must occur once (B28: `Ceramide 1, 2, 3, 4, 6II` written out as
   five names). Every step is logged; the logs and names are recorded in
   `app/tests/snapshots/catalog_cleaning.json`;
2. normalises the names (`app/services/ingredients/`); an unreviewed name fails the
   whole load (fail closed);
3. checks provenance (https `source_url`, date, a seedable `fetch_status` that agrees with
   `market`, a full list), a sunscreen's labelled SPF (at least 30, equal to the number in
   `spf_verbatim`), one row per product (`catalog_id`, `sheet_row`, brand + name and
   `source_url` each unique), the verbatim hash, and `expected_constraints` against
   properties derived from the list.

Any problem in any row stops the whole load: a partly loaded catalog would silently
change routines.

## Rows not in the catalog

The 14 staging rows deliberately left out (B05, B33, and every List A row except A09 and
A13) are recorded with their reasons in `products.json` under `not_promoted`, and printed
by the load report. In short: B05 is not an INCI list (its preservatives aren't named);
B33 was dropped (its product is A07, promoted as B37); A04 is held back (a cream, and the
wrinkle step is a serum step); the other List A rows are composition lines, names only or
prescription products, a rinse-off peel (A11), or a list with a stray comma and seven
essential oils (A12). A row can't be both in the catalog and not promoted.

## Commands (from `backend/`)

```bash
python -m app.services.catalog                                   # load products.json, print the load report
python -m app.services.ingredients.review                        # unreviewed or invalid names, flags
python seed.py                                                   # products = this file (prunes any other product)
python -m app.services.ingredients.review --staging ../catalog_staging   # every staging row
python -m app.services.catalog.promote --staging ../catalog_staging      # exact-text check against staging
python -m app.services.catalog.promote --staging ../catalog_staging --new B38   # a skeleton row
```

## Adding a row

1. Copy the list from the product's page into the staging sheet, as for the 50-row fill.
2. `promote --new <id>` prints a row with every copied field filled; fill the reviewed
   fields (`name`, `brand`, `category`, `texture`, `foaming`, `spf`, `market`,
   `list_kind`, `cleaning`, `known_mismatches`, `review_notes`) and add it to `products.json`.
3. Run the review command; any unreviewed name goes through review into
   `ingredient_config.py` (with a version bump) before the row can load.
4. Run `promote` (exact text) and the loader, bump `version`, record its fingerprint in
   `test_loader.py`, and re-record the cleaning snapshot (`UPDATE_SNAPSHOTS=1`) after
   reading its diff.
