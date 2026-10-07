"""The catalog loader: backend/catalog/products.json loads; every rule turns a bad row away."""

import copy
import hashlib
import json

import pytest

from app.services.catalog import CatalogError, catalog_config as cfg, check_rows, load_catalog, product_records
from app.services.catalog.loader import CATALOG_FILE, format_report, run, verbatim_sha256
from app.services.ingredients import fragrance_free
from app.tests.snapshot import check_snapshot

DATA = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
ROWS = DATA["products"]
BY_ID = {row["catalog_id"]: row for row in ROWS}

# products.json versions and the fingerprint of their rows and not_promoted entries. When
# either changes: bump "version" in products.json and add it here with the fingerprint from
# the failure. Never edit a recorded fingerprint (an uncommitted version may be updated).
DATA_RECORDED = {
    "products-1.0.0": "a661bb284b899a8b",
}


def fingerprint(data) -> str:
    content = {"products": data["products"], "not_promoted": data["not_promoted"]}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_the_rows_change_only_with_a_version_bump():
    version, current = DATA["version"], fingerprint(DATA)
    assert version in DATA_RECORDED, f"New products.json version {version!r}: add {current!r} to DATA_RECORDED."
    assert DATA_RECORDED[version] == current, (
        f"products.json changed but its version is still {version!r}: bump it and record {current!r}.")


def test_the_catalog_loads(catalog):
    assert catalog.version == DATA["version"]
    ids = [p.catalog_id for p in catalog.products]
    assert len(ids) == 37 and ids[0] == "B01" and ids[-1] == "A13"
    assert "B05" not in ids and "B33" not in ids and "A07" not in ids  # refused, dropped, promoted as B37
    assert {p.market for p in catalog.products if p.fetch_status == "ok_global_market"} == {"global"}
    assert sum(p.market == "global" for p in catalog.products) == 13
    assert all(p.ingredients.fully_known for p in catalog.products)


def test_the_only_constraint_failure_is_the_recorded_one(catalog):
    failing = {(p.catalog_id, c) for p in catalog.products for c, ok in p.constraints if not ok}
    assert failing == {("B34", "anhydrous_oil")}
    assert {(p.catalog_id, c) for p in catalog.products for c in p.known_mismatches} == failing
    assert {(p.catalog_id, c) for p in catalog.products for c in p.preferred_unmet} == {("B34", "fragrance_free")}


def test_the_sensitive_slot_products_are_fragrance_free_and_the_others_are_named(catalog):
    by_id = {p.catalog_id: p for p in catalog.products}
    for pid in ("B04", "B12", "B13", "B15", "B16", "B17", "B27"):  # expected_constraints fragrance_free
        assert fragrance_free(by_id[pid].ingredients), pid
    for pid in ("B28", "B34"):  # not sensitive-slot products (essential oils)
        assert not fragrance_free(by_id[pid].ingredients), pid


def test_product_records_keep_file_order(catalog):
    records = product_records(catalog)
    assert [r.id for r in records] == list(range(1, 38))
    assert [r.name for r in records] == [p.name for p in catalog.products]
    assert records[0].ingredients == catalog.products[0].ingredients


def test_the_cleaning_of_every_row_is_recorded(catalog):
    """A cleaning rule or directive that changes any row's names fails here until the
    snapshot is re-recorded (UPDATE_SNAPSHOTS=1) and the diff reviewed."""
    actual = {p.catalog_id: {"names": list(p.ingredient_names), "log": list(p.cleaning_log)}
              for p in catalog.products}
    check_snapshot("catalog_cleaning", actual)


def test_the_verbatim_text_is_kept_byte_for_byte():
    for row in ROWS:
        assert verbatim_sha256(row["ingredients_verbatim"]) == row["verbatim_sha256"], row["catalog_id"]


# --------------------------------------------------------------------------------------
# Every rule turns a bad row away (one good row, changed one field at a time)
# --------------------------------------------------------------------------------------


def changed(pid="B22", **fields):
    row = copy.deepcopy(BY_ID[pid])
    row.update(fields)
    if "ingredients_verbatim" in fields and "verbatim_sha256" not in fields:
        row["verbatim_sha256"] = verbatim_sha256(fields["ingredients_verbatim"])
    return row


def problems(*rows):
    products, found = check_rows(list(rows))
    return found


def test_a_good_row_passes():
    assert problems(changed()) == []


@pytest.mark.parametrize(("fields", "expected"), [
    ({"ingredients_verbatim": "Aqua, Niacinamide, Mystery Extract"}, "unreviewed ingredient names ['mystery extract']"),
    ({"ingredients_verbatim": "Aqua, Niacinamide: 10%"}, "names that can't be normalised"),
    ({"source_url": "http://theordinary.com/x"}, "is not an https URL"),
    ({"source_url": ""}, "is not an https URL"),
    ({"date_checked": "06/10/2026"}, "is not a YYYY-MM-DD date"),
    ({"fetch_status": "ok_names_only"}, "can't be seeded"),
    ({"market": "india"}, "doesn't match fetch_status"),
    ({"list_kind": "composition"}, "only a full ingredient list"),
    ({"verbatim_sha256": "0" * 64}, "doesn't match verbatim_sha256"),
    ({"category": "toner"}, "category 'toner'"),
    ({"texture": "foam"}, "texture 'foam'"),
    ({"foaming": "foaming"}, "allowed only on a cleanser"),
    ({"spf": 30}, "only a sunscreen has an SPF"),
    ({"expected_constraints": ["has_unicorn"]}, "unknown constraints ['has_unicorn']"),
    ({"expected_constraints": ["has_niacinamide", "has_retinoid"]}, "aren't recorded in known_mismatches"),
    ({"known_mismatches": {"has_niacinamide": "x"}}, "no longer fail"),
    ({"cleaning": {"corrections": [["not in the text", "x"]]}}, "cleaning: Correction text"),
    ({"cleaning": {"split_on": [" or "]}}, "cleaning: Unknown blend separators"),
])
def test_each_rule_turns_a_bad_row_away(fields, expected):
    found = problems(changed(**fields))
    assert any(expected in p for p in found), found
    assert all(p.startswith("B22: ") for p in found)


def test_missing_and_unknown_fields_are_errors():
    row = changed()
    del row["source_url"]
    row["sourceurl"] = "https://x.example"
    found = problems(row)
    assert any("missing fields ['source_url']" in p for p in found)
    assert any("unknown fields ['sourceurl']" in p for p in found)


def test_a_sunscreen_needs_a_matching_labelled_spf_of_at_least_30():
    assert problems(changed("B15")) == []
    assert any("at least 30" in p for p in problems(changed("B15", spf=25, spf_verbatim="SPF 25")))
    assert any("doesn't match spf_verbatim" in p for p in problems(changed("B15", spf=30)))
    assert any("at least 30" in p for p in problems(changed("B15", spf=None)))


def test_one_row_per_product():
    twin = changed(catalog_id="B99", sheet_row=999, source_url="https://example.com/b99")
    assert any("the same (brand, name)" in p for p in problems(changed(), twin))
    other = changed(catalog_id="B99", name="Another", sheet_row=999)
    assert any("the same source_url" in p for p in problems(changed(), other))
    assert any("the same catalog_id" in p for p in problems(changed(), changed(name="Another", sheet_row=999,
                                                                                  source_url="https://e.com/x")))


def test_every_problem_is_listed_and_nothing_loads(tmp_path):
    bad = {**DATA, "products": [changed(source_url="http://x"), changed("B15", spf=25, catalog_id="B98",
                                                                      sheet_row=998, source_url="https://e.com/y")]}
    path = tmp_path / "products.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(CatalogError) as error:
        load_catalog(path)
    assert len(error.value.problems) >= 2
    assert {p.split(":")[0] for p in error.value.problems} >= {"B22", "B98"}


NOT_PROMOTED = {"A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A10", "A11", "A12", "A14", "B05", "B33"}


def test_the_load_report_lists_every_row_and_why_staging_rows_were_left_out(catalog):
    text = format_report(catalog)
    assert "## Rows loaded (37)" in text
    for p in catalog.products:
        assert f"| {p.catalog_id} | {p.brand} | {p.name} | {p.category} | {p.market} |" in text
    assert "## Rows refused at load\n(none:" in text
    assert {pid for pid, _ in catalog.not_promoted} == NOT_PROMOTED
    for pid, reason in catalog.not_promoted:
        assert f"- {pid}: {reason}" in text
    assert "- B34: anhydrous_oil" in text


def test_a_staging_row_is_either_in_the_catalog_or_not_promoted(tmp_path):
    bad = {**DATA, "not_promoted": [*DATA["not_promoted"], {"catalog_id": "B22", "reason": "x"},
                                    {"catalog_id": "B05", "reason": "again"}, {"catalog_id": "B90"}]}
    path = tmp_path / "products.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(CatalogError) as error:
        load_catalog(path)
    assert set(error.value.problems) == {
        "B22: listed both as a catalog row and as not promoted",
        "B05: listed 2 times as not promoted",
        "B90: a not_promoted entry needs exactly a catalog_id and a reason",
    }


def test_the_command_prints_every_refused_row_when_the_load_stops(tmp_path, capsys):
    assert run() == 0
    assert "# Catalog load report: products-1.0.0 (37 products" in capsys.readouterr().out
    bad = {**DATA, "products": [changed(source_url="http://x"), *ROWS[1:]]}
    path = tmp_path / "products.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert run(path) == 1
    out = capsys.readouterr().out
    assert out.startswith("# Catalog load stopped: nothing loaded\n\n## Rows refused at load\n- B22: ")
    assert "Rows loaded" not in out


def test_every_constraint_name_in_the_catalog_has_a_check():
    used = {c for row in ROWS for c in (*row["expected_constraints"], *row["preferred"])}
    assert used <= set(cfg.CONSTRAINTS)
