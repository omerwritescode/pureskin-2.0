"""Evaluate the content-based ranker on a grid of profiles (roadmap 7c-ii).

    python -m app.services.recommendation.evaluate                  # full report (a few minutes)
    python -m app.services.recommendation.evaluate --no-timing      # deterministic part only
    python -m app.services.recommendation.evaluate --update-readme  # rewrite README's results

Every number comes from the real functions (build_routine, the ranker, explain) on the
seeded catalog (backend/catalog/products.json through the catalog loader, in file order, so
ids match a freshly seeded database; tests pass the fixture catalog instead). Nothing
is entered by hand. The output is deterministic markdown, apart from the build-time
section, which --no-timing leaves out. While recommendation_config.CATALOG_IS_PLACEHOLDER
is set, every table carries the placeholder banner: the numbers describe the method on 24
synthetic products and are not report results.

The ranker's weights were set before this evaluation and are never tuned to it. What it
measures is how the ranker behaves (which picks it changes, how stable they are), not
whether a routine is good for anyone's skin: there is no outcome data.
"""

import argparse
import itertools
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from app.services.ingredients import INGREDIENT_CONFIG_VERSION
from app.services.questionnaire.questionnaire_config import (
    CONFIG_VERSION as QUESTIONNAIRE_CONFIG_VERSION,
)

from . import recommendation_config as rcfg
from . import routine_config as cfg
from .engine import (
    AVOID,
    DUPLICATE,
    EXCLUDED_INGREDIENT,
    EXISTING_CONFLICT,
    FALLBACK,
    FRAGRANCE,
    RANKED,
    RULE_ORDER,
    SESSION,
    STRONG_ACTIVE,
    UNKNOWN,
    RankOptions,
    build_routine,
    conflict_keys,
    conflict_table,
    kept_in_order,
    product_record,
    random_order,
    step_targets_strong,
)
from .ranker import Scorer, band_name
from .rules import BASE, Requirement

# ======================================================================================
# Settings (they choose what is measured, never what the ranker does)
# ======================================================================================
SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
SKIN_TYPES = ("oily", "dry", "combination", "normal")
THIN = 5  # a slot with fewer eligible products than this is thin
VERY_THIN = 3  # ... and very thin
# Why a requirement had no eligible product: the Exclusion codes of the products that met it.
CAUSE_NAMES = {
    UNKNOWN: "unreviewed ingredient names",
    STRONG_ACTIVE: "a strong active (sensitive skin)",
    EXCLUDED_INGREDIENT: "L-ascorbic acid (sensitive skin)",
    FRAGRANCE: "fragrance (sensitive skin)",
    SESSION: "an evening-only active (morning)",
    AVOID: "the avoid list",
    DUPLICATE: "already uses one of its family",
    EXISTING_CONFLICT: "clashes with an active in use",
}
TAG_CAUSES = (AVOID, DUPLICATE, EXISTING_CONFLICT)  # rules that need questionnaire tags
VARIANTS = (  # ablations: RANKED with one ordering rule switched off
    ("without strong-active demotion", RankOptions(strong_last=False)),
    ("without conflict-safe first", RankOptions(conflict_safe=False)),
    ("without concern-priority choosing order", RankOptions(priority_order=False)),
    ("rule order (7c-i)", RULE_ORDER),
)
# Gaps already known before this evaluation, and the slots that show them:
# (label, [(category, source, keywords)], who it concerns: a score that must be High, sensitive only).
KNOWN_GAPS = (
    ("Morning pigmentation product without AHAs",
     [("serum", "pigmentation_score", ("alpha arbutin",))], "pigmentation_score", False),
    ("A non-retinoid wrinkle option for sensitive skin",
     [("serum", "wrinkle_score", ("retinol",)), ("moisturiser", "wrinkle_score", ("peptide",))],
     "wrinkle_score", True),
    ("Gentle non-foaming cleansers",
     [("cleanser", BASE, ("cream",))], None, False),
    ("The empty morning dark-spot step",
     [("serum", "pigmentation_score", ("alpha arbutin",))], "pigmentation_score", False),
)


@dataclass(frozen=True)
class Settings:
    skin_types: tuple[str, ...] = SKIN_TYPES
    levels: tuple[int, ...] = (15, 45, 80)  # Low, Moderate and High band midpoints
    scenario_levels: tuple[int, ...] = (15, 80)
    scenarios: tuple[str, ...] | None = None  # None: every tag scenario
    random_seeds: int = 100
    timing: bool = True


FULL = Settings()


def tags(**fields) -> dict:
    return {"version": QUESTIONNAIRE_CONFIG_VERSION, "actives_in_use": [], "products_in_use": [],
            "avoid": [], "stated_concern": None, **fields}


# The user's current products and avoid list, as stored in questionnaire_tags.
TAG_SCENARIOS = {
    "none answered": tags(),
    "retinol": tags(actives_in_use=["retinol"]),
    "prescription retinoid": tags(actives_in_use=["prescription_retinoid"]),
    "retinoid checkbox": tags(products_in_use=["retinoid"]),
    "salicylic acid": tags(actives_in_use=["salicylic acid"]),
    "benzoyl peroxide": tags(actives_in_use=["benzoyl peroxide"]),
    "vitamin C": tags(actives_in_use=["ascorbic acid"]),
    "niacinamide": tags(actives_in_use=["niacinamide"]),
    "exfoliant checkbox": tags(products_in_use=["exfoliant"]),
    "avoid fragrance": tags(avoid=["fragrance"]),
    "avoid acids": tags(avoid=["acids"]),
    "avoid alcohol, sulfates, parabens, lanolin": tags(avoid=["alcohol", "sulfates", "parabens", "lanolin"]),
}


# ======================================================================================
# Data
# ======================================================================================


def seed_catalog():
    """The catalog seed.py seeds (backend/catalog/products.json, through the catalog loader)
    as product records (ids in file order) and the conflict table."""
    import seed  # backend/seed.py: its CONFLICTS only; no database connection is made
    from app.services.catalog import load_catalog, product_records

    return product_records(load_catalog()), conflict_table(seed.CONFLICTS)


@dataclass(frozen=True)
class Case:
    skin_type: str
    sensitive: bool
    levels: tuple[int, ...]  # in SCORES order
    scenario: str | None
    profile: object = field(compare=False)


def make_case(skin_type, sensitive, levels, scenario=None, questionnaire_tags=None) -> Case:
    profile = SimpleNamespace(skin_type=skin_type, is_sensitive=sensitive,
                              questionnaire_tags=questionnaire_tags, **dict(zip(SCORES, levels)))
    return Case(skin_type, sensitive, tuple(levels), scenario, profile)


def base_grid(settings: Settings) -> list[Case]:
    """Skin type x sensitivity x every band combination of the five scores; no tags."""
    return [make_case(s, sens, levels) for s, sens, levels in itertools.product(
        settings.skin_types, (False, True), itertools.product(settings.levels, repeat=len(SCORES)))]


def scenario_grid(settings: Settings) -> list[Case]:
    names = settings.scenarios or tuple(TAG_SCENARIOS)
    return [make_case(s, sens, levels, name, TAG_SCENARIOS[name]) for name in names
            for s, sens, levels in itertools.product(
                settings.skin_types, (False, True), itertools.product(settings.scenario_levels, repeat=len(SCORES)))]


def with_goal(case: Case, goal: str) -> object:
    return SimpleNamespace(**{**vars(case.profile), "questionnaire_tags": tags(stated_concern=goal)})


# ======================================================================================
# What a routine picked
# ======================================================================================
SESSIONS = (cfg.AM, cfg.PM)


def sessions(routine):
    return ((cfg.AM, routine.am), (cfg.PM, routine.pm))


def slot(session, req) -> tuple:
    return (session, req.category, req.source, req.keywords)


def pick_map(routine) -> dict[tuple, int]:
    """Slot -> the product kept in it."""
    out = {}
    for session, steps in sessions(routine):
        for step in kept_in_order(steps):
            key = slot(session, step.req)
            assert key not in out, key
            out[key] = step.product.id
    return out


def pick_set(routine) -> frozenset:
    """S = {(session, category, product id)}, for the Jaccard index."""
    return frozenset((session, step.req.category, step.product.id)
                     for session, steps in sessions(routine) for step in kept_in_order(steps))


def changed_slots(a: dict, b: dict) -> int:
    return sum(a.get(k) != b.get(k) for k in set(a) | set(b))


def change_reason(step) -> str | None:
    """Why the ranker's pick differs from the step's rule-order pick (None: it doesn't).

    The first sort key that sets them apart; the keyword tiers are equal, since rule order
    is keyword order.
    """
    pick, rule = step.ranking.ranked[0], step.ranking.rule_order_pick
    if pick.product.id == rule.product.id:
        return None
    if rule.strong_outside_its_step and not pick.strong_outside_its_step:
        return "strong"
    if rule.clashes_with and not pick.clashes_with:
        return "conflict"
    return "score"


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def neighbours(cases: list[Case], levels: tuple[int, ...]):
    """Pairs of base-grid cases that differ in one score by one band: (i, j, score, transition)."""
    index = {(c.skin_type, c.sensitive, c.levels): i for i, c in enumerate(cases)}
    for i, c in enumerate(cases):
        for k, score in enumerate(SCORES):
            at = levels.index(c.levels[k])
            if at + 1 < len(levels):
                up = c.levels[:k] + (levels[at + 1],) + c.levels[k + 1:]
                j = index[(c.skin_type, c.sensitive, up)]
                yield i, j, score, f"{band_name(levels[at])}↔{band_name(levels[at + 1])}"


# ======================================================================================
# Formatting
# ======================================================================================


def banner() -> list[str]:
    return [f"> **{rcfg.PLACEHOLDER_BANNER}**", ""] if rcfg.CATALOG_IS_PLACEHOLDER else []


def pct(n: int, d: int) -> str:
    return f"{n:,} / {d:,} ({100 * n / d:.1f}%)" if d else "–"


def table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out + [""]


def para(*parts: str) -> list[str]:
    """One paragraph (its parts joined) and a blank line."""
    return ["".join(parts), ""]


def section(title: str, *parts: list[str]) -> list[str]:
    out = [f"## {title}", "", *banner()]
    for part in parts:
        out += part
    return out


def rule_name(source: str) -> str:
    if source == BASE:
        return "base"
    if source in rcfg.SCORE_NAMES:
        return f"{rcfg.SCORE_NAMES[source]} High"
    if source == cfg.SENSITIVE:
        return "sensitive"
    if source == FALLBACK:
        return "core fallback"
    return source


def slot_name(category: str, source: str, keywords: tuple, session_list=None) -> str:
    when = "/".join(s.upper() for s in session_list) + " " if session_list else ""
    what = " or ".join(keywords) if keywords else "any"
    return f"{when}{category}: {rule_name(source)} ({what})"


# ======================================================================================
# The measures
# ======================================================================================


@dataclass
class Run:
    """One mode's routines over a grid."""

    routines: list
    picks: list[dict] = field(default_factory=list)
    sets: list[frozenset] = field(default_factory=list)

    def __post_init__(self):
        self.picks = [pick_map(r) for r in self.routines]
        self.sets = [pick_set(r) for r in self.routines]


def run(cases, catalog, conflicts, options=RANKED) -> Run:
    return Run([build_routine(c.profile, catalog, conflicts, options) for c in cases])


def choice_steps(routine):
    """Kept steps with a choice (2 or more eligible products)."""
    return [s for _, steps in sessions(routine) for s in kept_in_order(steps) if len(s.ranking.rule_order) > 1]


def quality(r: Run, scorers, pairs) -> dict:
    steps = [(i, s) for i, routine in enumerate(r.routines) for s in choice_steps(routine)]
    matched = sum(bool(scorers[i].score(s.product).positive_terms) for i, s in steps)
    return {
        "face": (matched, len(steps)),
        "score": statistics.fmean(scorers[i].score(s.product).score for i, s in steps) if steps else 0.0,
        "dropped": sum(s.removed for routine in r.routines for _, steps_ in sessions(routine) for s in steps_),
        "coverage": len({pid for picks in r.picks for pid in picks.values()}),
        "jaccard": statistics.fmean(jaccard(r.sets[i], r.sets[j]) for i, j, _, _ in pairs) if pairs else 1.0,
    }


def responsiveness(cases: list[Case], ranked: Run, rule: Run) -> list[list]:
    counts = Counter()
    for routine in ranked.routines:
        for _, steps in sessions(routine):
            for step in kept_in_order(steps):
                counts["steps"] += 1
                ranking = step.ranking.ranked
                if len(ranking) == 1:
                    counts["single"] += 1
                    continue
                counts["choice"] += 1
                reason = change_reason(step)
                if reason:
                    counts[reason] += 1
                elif all(r.score == 0 for r in ranking):
                    counts["zero"] += 1
                else:
                    counts["kept"] += 1
    differ = sum(a != b for a, b in zip(ranked.picks, rule.picks))
    c = counts
    return [
        ["Kept steps", f"{c['steps']:,}"],
        ["… with one eligible product (no choice)", pct(c["single"], c["steps"])],
        ["… with 2 or more eligible products", pct(c["choice"], c["steps"])],
        ["   every candidate scores zero: rule order kept", pct(c["zero"], c["choice"])],
        ["   scores differ, the rule-order pick still ranks first", pct(c["kept"], c["choice"])],
        ["   pick differs from the step's rule-order pick: higher score", pct(c["score"], c["choice"])],
        ["   pick differs: strong active outside its step ranked last", pct(c["strong"], c["choice"])],
        ["   pick differs: conflict-safe first", pct(c["conflict"], c["choice"])],
        ["Profiles whose routine differs from the rule-order routine", pct(differ, len(cases))],
    ]


def ablations(cases, catalog, conflicts, ranked: Run) -> list[list]:
    rows = [["RANKED (all rules on)", "–", "–", f"{sum(s.removed for r in ranked.routines for _, st in sessions(r) for s in st):,}"]]
    for name, options in VARIANTS:
        other = run(cases, catalog, conflicts, options)
        profiles = sum(a != b for a, b in zip(ranked.picks, other.picks))
        slots = sum(changed_slots(a, b) for a, b in zip(ranked.picks, other.picks))
        dropped = sum(s.removed for r in other.routines for _, st in sessions(r) for s in st)
        rows.append([name, pct(profiles, len(cases)), f"{slots:,}", f"{dropped:,}"])
    return rows


def baselines(cases, catalog, conflicts, ranked: Run, rule: Run, scorers, pairs, seeds: int) -> list[list]:
    def row(name, q):
        return [name, pct(*q["face"]), f"{q['score']:.3f}", f"{q['dropped']:,}",
                f"{q['coverage']} / {len(catalog)}", f"{q['jaccard']:.3f}"]

    rows = [row("ranked", quality(ranked, scorers, pairs)), row("rule order (7c-i)", quality(rule, scorers, pairs))]
    if seeds:
        qs = [quality(run(cases, catalog, conflicts, random_order(seed)), scorers, pairs) for seed in range(seeds)]

        def ms(values, fmt):
            values = list(values)
            sd = statistics.stdev(values) if len(values) > 1 else 0.0
            return f"{format(statistics.fmean(values), fmt)} ± {format(sd, fmt)}"

        rows.append([
            f"random pick, {seeds} seeds (mean ± sd)",
            ms((100 * q["face"][0] / q["face"][1] for q in qs), ".1f") + "%",
            ms((q["score"] for q in qs), ".3f"),
            ms((q["dropped"] for q in qs), ".1f"),
            ms((q["coverage"] for q in qs), ".1f") + f" / {len(catalog)}",
            ms((q["jaccard"] for q in qs), ".3f"),
        ])
    return rows


def consistency(ranked: Run, rule: Run, pairs) -> list[list]:
    groups = defaultdict(list)
    for i, j, score, transition in pairs:
        groups[(score, transition)].append((i, j))
        groups[("all", transition)].append((i, j))
        groups[("all", "all")].append((i, j))

    def measures(r: Run, members):
        js = [jaccard(r.sets[i], r.sets[j]) for i, j in members]
        shared = [(r.picks[i][k] == r.picks[j][k]) for i, j in members for k in set(r.picks[i]) & set(r.picks[j])]
        return [f"{statistics.fmean(js):.3f}", f"{100 * sum(x == 1.0 for x in js) / len(js):.1f}%",
                f"{100 * sum(shared) / len(shared):.1f}%" if shared else "–"]

    order = [*SCORES, "all"]
    rows = []
    for key in sorted(groups, key=lambda k: (order.index(k[0]), k[1])):
        members = groups[key]
        score, transition = key
        name = rcfg.SCORE_NAMES.get(score, score)
        rows.append([name, transition, f"{len(members):,}", *measures(ranked, members), *measures(rule, members)])
    return rows


def leave_one_out(cases, catalog, conflicts, base: Run, options) -> tuple[set, int]:
    """Remove one product the routine didn't choose, rebuild, and compare the picks.

    Returns the (removed product id, case index) pairs whose picks changed, and how many
    pairs were tried.
    """
    tried, changed = 0, set()
    for removed in catalog:
        reduced = [p for p in catalog if p.id != removed.id]
        for i, (case, routine) in enumerate(zip(cases, base.routines)):
            if removed.id in {s.product.id for _, steps in sessions(routine) for s in steps}:
                continue  # chosen by a step (kept or later removed for a conflict)
            tried += 1
            if pick_map(build_routine(case.profile, reduced, conflicts, options)) != base.picks[i]:
                changed.add((removed.id, i))
    return changed, tried


def stability_rows(cases, catalog, ranked: tuple[set, int], rule: tuple[set, int]) -> list[list]:
    def row(name, changed, tried):
        per_product = Counter(pid for pid, _ in changed)
        return [name, pct(len(changed), tried), pct(len({i for _, i in changed}), len(cases)),
                f"{len(per_product)} / {len(catalog)}", pct(max(per_product.values(), default=0), len(cases))]

    return [row("ranked", *ranked), row("rule order (7c-i)", *rule),
            row("ranked only (changes rule order doesn't make)", ranked[0] - rule[0], ranked[1])]


def stated_goal(cases, catalog, conflicts, ranked: Run) -> list[list]:
    rows = []
    for goal, score in rcfg.STATED_CONCERN_SCORES.items():
        k = SCORES.index(score)
        by_band = defaultdict(list)
        for i, case in enumerate(cases):
            by_band[band_name(case.levels[k])].append(i)
        for band in ("Low", "Moderate", "High"):
            members = by_band.get(band, [])
            if not members:
                continue
            changed = sum(
                pick_map(build_routine(with_goal(cases[i], goal), catalog, conflicts)) != ranked.picks[i]
                for i in members)
            rows.append([f"{goal} ({rcfg.SCORE_NAMES[score]} score)", band, pct(changed, len(members))])
    return rows


def coverage(catalog, runs: dict[str, tuple[list[Case], Run]]) -> list[list]:
    rows = []
    for name, (cases, r) in runs.items():
        picked = {pid for picks in r.picks for pid in picks.values()}
        with_alt = picked | {a.product.id for routine in r.routines for _, steps in sessions(routine)
                             for s in kept_in_order(steps) for a in s.alternatives}
        sizes = [len(s.ranking.ranked) for routine in r.routines for _, steps in sessions(routine)
                 for s in kept_in_order(steps)]
        thin, very_thin = (
            sum(any(len(s.ranking.ranked) < limit for _, steps in sessions(routine) for s in kept_in_order(steps))
                for routine in r.routines)
            for limit in (THIN, VERY_THIN))
        unfilled = sum(len(routine.unfilled) for routine in r.routines)
        rows += [
            [name, "products picked at least once", pct(len(picked), len(catalog))],
            [name, "… also counting alternatives", pct(len(with_alt), len(catalog))],
            [name, "eligible products per kept step (min / median / max)",
             f"{min(sizes)} / {statistics.median(sizes):g} / {max(sizes)}"],
            [name, f"profiles with a kept step under {THIN} eligible products", pct(thin, len(cases))],
            [name, f"profiles with a kept step under {VERY_THIN} eligible products", pct(very_thin, len(cases))],
            [name, "requirements no eligible product met (each with a warning)", f"{unfilled:,}"],
        ]
    return rows


def cause_text(codes: tuple[str, ...]) -> str:
    if not codes:
        return "no product in the catalog meets it"
    return "every product meeting it is left out: " + "; ".join(CAUSE_NAMES[c] for c in codes)


def unfilled_breakdown(runs: dict[str, tuple[list[Case], Run]], scenarios: tuple[str, ...]) -> list[list]:
    """Requirements no eligible product met, by slot, cause and outcome, per grid."""
    counts: dict[tuple, Counter] = defaultdict(Counter)
    seen: dict[tuple, set] = defaultdict(set)
    for grid, (cases, r) in runs.items():
        for case, routine in zip(cases, r.routines):
            for u in routine.unfilled:
                key = (slot_name(u.req.category, u.req.source, u.req.keywords, [u.session]), cause_text(u.codes),
                       "the core step fell back" if u.fell_back else "no step")
                counts[key][grid] += 1
                if case.scenario:
                    seen[key].add(case.scenario)
    rows = []
    for key in sorted(counts, key=lambda k: (-sum(counts[k].values()), k)):
        names = [n for n in scenarios if n in seen[key]]
        where = "all" if len(names) == len(scenarios) else ", ".join(names) or "–"
        rows.append([*key, *(f"{counts[key][grid]:,}" for grid in runs), where])
    rows.append(["Total", "", "", *(f"{sum(c[grid] for c in counts.values()):,}" for grid in runs), ""])
    return rows


def unfilled_note(runs: dict[str, tuple[list[Case], Run]], settings: Settings) -> list[str]:
    """What differs between the grids' unfilled counts, from the data."""
    parts = []
    for grid, (cases, r) in runs.items():
        total = sum(len(routine.unfilled) for routine in r.routines)
        tagged = sum(1 for routine in r.routines for u in routine.unfilled if set(u.codes) & set(TAG_CAUSES))
        parts.append(f"{grid}: {total:,} over {len(cases):,} profiles ({total / len(cases):.2f} per profile), "
                     f"{tagged:,} of them caused by a rule that needs tags")
    high = {name: 1 / len(levels) for name, levels in (("base", settings.levels), ("tags", settings.scenario_levels))}
    return para("; ".join(parts) + ". ",
                f"A score is High in {high['base']:.0%} of base-grid profiles and {high['tags']:.0%} of tag-grid ",
                "profiles (band midpoints per score), so the steps only a High score adds, including those that ",
                "often have no eligible product, come up more often per profile on the tag grid. Causes that need ",
                "tags (the avoid list, a duplicate of an active in use, a clash with one) exist only there. Each ",
                "product counts under its first hard-rule reason (an active in use is checked before the ",
                "morning rules).")


# --------------------------------------------------------------------------------------
# Catalog gaps
# --------------------------------------------------------------------------------------


def _step_sessions(source: str, category: str, keywords: tuple) -> tuple[str, ...]:
    for score, steps in cfg.SCORE_STEPS:
        for step in steps:
            if score == source and step[0] == category and tuple(step[1]) == keywords:
                return tuple(step[2])
    return SESSIONS


def dropped_for_sensitive(routine) -> list[tuple]:
    """Steps a sensitive-skin substitution dropped (their warning is in the routine)."""
    out = []
    for (source, category, keywords), (replacement, message, _) in cfg.SENSITIVE_SUBSTITUTIONS.items():
        if replacement is None and message in routine.warnings:
            out += [(session, category, source, keywords) for session in _step_sessions(source, category, keywords)]
    return out


@dataclass
class SlotStats:
    """One slot (category, rule, keywords) over a grid. Events are (case index, session)."""

    filled: dict = field(default_factory=dict)  # event -> eligible products
    removed: set = field(default_factory=set)  # filled, then removed by conflict resolution
    empty_excluded: set = field(default_factory=set)  # every product meeting it left out by a hard rule
    empty_missing: set = field(default_factory=set)  # no product in the catalog meets it
    dropped: set = field(default_factory=set)  # dropped for sensitive skin (all strong actives)
    others: Counter = field(default_factory=Counter)  # conflict keys the session's other picks hold

    def only(self, members: set) -> "SlotStats":
        keep = lambda events: {e for e in events if e[0] in members}
        return SlotStats({e: n for e, n in self.filled.items() if e[0] in members}, keep(self.removed),
                         keep(self.empty_excluded), keep(self.empty_missing), keep(self.dropped), self.others)

    @property
    def cases(self) -> set:
        return {i for i, _ in [*self.filled, *self.empty_excluded, *self.empty_missing, *self.dropped]}

    @property
    def sessions(self) -> list[str]:
        used = {s for _, s in [*self.filled, *self.empty_excluded, *self.empty_missing, *self.dropped]}
        return [s for s in SESSIONS if s in used]

    def under(self, limit: int) -> set:
        """Cases where the slot had under `limit` eligible products, none, or lost its product."""
        return ({i for (i, _), n in self.filled.items() if n < limit} | {i for i, _ in self.removed}
                | {i for i, _ in self.empty_excluded | self.empty_missing | self.dropped})

    @property
    def thin_cases(self) -> set:
        return self.under(THIN)

    def sizes_text(self) -> str:
        sizes = list(self.filled.values())
        return f"{min(sizes)} / {statistics.median(sizes):g} / {max(sizes)}" if sizes else "none filled"


def slot_stats(cases: list[Case], ranked: Run) -> dict[tuple, SlotStats]:
    stats = defaultdict(SlotStats)
    for i, routine in enumerate(ranked.routines):
        for session, steps in sessions(routine):
            kept = kept_in_order(steps)
            for step in steps:
                st = stats[(step.req.category, step.req.source, step.req.keywords)]
                st.filled[(i, session)] = len(step.ranking.ranked)
                if step.removed:
                    st.removed.add((i, session))
                for other in kept:
                    if other is not step:
                        st.others.update(set(conflict_keys(other.product)))
        for u in routine.unfilled:
            st = stats[(u.req.category, u.req.source, u.req.keywords)]
            (st.empty_excluded if u.excluded else st.empty_missing).add((i, u.session))
        for session, category, source, keywords in dropped_for_sensitive(routine):
            stats[(category, source, keywords)].dropped.add((i, session))
    return stats


def condition_text(kind: str, value) -> str:
    if kind == "ingredient":
        return f"lists {value}"
    if kind == "class":
        return f"lists an ingredient of the {value.replace('_', ' ')} class"
    if kind == "property":
        return {"mineral_only": "mineral UV filters only", "anhydrous_oil": "an oil with no water"}[value]
    if kind == "texture":
        return "texture " + ", ".join(v.replace("_", "-") for v in value)
    if kind == "foaming":
        return "foaming: " + ", ".join(v.replace("_", "-") for v in value)
    if kind == "min_spf":
        return f"SPF {value} or higher"
    raise ValueError(kind)


def requirement_text(category: str, keywords: tuple) -> str:
    if not keywords:
        return f"any {category}"
    return " or ".join(" and ".join(condition_text(k, v) for k, v in cfg.MATCHERS[kw]) for kw in keywords)


def key_name(key: str) -> str:
    if key.startswith("class:"):
        cls = key.removeprefix("class:")
        return cfg.SHORT_CLASS_NAMES.get(cls, (cls, cls.replace("_", " ")))[1]
    return key


def _groups(category: str, pairs, positive: bool = True) -> list[str]:
    """Target groups (config order) that apply to the category, with positive or negative weight."""
    out = []
    for group, weight in pairs:
        scope = rcfg.TARGET_GROUPS[group][1]
        if (weight > 0) == positive and (scope is None or category in scope):
            out.append(group)
    return out


def slot_targets(category: str, source: str, members: list[Case]) -> str:
    """The ranker targets of the slot's own rule and of the profiles it serves."""
    parts = []
    if source in rcfg.CONCERN_TARGETS:
        parts.append(f"{rcfg.CONCERN_NAMES[source]}: " + ", ".join(_groups(category, rcfg.CONCERN_TARGETS[source])))
    for skin in SKIN_TYPES:
        if any(c.skin_type == skin for c in members):
            parts.append(f"{skin} skin: " + (", ".join(_groups(category, rcfg.SKIN_TYPE_TARGETS[skin]))
                                             or "none in this category"))
    if any(c.sensitive for c in members):
        parts.append("sensitive skin: " + ", ".join(_groups(category, rcfg.SENSITIVE_TARGETS)))
    return "; ".join(parts)


def needs(cases: list[Case], conflicts, key: tuple, st: SlotStats) -> list[str]:
    category, source, keywords = key
    members = [cases[i] for i in sorted(st.thin_cases)]
    rules = []
    if any(c.sensitive for c in members):
        penalised = _groups(category, rcfg.SENSITIVE_TARGETS, positive=False)
        rules.append("for sensitive skin: no retinoid, benzoyl peroxide, AHA or BHA; no L-ascorbic acid; "
                     "fragrance-free" + (f"; ideally no {' or '.join(penalised)} (it lowers the rank)" if penalised else ""))
    if cfg.AM in st.sessions:
        rules.append("in the morning: no retinoid" + ("" if category in cfg.RINSE_OFF_CATEGORIES else " or AHA"))
    if not step_targets_strong(Requirement(category, keywords)):
        rules.append("ideally no strong active (it would rank last in this step)")
    clash = Counter()
    for a, b in conflicts:
        for mine, theirs in ((a, b), (b, a)):
            if st.others[theirs]:
                clash[mine] += st.others[theirs]
    if clash:
        names = [key_name(k) for k, _ in sorted(clash.items(), key=lambda kv: (-kv[1], kv[0]))]
        rules.append("nothing that clashes with a product these routines hold (in at least one profile): "
                     + ", ".join(dict.fromkeys(names)))
    return [
        f"category {category}; {requirement_text(category, keywords)}",
        "targets it would rank on: " + slot_targets(category, source, members),
        "exclusions: " + "; ".join(rules) if rules else "exclusions: none beyond the general rules",
    ]


def who(cases: list[Case], members: set, source: str) -> str:
    chosen = [cases[i] for i in members]
    skin = [s for s in SKIN_TYPES if any(c.skin_type == s for c in chosen)]
    sens = {c.sensitive for c in chosen}
    sens_text = "sensitive only" if sens == {True} else "not sensitive" if sens == {False} else "sensitive or not"
    rule = "" if source in (BASE, FALLBACK, cfg.SENSITIVE) else f"; {rcfg.SCORE_NAMES[source]} High"
    return f"{', '.join(skin)}; {sens_text}{rule}"


def gaps(cases: list[Case], conflicts, ranked: Run) -> tuple[list[list], list[str], list[list]]:
    stats = slot_stats(cases, ranked)
    thin = {k: st for k, st in stats.items() if st.thin_cases}
    order = list(cfg.CATEGORY_ORDER)
    keys = sorted(thin, key=lambda k: (order.index(k[0]), k[1] != BASE, k[1], k[2]))
    rows, details = [], []
    for key in keys:
        st = thin[key]
        category, source, keywords = key
        name = slot_name(category, source, keywords, st.sessions)
        rows.append([name, who(cases, st.thin_cases, source), pct(len(st.thin_cases), len(st.cases)),
                     pct(len(st.under(VERY_THIN)), len(st.cases)), st.sizes_text(), f"{len(st.removed):,}", f"{len(st.empty_excluded):,}",
                     f"{len(st.empty_missing):,}", f"{len(st.dropped):,}"])
        details += [f"- **{name}**"] + [f"  - {line}" for line in needs(cases, conflicts, key, st)]
    details.append("")
    known = []
    for label, slots, score, sensitive_only in KNOWN_GAPS:
        concerned = {i for i, c in enumerate(cases)
                     if (score is None or band_name(c.levels[SCORES.index(score)]) == "High")
                     and (not sensitive_only or c.sensitive)}
        who_text = ", ".join(filter(None, ["sensitive" if sensitive_only else "",
                                           f"{rcfg.SCORE_NAMES[score]} High" if score else ""])) or "all"
        for category, source, keywords in slots:
            st = stats.get((category, source, keywords), SlotStats()).only(concerned)
            name = slot_name(category, source, keywords, st.sessions)
            sizes = list(st.filled.values())
            status = (f"required by {pct(len(st.cases), len(concerned))}; "
                      + (f"filled {len(sizes):,} times (eligible min {min(sizes)}, max {max(sizes)}), "
                         f"{len(st.removed):,} of them removed for a conflict; " if sizes else "never filled; ")
                      + f"empty {len(st.empty_excluded) + len(st.empty_missing):,} times "
                        f"({len(st.empty_excluded):,} every product left out by a hard rule, "
                        f"{len(st.empty_missing):,} none in the catalog); "
                        f"dropped for sensitive skin {len(st.dropped):,} times")
            known.append([label, name, f"{who_text}: {len(concerned):,}", status])
    return rows, details, known


# ======================================================================================
# The report
# ======================================================================================


def report(settings: Settings = FULL, out=None, catalog=None) -> str:
    """The report on the seeded catalog, or on `catalog`: (product records, conflict table)."""
    catalog, conflicts = catalog if catalog is not None else seed_catalog()
    cases = base_grid(settings)
    scen = scenario_grid(settings)
    ranked, rule = run(cases, catalog, conflicts), run(cases, catalog, conflicts, RULE_ORDER)
    ranked_s, rule_s = run(scen, catalog, conflicts), run(scen, catalog, conflicts, RULE_ORDER)
    scorers = [Scorer(c.profile, catalog) for c in cases]
    pairs = list(neighbours(cases, settings.levels))

    lines = [
        "# Recommendation ranker: evaluation",
        "",
        *banner(),
        (f"Config versions: {rcfg.RECOMMENDATION_CONFIG_VERSION}, {cfg.ROUTINE_CONFIG_VERSION}, "
         f"{INGREDIENT_CONFIG_VERSION}, tags {QUESTIONNAIRE_CONFIG_VERSION}."),
        "",
        (f"Catalog: {len(catalog)} products, {len(conflicts)} conflict rows (seed.py). "
         f"Base grid: {len(cases):,} profiles ({len(settings.skin_types)} skin types × sensitive or not × "
         f"{len(settings.levels)} bands ({', '.join(map(str, settings.levels))}) for each of 5 scores; no tags). "
         f"Tag grid: {len(scen):,} profiles ({len(settings.scenarios or TAG_SCENARIOS)} current-product/avoid "
         f"scenarios × {len(settings.skin_types)} skin types × sensitive or not × "
         f"{len(settings.scenario_levels)} bands per score)."),
        "",
        ("The ranker's weights were set before this evaluation and are never tuned to it. "
         "Nothing here measures benefit to skin: there is no outcome data."),
        "",
    ]
    lines += section(
        "1. Responsiveness: where the ranker changes a pick",
        para("Per kept step, the ranker's pick against the same step's rule-order pick ",
             "(single-candidate steps counted separately), then whole routines against RULE_ORDER. ",
             "A pick is attributed to the first sort key that moved it away from the rule-order pick; ",
             "a key that keeps the rule-order pick first (e.g. demoting a higher-scoring strong active) ",
             "shows in section 2 instead."),
        table(["Base grid", "Count"], responsiveness(cases, ranked, rule)),
        table(["Tag grid", "Count"], responsiveness(scen, ranked_s, rule_s)),
    )
    lines += section(
        "2. What each ordering rule changes (base grid)",
        para("Each row switches one rule off and compares the routines with RANKED. ",
             "\"Steps dropped for a conflict\": steps conflict resolution removed (a lost step)."),
        table(["Variant", "Profiles with a different routine", "Slot picks that differ", "Steps dropped for a conflict"],
              ablations(cases, catalog, conflicts, ranked)),
    )
    lines += section(
        "3. Baselines (base grid)",
        para("Face validity: share of picks, in steps with 2 or more eligible products, that list at least one of ",
             "the profile's target ingredients. **Circular by construction: targets come from our own config. ",
             "This is not accuracy.** The mean target score is circular for the same reason."),
        table(["Ordering", "Face validity (circular)", "Mean target score (circular)",
               "Steps dropped for a conflict", "Products picked", "Neighbour Jaccard"],
              baselines(cases, catalog, conflicts, ranked, rule, scorers, pairs, settings.random_seeds)),
    )
    lines += section(
        "4. Consistency: neighbouring profiles (base grid)",
        para("Pairs of profiles that differ in one score by one band. S = {(session, category, product)}; ",
             "Jaccard |S∩S'| / |S∪S'|; slot agreement: same product in the slots both routines have. ",
             "Steps are added only in the High band, so in rule order a Low↔Moderate change never ",
             "changes a routine."),
        table(["Score", "Change", "Pairs", "Ranked mean J", "Ranked J = 1", "Ranked slot agreement",
               "Rule-order mean J", "Rule-order J = 1", "Rule-order slot agreement"],
              consistency(ranked, rule, pairs)),
    )
    lines += section(
        "5. Stability under catalog perturbation: leave one out (base grid)",
        para("Remove one product the profile's routine did not choose, rebuild, and compare the picks. ",
             "In ranked mode IDF moves (N and document frequencies change). Rule order is the control: ",
             "its changes come from the rules themselves (a sensitive-skin substitution applies only ",
             "when some product meets the step and every one is left out, so removing the only such ",
             "product turns the substitution off). The last row is what the ranker adds."),
        table(["Ordering", "(removed product, profile) pairs with changed picks",
               "Profiles changed by at least one removal", "Removals that change any routine",
               "Most profiles changed by one removal"],
              stability_rows(cases, catalog, leave_one_out(cases, catalog, conflicts, ranked, RANKED),
                             leave_one_out(cases, catalog, conflicts, rule, RULE_ORDER))),
    )
    lines += section(
        "6. The stated goal (base grid)",
        para("Share of profiles whose picks change when the questionnaire goal names a concern. ",
             "The goal multiplies that concern's weights after the band scale, so a goal whose ",
             "score is Low has no effect, by design."),
        table(["Goal", "Band of its score", "Profiles whose picks change"],
              stated_goal(cases, catalog, conflicts, ranked)),
    )
    grids = {"base": (cases, ranked), "tags": (scen, ranked_s)}
    lines += section(
        "7. Coverage",
        table(["Grid", "Measure", "Value"], coverage(catalog, grids)),
        ["Requirements no eligible product met, by cause (per session):", ""],
        unfilled_note(grids, settings),
        table(["Requirement", "Cause", "Then", "Base grid", "Tag grid", "Tag scenarios"],
              unfilled_breakdown(grids, settings.scenarios or tuple(TAG_SCENARIOS))),
    )
    rows, details, known = gaps(cases, conflicts, ranked)
    lines += section(
        f"8. Catalog gaps: slots with fewer than {THIN} eligible products (base grid)",
        para("Who a slot fails to serve is the profiles for which it had fewer than ",
             f"{THIN} eligible products, none, or lost its product to conflict resolution; the ",
             f"under-{VERY_THIN} column counts the same with fewer than {VERY_THIN}. ",
             "Eligible: min / median / max over the steps it filled."),
        table(["Slot", "Fails to serve", f"Under {THIN} / requiring it", f"Under {VERY_THIN} / requiring it",
               "Eligible", "Removed for a conflict", "Empty: hard rule", "Empty: none in catalog",
               "Dropped for sensitive skin"], rows),
        ["What a product in each thin slot would need (characteristics only):", ""],
        details,
        ["Known gaps:", ""],
        ["Each status counts only the profiles the gap concerns (events are per session).", ""],
        table(["Gap", "Slot", "Profiles concerned", "On this grid"], known),
    )
    if settings.timing:
        times = {}
        for name, options in (("ranked", RANKED), ("rule order", RULE_ORDER)):
            spent = []
            for c in cases:
                start = time.perf_counter()
                build_routine(c.profile, catalog, conflicts, options)
                spent.append(time.perf_counter() - start)
            times[name] = statistics.median(spent) * 1000
        lines += section(
            "9. Build time (not deterministic)",
            table(["Ordering", "Median ms per routine"], [[k, f"{v:.2f}"] for k, v in times.items()]),
        )
    text = "\n".join(lines).rstrip() + "\n"
    if out is not None:
        out.write(text)
    return text


README = Path(__file__).with_name("README.md")
README_START, README_END = "<!-- evaluation:start -->", "<!-- evaluation:end -->"


def update_readme(text: str, path: Path = README) -> None:
    """Replace the README's results (between the markers) with a generated report."""
    readme = path.read_text(encoding="utf-8")
    head, rest = readme.split(README_START)
    _, tail = rest.split(README_END)
    body = text.replace("\n## ", "\n### ").replace("# Recommendation ranker: evaluation\n\n", "", 1)
    path.write_text(f"{head}{README_START}\n{body}{README_END}{tail}", encoding="utf-8")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-timing", action="store_true", help="leave out the build-time section")
    parser.add_argument("--update-readme", action="store_true",
                        help="write the deterministic report into README.md (between its markers)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.update_readme:
        update_readme(report(Settings(timing=False)))
        print(f"Updated {README.name}")
    else:
        report(Settings(timing=not args.no_timing), sys.stdout)


if __name__ == "__main__":
    main()
