"""The evaluation module: deterministic output from the real functions, with the banner."""

import re

import pytest

import seed
from app.services.recommendation import evaluate
from app.services.recommendation import recommendation_config as rcfg
from app.services.recommendation import routine_config as cfg
from app.services.recommendation.evaluate import Settings, report
from app.services.recommendation.tests.test_engine import SEED_PRODUCTS

SMALL = Settings(skin_types=("oily", "dry"), levels=(15, 80), scenario_levels=(80,),
                 scenarios=("none answered", "retinol"), random_seeds=2, timing=False)


@pytest.fixture(scope="module")
def text() -> str:
    return report(SMALL)


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    return {part.splitlines()[0]: part for part in parts[1:]}


def test_the_report_is_deterministic(text):
    assert report(SMALL) == text


def test_every_section_and_the_header_carry_the_placeholder_banner(text):
    assert rcfg.CATALOG_IS_PLACEHOLDER  # until 7c-iii replaces the catalog
    banner = f"> **{rcfg.PLACEHOLDER_BANNER}**"
    header = text.split("\n## ")[0]
    assert banner in header
    found = sections(text)
    assert [title.split(".")[0] for title in found] == [str(n) for n in range(1, 9)]
    for title, body in found.items():
        assert banner in body, title


def test_without_the_placeholder_flag_there_is_no_banner(monkeypatch):
    monkeypatch.setattr(rcfg, "CATALOG_IS_PLACEHOLDER", False)
    assert rcfg.PLACEHOLDER_BANNER not in "\n".join(evaluate.banner())


def test_timing_is_a_separate_optional_section(text):
    assert "Build time" not in text  # timing=False
    tiny = Settings(skin_types=("dry",), levels=(80,), scenario_levels=(80,), scenarios=("none answered",),
                    random_seeds=0, timing=True)
    assert "## 9. Build time (not deterministic)" in report(tiny)


def test_the_readme_results_are_generated_for_the_current_versions():
    """README.md's results come from --update-readme, never typed by hand."""
    readme = evaluate.README.read_text(encoding="utf-8")
    results = readme.split(evaluate.README_START)[1].split(evaluate.README_END)[0]
    assert rcfg.RECOMMENDATION_CONFIG_VERSION in results and cfg.ROUTINE_CONFIG_VERSION in results
    assert (f"> **{rcfg.PLACEHOLDER_BANNER}**" in results) == rcfg.CATALOG_IS_PLACEHOLDER


def test_update_readme_replaces_only_the_marked_section(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(f"intro\n{evaluate.README_START}\nold\n{evaluate.README_END}\noutro\n", encoding="utf-8")
    evaluate.update_readme("# Recommendation ranker: evaluation\n\nnew\n## 1. A\n", path)
    assert path.read_text(encoding="utf-8") == (
        f"intro\n{evaluate.README_START}\nnew\n### 1. A\n{evaluate.README_END}\noutro\n")


def test_config_versions_and_face_validity_label(text):
    assert rcfg.RECOMMENDATION_CONFIG_VERSION in text and cfg.ROUTINE_CONFIG_VERSION in text
    assert "Circular by construction: targets come from our own config. This is not accuracy." in text


def test_a_goal_whose_score_is_low_changes_no_pick(text):
    rows = [line for line in sections(text)["6. The stated goal (base grid)"].splitlines()
            if line.startswith("| ") and "| Low |" in line]
    assert len(rows) == len(rcfg.STATED_CONCERN_SCORES)
    assert all(re.search(r"\| 0 / \d", row) for row in rows)


def test_the_gap_report_names_no_product(text):
    gaps = sections(text)["8. Catalog gaps: slots with fewer than 5 eligible products (base grid)"]
    for name, *_ in seed.PRODUCTS:
        assert name not in gaps


def test_the_unfilled_breakdown_adds_up_and_names_a_cause_for_each_requirement():
    catalog, conflicts = evaluate.seed_catalog()
    grids = {"base": (evaluate.base_grid(SMALL), None), "tags": (evaluate.scenario_grid(SMALL), None)}
    grids = {g: (cases, evaluate.run(cases, catalog, conflicts)) for g, (cases, _) in grids.items()}
    rows = evaluate.unfilled_breakdown(grids, SMALL.scenarios)
    totals = rows[-1]
    for k, (_, r) in enumerate(grids.values()):
        assert int(totals[3 + k].replace(",", "")) == sum(len(routine.unfilled) for routine in r.routines)
    for row in rows[:-1]:
        assert row[1] == "no product in the catalog meets it" or row[1].startswith("every product meeting it")
    assert set(evaluate.CAUSE_NAMES) >= {code for _, r in grids.values() for routine in r.routines
                                         for u in routine.unfilled for code in u.codes}


def test_the_catalog_is_the_seeded_one_in_seed_order():
    catalog, conflicts = evaluate.seed_catalog()
    assert [(p.id, p.name, p.ingredients, p.texture, p.foaming, p.spf) for p in catalog] == [
        (p.id, p.name, p.ingredients, p.texture, p.foaming, p.spf) for p in SEED_PRODUCTS]
    assert len(conflicts) == len(seed.CONFLICTS)


def test_neighbours_differ_in_one_score_by_one_band():
    cases = evaluate.base_grid(SMALL)
    pairs = list(evaluate.neighbours(cases, SMALL.levels))
    assert len(pairs) == len(cases) * len(evaluate.SCORES) // 2
    for i, j, score, transition in pairs:
        a, b = cases[i], cases[j]
        k = evaluate.SCORES.index(score)
        assert (a.skin_type, a.sensitive) == (b.skin_type, b.sensitive)
        assert [x != y for x, y in zip(a.levels, b.levels)] == [n == k for n in range(len(evaluate.SCORES))]
        assert transition == "Low↔High"


def test_the_grids_have_the_documented_sizes():
    assert len(evaluate.base_grid(evaluate.FULL)) == 4 * 2 * 3 ** 5 == 1944
    assert len(evaluate.scenario_grid(evaluate.FULL)) == len(evaluate.TAG_SCENARIOS) * 4 * 2 * 2 ** 5 == 3072


def test_every_known_gap_names_a_real_rule_step():
    steps = {(c, "base", tuple(k)) for steps in cfg.BASE_STEPS.values() for c, k, _, _ in steps}
    steps |= {(c, score, tuple(k)) for score, score_steps in cfg.SCORE_STEPS for c, k, _, _ in score_steps}
    for _, slots, score, _ in evaluate.KNOWN_GAPS:
        assert score is None or score in evaluate.SCORES
        for slot in slots:
            assert slot in steps, slot


def test_rule_order_never_differs_from_itself_and_ranked_picks_are_attributed():
    catalog, conflicts = evaluate.seed_catalog()
    cases = evaluate.base_grid(SMALL)
    rule = evaluate.run(cases, catalog, conflicts, evaluate.RULE_ORDER)
    for routine in rule.routines:
        for _, steps in evaluate.sessions(routine):
            for step in steps:
                assert evaluate.change_reason(step) is None
    ranked = evaluate.run(cases, catalog, conflicts)
    reasons = {evaluate.change_reason(s) for r in ranked.routines for _, st in evaluate.sessions(r) for s in st}
    assert reasons <= {None, "score", "strong", "conflict"}
